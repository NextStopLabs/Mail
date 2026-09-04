import email
import email.policy
import email.utils
import re
import hashlib
from email.header import decode_header
from email.message import Message
from typing import List, Dict, Any, Optional

# Sanitization: prefer nh3, fallback to bleach
try:
    import nh3
    HAS_NH3 = True
except ImportError:
    HAS_NH3 = False
    import bleach

def decode_mime_header(value: Optional[str]) -> str:
    if not value:
        return ""
    try:
        parts = decode_header(value)
        decoded = []
        for text, charset in parts:
            if isinstance(text, bytes):
                try:
                    decoded.append(text.decode(charset or "utf-8", errors="replace"))
                except Exception:
                    decoded.append(text.decode("utf-8", errors="replace"))
            else:
                decoded.append(text)
        return "".join(decoded)
    except Exception:
        return value

def parse_address(header_value: Optional[str]) -> List[Dict[str, str]]:
    if not header_value:
        return []
    parsed = email.utils.getaddresses([header_value])
    result = []
    for name, addr in parsed:
        result.append({"name": decode_mime_header(name), "email": addr})
    return result

def sanitize_html(html: str) -> str:
    if not html:
        return ""
    if HAS_NH3:
        allowed_tags = {
            "a", "abbr", "b", "blockquote", "br", "caption", "cite", "code", "col", "colgroup",
            "dd", "del", "div", "dl", "dt", "em", "h1", "h2", "h3", "h4", "h5", "h6",
            "hr", "i", "img", "li", "ol", "p", "pre", "span", "strong", "table", "tbody",
            "td", "tfoot", "th", "thead", "tr", "u", "ul", "font", "center"
        }
        allowed_attrs = {
            "a": {"href", "title", "target"},
            "img": {"src", "alt", "width", "height", "style"},
            "td": {"colspan", "rowspan", "style", "align"},
            "th": {"colspan", "rowspan", "style", "align"},
            "table": {"style", "border", "cellpadding", "cellspacing", "width"},
            "*": {"style", "class"},
        }
        cleaned = nh3.clean(
            html,
            tags=allowed_tags,
            attributes=allowed_attrs,
            link_rel=None,
        )
        cleaned = re.sub(r'href\s*=\s*["\']\s*javascript:[^"\']*["\']', 'href="#"', cleaned, flags=re.I)
        return cleaned
    else:
        allowed_tags = bleach.sanitizer.ALLOWED_TAGS.union({
            "p","br","div","span","img","table","tbody","thead","tr","td","th","ul","ol","li","h1","h2","h3","h4","a","blockquote","pre","code","hr","center","font"
        })
        allowed_attrs = {**bleach.sanitizer.ALLOWED_ATTRIBUTES, "img": ["src","alt","width","height","style"], "a": ["href","title"], "*": ["style"]}
        cleaned = bleach.clean(html, tags=allowed_tags, attributes=allowed_attrs, strip=True)
        cleaned = re.sub(r'javascript:', '', cleaned, flags=re.I)
        return cleaned

def extract_bodies(msg: Message) -> Dict[str, Any]:
    text_parts = []
    html_parts = []
    attachments = []
    inline_images = {}
    if msg.is_multipart():
        for part in msg.walk():
            if part.is_multipart():
                continue
            ctype = part.get_content_type()
            disp = (part.get_content_disposition() or "").lower()
            cid = part.get("Content-ID")
            filename = part.get_filename()
            if filename:
                filename = decode_mime_header(filename)
            payload = part.get_payload(decode=True)
            charset = part.get_content_charset() or "utf-8"
            if disp == "attachment" or (filename and disp != "inline"):
                size = len(payload) if payload else 0
                attachments.append({
                    "filename": filename or "unnamed",
                    "mime": ctype,
                    "size": size,
                    "cid": cid.strip("<>") if cid else None,
                    "part_index": None,
                })
                if cid:
                    inline_images[cid.strip("<>")] = part
                continue
            if ctype == "text/plain" and disp != "attachment":
                try:
                    text = payload.decode(charset, errors="replace") if payload else ""
                except Exception:
                    text = payload.decode("utf-8", errors="replace") if payload else ""
                if cid and ctype.startswith("image/"):
                    inline_images[cid.strip("<>")] = part
                else:
                    text_parts.append(text)
            elif ctype == "text/html" and disp != "attachment":
                try:
                    html = payload.decode(charset, errors="replace") if payload else ""
                except Exception:
                    html = payload.decode("utf-8", errors="replace") if payload else ""
                html_parts.append(html)
            elif ctype.startswith("image/") and cid:
                inline_images[cid.strip("<>")] = part
                if disp == "inline":
                    attachments.append({
                        "filename": filename or cid.strip("<>"),
                        "mime": ctype,
                        "size": len(payload) if payload else 0,
                        "cid": cid.strip("<>"),
                    })
            elif ctype.startswith("image/") or filename:
                attachments.append({
                    "filename": filename or "attachment",
                    "mime": ctype,
                    "size": len(payload) if payload else 0,
                    "cid": cid.strip("<>") if cid else None,
                })
    else:
        ctype = msg.get_content_type()
        payload = msg.get_payload(decode=True)
        charset = msg.get_content_charset() or "utf-8"
        if ctype == "text/html":
            html = payload.decode(charset, errors="replace") if payload else ""
            html_parts.append(html)
        else:
            text = payload.decode(charset, errors="replace") if payload else ""
            text_parts.append(text)
    text_body = "\n\n".join(text_parts) if text_parts else ""
    html_body = "\n".join(html_parts) if html_parts else ""
    if html_body:
        html_body = sanitize_html(html_body)
    return {
        "text": text_body,
        "html": html_body,
        "attachments": attachments,
        "inline_images": inline_images,
    }

# ----------------------------------------------------------------------
# Thread / Quote parsing enhancements
# ----------------------------------------------------------------------

MAX_QUOTE_DEPTH = 5

# Helpers for date parsing
def _try_parse_date(date_str: str) -> Optional[str]:
    if not date_str:
        return None
    # Normalize: replace " at " with " " for gmail style
    norm = re.sub(r'\s+at\s+', ' ', date_str, flags=re.I).strip()
    # try email.utils
    try:
        dt = email.utils.parsedate_to_datetime(norm)
        if dt:
            return dt.isoformat()
    except Exception:
        pass
    # Try with cleaned variant without trailing commas
    try:
        dt = email.utils.parsedate_to_datetime(norm.strip(" ,"))
        if dt:
            return dt.isoformat()
    except Exception:
        pass
    # fallback: try common date formats with regex extraction
    # Use fuzzy: search for date-like substring
    # Try dateutil if available
    try:
        from dateutil import parser as date_parser
        dt = date_parser.parse(norm, fuzzy=True)
        return dt.isoformat()
    except Exception:
        pass
    # Manual fallback: try to extract date without name
    try:
        # Remove leading "On " if any
        n2 = re.sub(r'^On\s+', '', norm, flags=re.I)
        from dateutil import parser as date_parser2
        dt = date_parser2.parse(n2, fuzzy=True)
        return dt.isoformat()
    except Exception:
        pass
    return None

def _extract_email(text: str) -> str:
    m = re.search(r'<([^>]+@[^>]+)>', text)
    if m:
        return m.group(1).strip()
    m2 = re.search(r'[\w\.\-+]+@[\w\.\-]+\.\w+', text)
    if m2:
        return m2.group(0).strip()
    return ""

def _strip_quote_prefix(text: str) -> str:
    """Remove leading > markers per line, handling >> etc."""
    lines = text.splitlines()
    stripped = []
    for line in lines:
        # Remove leading spaces, then one or more >, then optional space
        # Use re to remove only leading quote markers
        cleaned = re.sub(r'^\s*>+\s*', '', line)
        # If line was just ">" or ">>", then cleaned becomes "" -> keep as empty
        stripped.append(cleaned)
    return "\n".join(stripped).strip()

def extract_gmail_metadata(header_line: str) -> Dict[str, Any]:
    """Parse Gmail style: On ... wrote:"""
    raw = header_line.strip()
    # Remove On prefix and wrote: suffix
    inner = re.sub(r'^\s*On\s+', '', raw, flags=re.I)
    inner = re.sub(r'\s+wrote:\s*$', '', inner, flags=re.I)
    email_addr = _extract_email(inner)
    # Get name via parse_address on inner
    # parse_address may extract name correctly if email present
    addrs = parse_address(inner)
    # filter to valid emails (must contain @)
    valid_addrs = [a for a in addrs if a["email"] and "@" in a["email"]]
    name = ""
    if valid_addrs:
        # find addr matching email_addr or first with name
        for a in valid_addrs:
            if a["email"] and a["email"] == email_addr:
                name = a["name"]
                break
        if not name:
            # fallback: first addr name
            name = valid_addrs[0]["name"] if valid_addrs[0]["name"] else ""
            if not email_addr:
                email_addr = valid_addrs[0]["email"]
    elif addrs:
        # No valid email, try to use name part without email
        # Attempt to extract name as trailing capitalized words after date
        tmp_name_candidate = inner
        if email_addr:
            tmp_name_candidate = tmp_name_candidate.replace(email_addr, "")
        m_tmp = re.search(r'([A-Z][a-z]+(?:\s+[A-Z][a-z]+){0,2})\s*$', tmp_name_candidate)
        if m_tmp:
            poss = m_tmp.group(1)
            if not re.search(r'\b(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\b', poss, re.I) and not re.search(r'\d', poss):
                name = poss
        # ensure email remains empty if not valid
        if email_addr and "@" not in email_addr:
            email_addr = ""
        # If name appears to contain date (e.g., "Thu, Sep 3, 2026 at 4:47 PM Kai"), extract trailing name part
        if name and (re.search(r'\d', name) or re.search(r'\b(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\b', name, re.I) or re.search(r'\b(PM|AM)\b', name, re.I)):
            # Try to extract trailing name after date pattern
            # Look for pattern like " at ... PM <name>" or date end
            m2 = re.search(r'([A-Z][a-z]+(?:\s+[A-Z][a-z]+){0,2})\s*$', name)
            if m2:
                possible = m2.group(1)
                if not re.search(r'\b(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\b', possible, re.I) and not re.search(r'\d', possible):
                    name = possible
                else:
                    # fallback: take last word if capitalized and not date
                    parts = name.strip().split()
                    last = parts[-1] if parts else ""
                    if last and not re.search(r'\d', last) and re.match(r'^[A-Z][a-z]+$', last):
                        name = last
                    else:
                        name = ""
            else:
                # fallback: take last word if capitalized and not date
                parts = name.strip().split()
                last = parts[-1] if parts else ""
                if last and not re.search(r'\d', last) and re.match(r'^[A-Z][a-z]+$', last):
                    name = last
                else:
                    name = ""
    else:
        # No parsed addr, try heuristic: split by comma, last part is name+email
        # For "Thu, 3 Sep 2026 at 17:36, Nico Laizans <...>" -> parts after last comma before email is name
        # Use email stripped inner
        tmp = inner
        if email_addr:
            tmp = tmp.replace(f"<{email_addr}>", "").replace(email_addr, "")
        # Now tmp contains date + name separated by comma or " at "
        # Heuristic: find last comma, name is after it, date is before
        if "," in tmp:
            parts = [p.strip() for p in tmp.split(",")]
            # Last part likely name
            candidate_name = parts[-1].strip()
            # Remove date-like words? candidate_name may be "Nico Laizans"
            # If candidate_name looks like date (contains digit and month), not name
            if re.search(r'\d{4}', candidate_name) or re.search(r'\b(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\b', candidate_name, re.I):
                name = ""
                tmp_date = tmp
            else:
                name = candidate_name
                # date is everything before last comma
                tmp_date = ",".join(parts[:-1])
        else:
            tmp_date = tmp
        # Try to infer date from tmp_date
    # Try to extract date string: remove name and email from inner
    date_candidate = inner
    if name:
        # Remove name occurrence
        date_candidate = date_candidate.replace(name, "")
    if email_addr:
        date_candidate = date_candidate.replace(f"<{email_addr}>", "").replace(email_addr, "")
    # Clean up date candidate: remove extra commas, "at"
    date_candidate = date_candidate.strip(" ,")
    # Attempt to parse date
    date_iso = _try_parse_date(date_candidate)
    if not date_iso:
        # Try fuzzy parse of whole inner
        date_iso = _try_parse_date(inner)
    return {"name": name.strip(), "email": email_addr.strip(), "date": date_iso, "raw_date": date_candidate}

def parse_outlook_headers(header_lines: List[str]) -> Dict[str, Any]:
    sender_name = ""
    sender_email = ""
    date_iso = None
    subject = ""
    for line in header_lines:
        if re.match(r'^\s*From\s*:', line, re.I):
            val = re.sub(r'^\s*From\s*:\s*', '', line, flags=re.I).strip()
            addrs = parse_address(val)
            if addrs:
                sender_name = addrs[0]["name"]
                sender_email = addrs[0]["email"]
            else:
                sender_email = _extract_email(val)
        elif re.match(r'^\s*(Sent|Date)\s*:', line, re.I):
            val = re.sub(r'^\s*(Sent|Date)\s*:\s*', '', line, flags=re.I).strip()
            date_iso = _try_parse_date(val)
        elif re.match(r'^\s*To\s*:', line, re.I):
            pass
        elif re.match(r'^\s*Subject\s*:', line, re.I):
            subject = re.sub(r'^\s*Subject\s*:\s*', '', line, flags=re.I).strip()
    return {"name": sender_name, "email": sender_email, "date": date_iso, "subject": subject}

def _build_quoted_dict(metadata: Dict[str, Any], body: str, depth: int, html: str = "") -> Dict[str, Any]:
    mid_raw = f"{metadata.get('email','')}{metadata.get('date','')}{depth}{body[:50]}"
    qid = hashlib.md5(mid_raw.encode()).hexdigest()[:12]
    sender = {"name": metadata.get("name","") or "", "email": metadata.get("email","") or ""}
    ts = metadata.get("date")
    return {
        "id": f"quoted-{qid}",
        "message_id": "",
        "in_reply_to": "",
        "references": "",
        "sender": sender,
        "recipients": {"to": [], "cc": [], "bcc": []},
        "subject": metadata.get("subject",""),
        "timestamp": ts,
        "date": ts,
        "body": {"plain_text": body.strip(), "html": sanitize_html(html) if html else ""},
        "text": body.strip(),
        "html": sanitize_html(html) if html else "",
        "attachments": [],
        "is_current_message": False,
        "is_quoted_message": True,
        "quote_depth": depth,
        "quotedMessages": [],
    }

def _separate_nested_quote_blocks(text: str, depth: int) -> tuple[str, List[Dict]]:
    """Detect nested > blocks at suffix of text and extract as quoted."""
    if not text or depth >= MAX_QUOTE_DEPTH:
        return text, []
    lines = text.splitlines()
    first_idx = None
    for idx, line in enumerate(lines):
        if re.match(r'^\s*>', line):
            first_idx = idx
            break
    if first_idx is None:
        return text, []
    suffix = lines[first_idx:]
    # Heuristic: suffix is quoted if majority quoted or if it starts with > and goes to end
    quoted_count = sum(1 for l in suffix if re.match(r'^\s*>', l) or l.strip() == "")
    # Require at least 50% quoted or suffix length >2 and first line quoted
    if quoted_count < len(suffix) * 0.5:
        return text, []
    current_part = "\n".join(lines[:first_idx]).strip()
    quoted_part = "\n".join(suffix).strip()
    cleaned = _strip_quote_prefix(quoted_part)
    # Recurse for deeper
    deeper_cur, deeper_q = _separate_nested_quote_blocks(cleaned, depth+1)
    q = _build_quoted_dict({"name":"", "email":"", "date":None}, deeper_cur, depth+1)
    if deeper_q:
        q["quotedMessages"] = deeper_q
    return current_part, [q]

def separate_quoted_content(text: str) -> tuple[str, List[Dict]]:
    """
    Separate current message from quoted content.
    Handles Gmail, Outlook, and traditional > blocks, with nesting.
    Returns (current_text, quoted_messages_list)
    """
    if not text:
        return "", []
    # Normalize line endings
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    lines = text.splitlines()
    current_lines = []
    quoted_messages: List[Dict] = []
    current_text_holder = None
    i = 0
    # Helper to finalize current when first header found
    def ensure_current():
        nonlocal current_text_holder
        if current_text_holder is None:
            if current_lines is not None:
                current_text_holder = "\n".join(current_lines).strip()
            else:
                current_text_holder = ""
    # Iterate
    pending_current_lines = current_lines
    # We'll use separate logic: scan for headers
    # Instead of incremental, we will collect header positions first to handle Outlook extended.
    # But incremental loop is simpler for gmail/outlook detection
    i = 0
    current_lines = []
    current_text = None
    quoted_messages = []
    while i < len(lines):
        line = lines[i]
        is_gmail = re.match(r'^\s*On\s.+wrote:\s*$', line, re.I) is not None
        is_outlook = re.match(r'^\s*-{2,}\s*Original Message\s*-{2,}\s*$', line, re.I) is not None
        if is_gmail:
            if len(quoted_messages) >= MAX_QUOTE_DEPTH:
                # Max depth reached: merge remaining into last quoted and stop
                if quoted_messages:
                    remaining = "\n".join(lines[i:])
                    quoted_messages[-1]["text"] += "\n" + remaining
                    quoted_messages[-1]["body"]["plain_text"] = quoted_messages[-1]["text"]
                break
            if current_text is None:
                current_text = "\n".join(current_lines).strip()
                current_lines = None
            metadata = extract_gmail_metadata(line)
            body_lines = []
            i += 1
            while i < len(lines):
                nxt = lines[i]
                if re.match(r'^\s*On\s.+wrote:\s*$', nxt, re.I) or re.match(r'^\s*-{2,}\s*Original Message\s*-{2,}\s*$', nxt, re.I):
                    break
                body_lines.append(nxt)
                i += 1
            body_text = "\n".join(body_lines).strip()
            body_clean = _strip_quote_prefix(body_text) if re.search(r'^\s*>', body_text, re.M) else body_text
            # Check nested > blocks inside body_clean suffix
            # Split body_clean into its own current + nested quoted
            nested_cur, nested_q = _separate_nested_quote_blocks(body_clean, len(quoted_messages))
            # nested_cur is the actual body for this quoted, nested_q are deeper
            q = _build_quoted_dict(metadata, nested_cur, len(quoted_messages))
            if nested_q:
                q["quotedMessages"] = nested_q
                # Also if body_clean had headers nested that were already handled as separate quoted_messages sibling, we would have missed.
                # But our outer loop already handles sequential headers as separate sibling quoted_messages, not nested.
                # For cases where body_clean still contains a gmail header, our _separate_nested_quote_blocks wouldn't capture it, but outer loop would capture it as sibling.
                # To handle, we could check if body_clean contains gmail header and if so, recursively parse it
                # Let's detect and parse recursively for header inside body_clean
                # Use separate_quoted_content recursively on body_clean's nested remainder? Already handling via nested_cur split.
                pass
            quoted_messages.append(q)
            continue
        elif is_outlook:
            if len(quoted_messages) >= MAX_QUOTE_DEPTH:
                if quoted_messages:
                    remaining = "\n".join(lines[i:])
                    quoted_messages[-1]["text"] += "\n" + remaining
                    quoted_messages[-1]["body"]["plain_text"] = quoted_messages[-1]["text"]
                break
            if current_text is None:
                current_text = "\n".join(current_lines).strip()
                current_lines = None
            # Collect outlook header lines
            header_lines = []
            i += 1
            while i < len(lines) and len(header_lines) < 8:
                h = lines[i]
                if re.match(r'^\s*(From|Sent|Date|To|Cc|Subject)\s*:', h, re.I):
                    header_lines.append(h)
                    i += 1
                elif h.strip() == "":
                    i += 1
                    break
                else:
                    break
            metadata = parse_outlook_headers(header_lines)
            body_lines = []
            while i < len(lines):
                nxt = lines[i]
                if re.match(r'^\s*On\s.+wrote:\s*$', nxt, re.I) or re.match(r'^\s*-{2,}\s*Original Message\s*-{2,}\s*$', nxt, re.I):
                    break
                body_lines.append(nxt)
                i += 1
            body_text = "\n".join(body_lines).strip()
            body_clean = _strip_quote_prefix(body_text) if re.search(r'^\s*>', body_text, re.M) else body_text
            nested_cur, nested_q = _separate_nested_quote_blocks(body_clean, len(quoted_messages))
            q = _build_quoted_dict(metadata, nested_cur, len(quoted_messages))
            if nested_q:
                q["quotedMessages"] = nested_q
            quoted_messages.append(q)
            continue
        else:
            if current_lines is not None:
                current_lines.append(line)
            else:
                # We are already in quoted section but encountering non-header line outside expected body collection.
                # This should not happen because body collection consumes lines until next header.
                # If we reach here, it means we have finished all headers and still have lines? Actually after processing a quoted header, we consume its body and continue; we don't collect stray lines.
                # So this branch means lines after last quoted? But quoted section should have been consumed. This would be sibling? We'll just append to last quoted's body if exists
                if quoted_messages:
                    # Append to last quoted's body text (should not happen with our logic)
                    pass
                pass
            i += 1
    # After loop, if no header found, handle > block fallback
    if current_text is None:
        full = "\n".join(current_lines) if current_lines is not None else ""
        # Check for > block
        m = re.search(r'^\s*>', full, re.MULTILINE)
        if m:
            current_text = full[:m.start()].strip()
            quoted_body = full[m.start():].strip()
            cleaned = _strip_quote_prefix(quoted_body)
            # Recursively check for nested inside cleaned
            nested_cur, nested_q = _separate_nested_quote_blocks(cleaned, 0)
            # If nested_q exists, then primary quoted's body is nested_cur and nested is deeper
            q = _build_quoted_dict({"name":"", "email":"", "date":None}, nested_cur if nested_q else cleaned, 0)
            if nested_q:
                # If cleaned had nested, cleaned's current is nested_cur, but we already extracted nested_q from cleaned
                # Actually _separate_nested_quote_blocks(cleaned,0) would treat cleaned's suffix as nested, not the whole cleaned.
                # Need to handle correctly: if cleaned contains nested > block suffix, then cleaned's current is before nested, and quoted is nested.
                # So we should set q body to nested_cur and its quotedMessages to nested_q
                q["body"]["plain_text"] = nested_cur
                q["text"] = nested_cur
                q["quotedMessages"] = nested_q
            quoted_messages = [q]
            # Also need to handle case where cleaned itself still contains multiple levels: already recursion handles one level, but deeper handled via nested_q's own quotedMessages
        else:
            current_text = full.strip()
            quoted_messages = []
    else:
        # current_text already set, quoted_messages may be populated
        if current_text is None:
            current_text = ""
    # For quoted messages that have body containing further gmail headers that weren't captured because they were inside body_clean but not as separate header positions (due to leading > stripping), we may need second pass
    # Expand: for each quoted message, check if its body contains a header pattern, and if so split recursively
    expanded = []
    for q in quoted_messages:
        if q["quote_depth"] >= MAX_QUOTE_DEPTH - 1:
            expanded.append(q)
            continue
        body = q["body"]["plain_text"] or q["text"]
        # If body contains On ... wrote: pattern, split it
        if re.search(r'^\s*On\s.+wrote:\s*$', body, flags=re.MULTILINE|re.I) or re.search(r'^\s*-{2,}\s*Original Message\s*-{2,}', body, flags=re.MULTILINE|re.I):
            # Limit remaining depth budget
            remaining_budget = MAX_QUOTE_DEPTH - q["quote_depth"] - 1
            sub_current, sub_quoted = separate_quoted_content(body)
            # Truncate sub_quoted to remaining budget
            if len(sub_quoted) > remaining_budget:
                # Keep only up to budget, merge rest into last
                sub_quoted = sub_quoted[:remaining_budget]
            # sub_current becomes this quoted's body, sub_quoted become its nested
            q["body"]["plain_text"] = sub_current
            q["text"] = sub_current
            # Merge existing quotedMessages with new sub_quoted (nested deeper)
            existing_nested = q.get("quotedMessages", [])
            # sub_quoted are at depth+1; adjust depth
            for sq in sub_quoted:
                sq["quote_depth"] = q["quote_depth"] + 1 + sq["quote_depth"]
            # Also cap nested depths
            for sq in sub_quoted:
                if sq["quote_depth"] >= MAX_QUOTE_DEPTH:
                    sq["quote_depth"] = MAX_QUOTE_DEPTH - 1
                # Cap its nested recursively if any
                def _cap_depth(qs, base_depth):
                    for qq in qs:
                        if qq["quote_depth"] >= MAX_QUOTE_DEPTH:
                            qq["quote_depth"] = MAX_QUOTE_DEPTH -1
                        if qq.get("quotedMessages"):
                            _cap_depth(qq["quotedMessages"], qq["quote_depth"])
                _cap_depth(sub_quoted, q["quote_depth"])
            q["quotedMessages"] = existing_nested + sub_quoted
        expanded.append(q)
    quoted_messages = expanded
    return current_text or "", quoted_messages

def parse_html_quoted(html: str) -> tuple[str, List[Dict]]:
    """Parse quoted content from HTML. Fallback to text-based detection on stripped text."""
    if not html:
        return "", []
    # Look for common HTML quote containers: blockquote, gmail_quote, outlook
    # Try to split on blockquote
    # Find first blockquote or gmail_quote div
    lower = html.lower()
    # Search for markers
    markers = []
    for pat in [r'<blockquote', r'gmail_quote', r'outlook', r'original message']:
        m = re.search(pat, lower)
        if m:
            markers.append(m.start())
    if markers:
        earliest = min(markers)
        # Find tag start near earliest: go back to <
        tag_start = html.rfind("<", 0, earliest + 20)
        if tag_start != -1:
            current_html = html[:tag_start].strip()
            quoted_html = html[tag_start:].strip()
            # Try to extract text from quoted_html for metadata
            text_content = re.sub(r'<[^>]+>', ' ', quoted_html)
            # Attempt gmail metadata extraction from text_content lines
            lines = [l.strip() for l in text_content.splitlines() if l.strip()]
            metadata = {"name":"", "email":"", "date":None}
            for l in lines[:3]:
                if re.match(r'^\s*On\s.+wrote:\s*$', l, re.I):
                    metadata = extract_gmail_metadata(l)
                    break
            body_text = re.sub(r'<[^>]+>', '\n', quoted_html).strip()
            body_clean = body_text
            q = _build_quoted_dict(metadata, body_clean, 0, html=quoted_html)
            return sanitize_html(current_html), [q]
    # No HTML quote container found, return full html as current
    return html, []

def normalize_subject(subject: str) -> str:
    if not subject:
        return ""
    return re.sub(r'^\s*(re|fwd|fw):\s*', '', subject, flags=re.I).strip().lower()

def deduplicate_quoted_against_thread(thread_messages: List[Dict], quoted_messages: List[Dict]) -> List[Dict]:
    """Remove quoted messages that duplicate real thread messages (by body snippet or sender)."""
    if not thread_messages or not quoted_messages:
        return quoted_messages
    # Build set of thread bodies normalized
    thread_bodies = set()
    thread_senders = set()
    for m in thread_messages:
        txt = (m.get("text") or m.get("body", {}).get("plain_text") or "").strip().lower()
        # Normalize whitespace
        txt_norm = re.sub(r'\s+', ' ', txt)[:200]
        thread_bodies.add(txt_norm)
        sender_email = (m.get("sender", {}).get("email") or "").lower()
        if sender_email:
            thread_senders.add(sender_email)
        # Also add snippet
        snippet = (m.get("snippet") or "")[:200].lower()
        if snippet:
            thread_bodies.add(re.sub(r'\s+', ' ', snippet))
    filtered = []
    for q in quoted_messages:
        body = (q.get("text") or q.get("body", {}).get("plain_text") or "").strip().lower()
        body_norm = re.sub(r'\s+', ' ', body)[:200]
        # If body matches any thread body, skip
        is_duplicate = False
        for tb in thread_bodies:
            if tb and body_norm and (tb in body_norm or body_norm in tb):
                # Require at least 10 chars overlap; for short messages allow exact match
                if len(body_norm) > 10 and len(tb) > 10:
                    is_duplicate = True
                    break
                # For very short but exact equality
                if body_norm == tb:
                    is_duplicate = True
                    break
        # Also check if quoted body is very short and matches snippet? Be less aggressive
        if is_duplicate:
            continue
        # Recursively dedup nested
        nested = q.get("quotedMessages", [])
        if nested:
            q["quotedMessages"] = deduplicate_quoted_against_thread(thread_messages, nested)
        filtered.append(q)
    return filtered

def build_email_message_dict(parsed: Dict[str, Any], quote_depth: int = 0, is_current: bool = True, is_quoted: bool = False) -> Dict[str, Any]:
    """Create normalized EmailMessage structure from parsed dict."""
    # Extract body plain/html
    return {
        "id": parsed.get("uid") or parsed.get("messageId") or f"msg-{hashlib.md5(parsed.get('subject','').encode()).hexdigest()[:8]}",
        "message_id": parsed.get("messageId", ""),
        "in_reply_to": parsed.get("inReplyTo", ""),
        "references": parsed.get("references", ""),
        "sender": parsed.get("sender", {"name":"", "email":""}),
        "recipients": {
            "to": parsed.get("to", []),
            "cc": parsed.get("cc", []),
            "bcc": parsed.get("bcc", []),
        },
        "subject": parsed.get("subject", ""),
        "timestamp": parsed.get("date"),
        "date": parsed.get("date"),
        "body": {
            "plain_text": parsed.get("text", ""),
            "html": parsed.get("html", ""),
        },
        "text": parsed.get("text", ""),
        "html": parsed.get("html", ""),
        "attachments": parsed.get("attachments", []),
        "is_current_message": is_current,
        "is_quoted_message": is_quoted,
        "quote_depth": quote_depth,
        "quotedMessages": parsed.get("quotedMessages", []),
    }

def build_conversation(messages: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Build conversation summary from thread messages."""
    if not messages:
        return {"id": "", "subject": "", "participants": []}
    # Normalize subject
    subj = messages[0].get("subject", "")
    subj_norm = normalize_subject(subj)
    # Participants: unique senders + recipients
    participants = {}
    for m in messages:
        for addr in [m.get("sender")] + (m.get("to") or []) + (m.get("cc") or []):
            if not addr or not isinstance(addr, dict):
                continue
            email_addr = addr.get("email", "").lower()
            if email_addr and email_addr not in participants:
                participants[email_addr] = addr
        # Also from list
        for addr in m.get("from", []) or []:
            email_addr = addr.get("email","").lower()
            if email_addr and email_addr not in participants:
                participants[email_addr] = addr
    # Thread id: use normalized subject or first message id
    thread_id = subj_norm or messages[0].get("messageId") or messages[0].get("uid") or ""
    return {
        "id": thread_id,
        "subject": subj,
        "normalized_subject": subj_norm,
        "participants": list(participants.values()),
        "messageCount": len(messages),
    }


def parse_message(raw_bytes: bytes, uid: str = None, flags=None, mailbox: str = None) -> Dict[str, Any]:
    try:
        msg = email.message_from_bytes(raw_bytes, policy=email.policy.default)
    except Exception:
        msg = email.message_from_bytes(raw_bytes)
    subject = decode_mime_header(msg.get("Subject", ""))
    from_addrs = parse_address(msg.get("From", ""))
    to_addrs = parse_address(msg.get("To", ""))
    cc_addrs = parse_address(msg.get("Cc", ""))
    bcc_addrs = parse_address(msg.get("Bcc", ""))
    reply_to = parse_address(msg.get("Reply-To", ""))
    date_str = msg.get("Date")
    try:
        date_tuple = email.utils.parsedate_to_datetime(date_str) if date_str else None
        date_iso = date_tuple.isoformat() if date_tuple else None
    except Exception:
        date_iso = None
    message_id = msg.get("Message-ID", "")
    in_reply_to = msg.get("In-Reply-To", "")
    references = msg.get("References", "")
    bodies = extract_bodies(msg)
    flag_set = set()
    if flags:
        for f in flags:
            if isinstance(f, bytes):
                f = f.decode()
            flag_set.add(f)
    is_read = b"\\Seen" in flag_set or "\\Seen" in flag_set
    is_flagged = b"\\Flagged" in flag_set or "\\Flagged" in flag_set
    is_answered = b"\\Answered" in flag_set or "\\Answered" in flag_set
    has_attachments = len(bodies["attachments"]) > 0
    # Separate quoted content from text and html
    raw_text = bodies["text"] or ""
    raw_html = bodies["html"] or ""
    # Parse text quoted
    current_text, quoted_from_text = separate_quoted_content(raw_text) if raw_text else ("", [])
    # Parse html quoted if needed and no text quoted? For html we prefer to keep html for current, but also provide quoted html
    current_html = raw_html
    quoted_from_html = []
    if raw_html:
        # If html contains blockquote, parse it; otherwise if text had quoted, we keep html as is but mark quoted html as sanitized version of quoted text?
        if re.search(r'<blockquote|gmail_quote', raw_html, re.I):
            current_html, quoted_from_html = parse_html_quoted(raw_html)
        # If text quoted exists and html not split, keep current_html as sanitized current (we already have)
        # For quoted html, if no html quoted but text quoted exists, create html versions from quoted text plain
        if quoted_from_text and not quoted_from_html:
            # Convert quoted text bodies to html-escaped for display
            import html as html_lib
            for q in quoted_from_text:
                txt = q.get("text","") or q.get("body",{}).get("plain_text","")
                q["html"] = "<pre>" + html_lib.escape(txt) + "</pre>"
                q["body"]["html"] = q["html"]
    # Choose quoted list: prefer html quoted if found, else text quoted
    quoted_messages = quoted_from_html if quoted_from_html else quoted_from_text
    # Enforce max depth already handled
    # Build snippet from current_text
    snippet_source = current_text or re.sub(r"<[^>]+>", " ", current_html or "")
    snippet = snippet_source.strip().replace("\r", " ").replace("\n", " ")[:200]
    sender = from_addrs[0] if from_addrs else {"name": "", "email": ""}
    # Build normalized EmailMessage structure fields as well as legacy
    body_plain = current_text if current_text else raw_text
    # If no split (no quoted), body_plain = raw_text
    if not quoted_messages:
        body_plain = raw_text
        current_text = raw_text
    # Build result with new fields
    result = {
        "uid": uid,
        "mailbox": mailbox,
        "subject": subject or "(no subject)",
        "from": from_addrs,
        "sender": sender,
        "to": to_addrs,
        "cc": cc_addrs,
        "bcc": bcc_addrs,
        "replyTo": reply_to,
        "date": date_iso,
        "messageId": message_id,
        "inReplyTo": in_reply_to,
        "references": references,
        "snippet": snippet,
        "text": body_plain,
        "html": current_html,
        "rawText": raw_text,
        "rawHtml": raw_html,
        "attachments": bodies["attachments"],
        "flags": list(flag_set),
        "read": is_read,
        "starred": is_flagged,
        "answered": is_answered,
        "hasAttachments": has_attachments,
        "size": len(raw_bytes),
        # New fields
        "body": {"plain_text": body_plain, "html": current_html},
        "quotedMessages": quoted_messages,
        "quoteCount": len(quoted_messages),
        "is_current_message": True,
        "is_quoted_message": False,
        "quote_depth": 0,
        "conversation": None,
    }
    # Also create EmailMessage normalized object for compatibility
    # Provide id/message_id etc at top level plus nested
    result["id"] = uid or message_id or ""
    result["message_id"] = message_id
    result["in_reply_to"] = in_reply_to
    result["recipients"] = {"to": to_addrs, "cc": cc_addrs, "bcc": bcc_addrs}
    result["timestamp"] = date_iso
    return result

def build_thread_tree(messages: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    id_map = {}
    for m in messages:
        mid = (m.get("messageId") or m.get("message_id") or "").strip()
        if mid:
            id_map[mid] = m
    for m in messages:
        refs = (m.get("references") or m.get("References") or "") + " " + (m.get("inReplyTo") or m.get("in_reply_to") or "")
        thread_key = None
        for ref in refs.split():
            ref = ref.strip()
            if ref in id_map:
                ancestor = id_map[ref]
                thread_key = ancestor.get("threadId") or ancestor.get("messageId") or ancestor.get("message_id") or ancestor.get("subject")
                break
        if not thread_key:
            subj = m.get("subject", "")
            subj_norm = re.sub(r"^(re:|fwd:|fw:)\s*", "", subj, flags=re.I).strip().lower()
            thread_key = subj_norm or m.get("messageId") or m.get("message_id") or m.get("uid") or m.get("id")
        m["threadId"] = thread_key
    grouped: Dict[str, List[Dict]] = {}
    for m in messages:
        grouped.setdefault(m["threadId"], []).append(m)
    result = []
    for tid, msgs in grouped.items():
        msgs_sorted = sorted(msgs, key=lambda x: x.get("date") or x.get("timestamp") or "")
        result.append({
            "threadId": tid,
            "subject": msgs_sorted[0].get("subject"),
            "messages": msgs_sorted,
            "count": len(msgs_sorted),
            "unreadCount": sum(1 for x in msgs_sorted if not x.get("read")),
            "hasAttachments": any(x.get("hasAttachments") for x in msgs_sorted),
            "lastDate": msgs_sorted[-1].get("date") or msgs_sorted[-1].get("timestamp"),
        })
    result.sort(key=lambda x: x.get("lastDate") or "", reverse=True)
    return result
