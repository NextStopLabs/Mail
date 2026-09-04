import imaplib
import re
import logging
import email.utils
from typing import List, Dict, Any, Optional, Tuple
from apps.mail.services.parser import parse_message
from django.core.cache import cache

logger = logging.getLogger("mail")

# Helper to encode folder names for IMAP (utf7)
def encode_folder(name: str) -> str:
    return name

def decode_folder(raw) -> str:
    if isinstance(raw, bytes):
        return raw.decode()
    return raw

# Folder type detection
FOLDER_ROLE_MAP = {
    "inbox": ["inbox"],
    "sent": ["sent", "sent items", "sent messages"],
    "drafts": ["drafts", "draft"],
    "trash": ["trash", "deleted", "bin"],
    "spam": ["spam", "junk", "junk email"],
    "archive": ["archive", "all mail"],
    "starred": ["starred", "flagged"],
}

def detect_role(folder_name: str, attributes: List[bytes]) -> str:
    lname = folder_name.lower()
    # Check IMAP attributes like \Sent \Drafts \Trash \Junk \Archive
    attr_str = " ".join([a.decode() if isinstance(a, bytes) else str(a) for a in attributes]).lower()
    if "\\sent" in attr_str:
        return "sent"
    if "\\drafts" in attr_str:
        return "drafts"
    if "\\trash" in attr_str:
        return "trash"
    if "\\junk" in attr_str or "\\spam" in attr_str:
        return "spam"
    if "\\archive" in attr_str:
        return "archive"
    for role, keywords in FOLDER_ROLE_MAP.items():
        for kw in keywords:
            if kw == lname or kw in lname.split("/")[-1]:
                return role
    return "custom"

class MailService:
    """
    Clean abstraction over IMAP. No IMAP calls outside this service.
    Per-request instance, isolated per authenticated mailbox.
    """
    def __init__(self, conn: imaplib.IMAP4):
        self.conn = conn

    # --- Mailboxes ---
    def list_mailboxes(self) -> List[Dict[str, Any]]:
        typ, data = self.conn.list()
        if typ != "OK":
            raise Exception("Failed to list mailboxes")
        mailboxes = []
        for line in data:
            if not line:
                continue
            # line example: b'(\\HasNoChildren) "/" "INBOX"'
            try:
                # Use regex to parse
                m = re.match(rb'\((.*?)\)\s+"([^"]+)"\s+"?([^"]+)"?', line)
                if not m:
                    # fallback: split
                    decoded = line.decode(errors="replace")
                    # attempt to extract name after last quote
                    parts = decoded.rsplit('"', 2)
                    name = parts[-2] if len(parts) >= 2 else decoded.split()[-1].strip('"')
                    attrs = []
                    delim = "/"
                else:
                    attrs_raw, delim, name = m.groups()
                    attrs = attrs_raw.split()
                    name = name.decode() if isinstance(name, bytes) else name
                    delim = delim.decode() if isinstance(delim, bytes) else delim
                # skip empty?
                role = detect_role(name, attrs if isinstance(attrs, list) else [])
                # Get status for unread counts
                mailboxes.append({
                    "id": name,
                    "name": name.split("/")[-1] if "/" in name else name.split(".")[-1] if "." in name else name,
                    "fullName": name,
                    "delimiter": delim,
                    "attributes": [a.decode() if isinstance(a, bytes) else str(a) for a in attrs] if isinstance(attrs, list) else [],
                    "role": role,
                })
            except Exception as e:
                logger.warning("Failed to parse mailbox line %s: %s", line, e)
                continue

        # Enrich with counts (UNSEEN and MESSAGES) - do it efficiently but not for every folder if many
        for mb in mailboxes:
            try:
                # Use STATUS to avoid selecting
                typ, status_data = self.conn.status(f'"{mb["fullName"]}"', "(MESSAGES UNSEEN RECENT UIDNEXT UIDVALIDITY)")
                if typ == "OK" and status_data and status_data[0]:
                    s = status_data[0].decode() if isinstance(status_data[0], bytes) else str(status_data[0])
                    # parse numbers
                    m_msg = re.search(r"MESSAGES\s+(\d+)", s)
                    m_unseen = re.search(r"UNSEEN\s+(\d+)", s)
                    mb["total"] = int(m_msg.group(1)) if m_msg else 0
                    mb["unseen"] = int(m_unseen.group(1)) if m_unseen else 0
                else:
                    mb["total"] = 0
                    mb["unseen"] = 0
            except Exception:
                mb["total"] = 0
                mb["unseen"] = 0

        # Sort: inbox first, then sent/drafts etc, then custom
        order = {"inbox": 0, "sent": 1, "drafts": 2, "archive": 3, "spam": 4, "trash": 5, "custom": 6}
        mailboxes.sort(key=lambda x: (order.get(x["role"], 99), x["fullName"].lower()))
        return mailboxes

    def _select_mailbox(self, mailbox: str, readonly: bool = False):
        # Quote mailbox name if needed
        mbox = f'"{mailbox}"' if " " in mailbox or "/" in mailbox else mailbox
        typ, data = self.conn.select(mbox, readonly=readonly)
        if typ != "OK":
            # try with quotes
            typ, data = self.conn.select(f'"{mailbox}"', readonly=readonly)
            if typ != "OK":
                raise Exception(f"Cannot select mailbox {mailbox}: {data}")
        return data

    # --- Messages ---
    def list_messages(
        self,
        mailbox: str,
        page: int = 1,
        page_size: int = 50,
        search: str = None,
        filter_by: str = None,  # unread, flagged, etc
    ) -> Dict[str, Any]:
        self._select_mailbox(mailbox, readonly=True)
        # Build search criteria
        criteria = []
        if search:
            # Use IMAP SEARCH with OR for subject/from/body
            # Escape quotes
            safe = search.replace('"', ' ')
            # We'll use: (OR OR SUBJECT "x" FROM "x" TEXT "x") but IMAP TEXT searches body
            # For simplicity use: TEXT "search" which searches all
            criteria.append(f'TEXT "{safe}"')
        if filter_by == "unread":
            criteria.append("UNSEEN")
        elif filter_by == "flagged":
            criteria.append("FLAGGED")
        elif filter_by == "read":
            criteria.append("SEEN")

        # Use UID SEARCH
        search_cmd = " ".join(criteria) if criteria else "ALL"
        try:
            typ, data = self.conn.uid("SEARCH", None, search_cmd)
        except Exception:
            typ, data = self.conn.uid("SEARCH", None, "ALL")

        if typ != "OK" or not data or not data[0]:
            return {"messages": [], "total": 0, "page": page, "pageSize": page_size, "mailbox": mailbox}

        uids = data[0].split()
        total = len(uids)
        # Sort descending (newest first) - SEARCH returns ascending, so reverse
        uids = uids[::-1]

        # Pagination
        start = (page - 1) * page_size
        end = start + page_size
        page_uids = uids[start:end]
        if not page_uids:
            return {"messages": [], "total": total, "page": page, "pageSize": page_size, "mailbox": mailbox}

        # Fetch headers + flags for page
        # Use UID FETCH with (UID FLAGS BODY.PEEK[HEADER.FIELDS (FROM TO SUBJECT DATE MESSAGE-ID IN-REPLY-TO REFERENCES)] BODY.PEEK[TEXT] maybe)
        # For list view we fetch ENVELOPE and FLAGS and partial body for snippet
        # Efficient: FETCH (UID FLAGS ENVELOPE BODY.PEEK[HEADER.FIELDS...] BODY.PEEK[TEXT] ...)
        # We'll fetch ENVELOPE and FLAGS and RFC822.SIZE and BODYSTRUCTURE quickly, then parse.
        # Simpler: FETCH (UID FLAGS ENVELOPE RFC822.HEADER RFC822.SIZE)
        # Then for snippet we need preview: we can fetch BODY.PEEK[TEXT] limited? Instead fetch full for preview truncated.

        # Batch fetch
        uid_str = ",".join([u.decode() if isinstance(u, bytes) else str(u) for u in page_uids])
        typ, fetch_data = self.conn.uid("FETCH", uid_str, "(UID FLAGS ENVELOPE BODY.PEEK[HEADER.FIELDS (FROM TO SUBJECT DATE MESSAGE-ID IN-REPLY-TO REFERENCES)] RFC822.SIZE INTERNALDATE BODYSTRUCTURE)")
        messages = []
        if typ == "OK" and fetch_data:
            # fetch_data is list of tuples
            # We need to parse ourselves by iterating
            # imaplib returns interleaved data; easier to do separate FETCH for RFC822.HEADER? Let's do simpler: FETCH RFC822.HEADER for each?
            # For robustness, parse the fetch_data manually: each item may be (msg_id, data)
            # Instead we fallback to fetching individual messages' headers via UID FETCH per uid if parsing fails
            try:
                messages = self._parse_list_fetch(fetch_data, page_uids)
            except Exception as e:
                logger.warning("parse list fetch failed: %s", e)
                messages = []

        # If parsing yielded nothing, try per-message fetch of full? (slower)
        if not messages:
            messages = self._fallback_list_fetch(page_uids, mailbox)

        # Fetch snippets via additional FETCH for body preview (optional, we already have envelope)
        # Enrich with preview from BODY.PEEK[TEXT] truncated first 500 chars if not already
        return {"messages": messages, "total": total, "page": page, "pageSize": page_size, "mailbox": mailbox}

    def _parse_list_fetch(self, fetch_data, expected_uids):
        messages = []
        # fetch_data contains tuples and strings; we need to collate per message
        # imaplib's FETCH response is tricky; we can iterate and extract UID, FLAGS, ENVELOPE
        # For simplicity, we fetch raw headers using regex on fetch_data bytes
        # This is best-effort; fallback exists.
        i = 0
        raw_map = {}  # uid -> header_bytes + flags
        current_uid = None
        current_flags = []
        while i < len(fetch_data):
            item = fetch_data[i]
            if item is None:
                i += 1
                continue
            if isinstance(item, tuple) and len(item) == 2:
                header_part, body_part = item
                # header_part contains "1 (UID 123 FLAGS (\Seen) ENVELOPE (...) ..."
                if isinstance(header_part, bytes):
                    hp = header_part.decode(errors="replace")
                else:
                    hp = str(header_part)
                # extract UID
                m_uid = re.search(r"UID\s+(\d+)", hp)
                uid = m_uid.group(1) if m_uid else None
                # flags
                m_flags = re.search(r"FLAGS\s+\((.*?)\)", hp)
                flags = m_flags.group(1).split() if m_flags and m_flags.group(1) else []
                raw_map[uid] = {"flags": flags, "header_bytes": body_part if isinstance(body_part, bytes) else b"", "raw": hp}
                current_uid = uid
            elif isinstance(item, bytes):
                # This is the closing parenthesis or header data continuation
                # Sometimes body_part is separate
                if current_uid and item.strip() not in (b")", b""):
                    # Append to header_bytes
                    if current_uid in raw_map:
                        existing = raw_map[current_uid].get("header_bytes", b"")
                        if isinstance(item, bytes):
                            raw_map[current_uid]["header_bytes"] = existing + item
            i += 1

        for uid, info in raw_map.items():
            try:
                header_bytes = info["header_bytes"]
                if not header_bytes:
                    continue
                # Need full message for parse_message? We have only header, so construct minimal
                # Use parse_message with header_bytes + empty body
                # To get snippet we need body preview; we'll fetch later if needed
                # For now parse header only
                msg = email.message_from_bytes(header_bytes) if header_bytes else None
                if msg is None:
                    continue
                # Build minimal parsed object from envelope data
                # Instead of full parse, construct dict manually from headers
                subject = ""
                for k, v in msg.items():
                    if k.lower() == "subject":
                        from apps.mail.services.parser import decode_mime_header
                        subject = decode_mime_header(v)
                from_hdr = msg.get("From", "")
                to_hdr = msg.get("To", "")
                date_hdr = msg.get("Date", "")
                # snippet will be fetched separately; leave empty for now
                # Use flags
                flags = info["flags"]
                is_read = "\\Seen" in flags
                is_flagged = "\\Flagged" in flags
                from apps.mail.services.parser import parse_address
                sender = parse_address(from_hdr)[0] if parse_address(from_hdr) else {"name": "", "email": from_hdr}
                try:
                    date_iso = email.utils.parsedate_to_datetime(date_hdr).isoformat() if date_hdr else None
                except Exception:
                    date_iso = None
                messages.append({
                    "uid": uid,
                    "subject": subject or "(no subject)",
                    "from": parse_address(from_hdr),
                    "sender": sender,
                    "to": parse_address(to_hdr),
                    "date": date_iso,
                    "messageId": msg.get("Message-ID", ""),
                    "snippet": "",
                    "flags": flags,
                    "read": is_read,
                    "starred": is_flagged,
                    "hasAttachments": False,  # unknown without BODYSTRUCTURE parse
                    "size": 0,
                })
            except Exception:
                continue
        # Now enrich snippet and hasAttachments via BODYSTRUCTURE if available? We'll do second fetch for full preview truncated
        # Fetch BODY.PEEK[TEXT] for each uid limited
        if messages and raw_map:
            # Try to get BODY preview via separate fetch for snippet/hasAttachments
            try:
                uids = list(raw_map.keys())
                uid_str = ",".join(uids)
                typ, data = self.conn.uid("FETCH", uid_str, "(UID BODY.PEEK[TEXT]<0.500> FLAGS BODYSTRUCTURE)")
                # Parse hasAttachments from BODYSTRUCTURE presence of "attachment"
                # Simple: if response contains "attachment" string, mark true
                if typ == "OK" and data:
                    for item in data:
                        if isinstance(item, tuple) and len(item) == 2:
                            hdr, body = item
                            hdr_s = hdr.decode(errors="replace") if isinstance(hdr, bytes) else str(hdr)
                            m_uid = re.search(r"UID\s+(\d+)", hdr_s)
                            uid = m_uid.group(1) if m_uid else None
                            if not uid:
                                continue
                            # find message dict
                            for m in messages:
                                if m["uid"] == uid:
                                    if body and isinstance(body, bytes):
                                        snippet = body.decode(errors="replace").strip().replace("\r", " ").replace("\n", " ")[:200]
                                        # If snippet is html, strip tags roughly
                                        snippet = re.sub(r"<[^>]+>", " ", snippet)
                                        m["snippet"] = snippet
                                    # check attachment in hdr
                                    if "attachment" in hdr_s.lower() or '\"attachment\"' in hdr_s.lower():
                                        m["hasAttachments"] = True
                                    break
            except Exception as e:
                logger.debug("snippet enrichment failed: %s", e)

        # Sort by date desc? Already in reverse uid order, but keep uid order
        uid_order = {u.decode() if isinstance(u, bytes) else str(u): idx for idx, u in enumerate(expected_uids)}
        messages.sort(key=lambda x: uid_order.get(str(x["uid"]), 999))
        return messages

    def _fallback_list_fetch(self, uids, mailbox):
        messages = []
        for uid in uids:
            uid_s = uid.decode() if isinstance(uid, bytes) else str(uid)
            try:
                typ, data = self.conn.uid("FETCH", uid_s, "(UID FLAGS RFC822.HEADER RFC822.SIZE)")
                if typ != "OK" or not data or not data[0]:
                    continue
                # data[0] is tuple
                raw_header = b""
                flags = []
                for item in data:
                    if isinstance(item, tuple) and len(item) == 2:
                        hdr_part, body_part = item
                        hdr_s = hdr_part.decode(errors="replace") if isinstance(hdr_part, bytes) else str(hdr_part)
                        m_flags = re.search(r"FLAGS\s+\((.*?)\)", hdr_s)
                        if m_flags:
                            flags = m_flags.group(1).split()
                        if isinstance(body_part, bytes):
                            raw_header = body_part
                # Also fetch snippet body
                typ2, data2 = self.conn.uid("FETCH", uid_s, "BODY.PEEK[TEXT]<0.800>")
                snippet = ""
                if typ2 == "OK" and data2 and data2[0]:
                    if isinstance(data2[0], tuple):
                        snippet_raw = data2[0][1]
                        if isinstance(snippet_raw, bytes):
                            snippet = snippet_raw.decode(errors="replace").strip().replace("\r", " ").replace("\n", " ")[:200]
                            snippet = re.sub(r"<[^>]+>", " ", snippet)
                    elif isinstance(data2[0], bytes):
                        snippet = data2[0].decode(errors="replace")[:200]
                # Parse header
                from apps.mail.services.parser import parse_address, decode_mime_header
                msg = email.message_from_bytes(raw_header) if raw_header else None
                if msg is None:
                    continue
                subject = decode_mime_header(msg.get("Subject", ""))
                from_hdr = msg.get("From", "")
                to_hdr = msg.get("To", "")
                date_hdr = msg.get("Date", "")
                try:
                    date_iso = email.utils.parsedate_to_datetime(date_hdr).isoformat() if date_hdr else None
                except Exception:
                    date_iso = None
                sender = parse_address(from_hdr)[0] if parse_address(from_hdr) else {"name": "", "email": from_hdr}
                messages.append({
                    "uid": uid_s,
                    "subject": subject or "(no subject)",
                    "from": parse_address(from_hdr),
                    "sender": sender,
                    "to": parse_address(to_hdr),
                    "date": date_iso,
                    "messageId": msg.get("Message-ID", ""),
                    "snippet": snippet,
                    "flags": flags,
                    "read": "\\Seen" in flags,
                    "starred": "\\Flagged" in flags,
                    "hasAttachments": False,
                    "size": 0,
                })
            except Exception as e:
                logger.warning("fallback fetch failed for uid %s: %s", uid_s, e)
                continue
        return messages

    def get_message(self, mailbox: str, uid: str) -> Dict[str, Any]:
        self._select_mailbox(mailbox, readonly=True)
        typ, data = self.conn.uid("FETCH", str(uid), "(UID FLAGS RFC822)")
        if typ != "OK" or not data or data[0] is None:
            raise Exception("Message not found")
        raw = None
        flags = []
        for item in data:
            if isinstance(item, tuple) and len(item) == 2:
                hdr, body = item
                hdr_s = hdr.decode(errors="replace") if isinstance(hdr, bytes) else str(hdr)
                m_flags = re.search(r"FLAGS\s+\((.*?)\)", hdr_s)
                if m_flags:
                    flags = m_flags.group(1).split()
                if isinstance(body, bytes):
                    raw = body
                elif isinstance(body, str):
                    raw = body.encode()
            elif isinstance(item, bytes) and len(item) > 100:
                raw = item
        if raw is None:
            # try alternative
            for item in data:
                if isinstance(item, bytes) and b"Subject" in item:
                    raw = item
                    break
        if raw is None:
            raise Exception("Failed to retrieve message")
        parsed = parse_message(raw, uid=str(uid), flags=flags, mailbox=mailbox)
        return parsed

    def get_thread(self, mailbox: str, uid: str, limit: int = 100) -> Dict[str, Any]:
        """
        Build conversation thread for given uid using Message-ID threading + subject fallback.
        Returns {conversation, messages, currentMessage}
        """
        from apps.mail.services.parser import build_conversation, build_thread_tree, deduplicate_quoted_against_thread, normalize_subject
        # First get target message
        target = self.get_message(mailbox, uid)
        # Gather candidate UIDs across relevant mailboxes (current + Sent + INBOX) to show replies
        try:
            # Build list of mailboxes to search for thread members
            candidate_mailboxes = [mailbox]
            try:
                all_boxes = self.list_mailboxes()
                # Add Sent and INBOX if not already
                for mb in all_boxes:
                    role = mb.get("role")
                    name = mb.get("fullName")
                    if role in ("sent", "inbox") and name not in candidate_mailboxes:
                        candidate_mailboxes.append(name)
                    # Also add archive maybe?
                # Keep order, limit to 3 to avoid too many IMAP selects
                candidate_mailboxes = candidate_mailboxes[:4]
            except Exception:
                pass

            messages_for_thread = []
            import email as email_lib
            from apps.mail.services.parser import decode_mime_header, parse_address
            # Collect UIDs from each candidate mailbox using bulk FETCH (1 round-trip per mailbox instead of N)
            for cand_mb in candidate_mailboxes:
                try:
                    self._select_mailbox(cand_mb, readonly=True)
                    typ, data = self.conn.uid("SEARCH", None, "ALL")
                    if typ != "OK" or not data or not data[0]:
                        continue
                    all_uids = data[0].split()
                    recent_uids = all_uids[-limit:] if len(all_uids) > limit else all_uids
                    if not recent_uids:
                        continue
                    # Bulk fetch headers for all recent UIDs at once
                    uid_str = b",".join(recent_uids).decode() if isinstance(recent_uids[0], bytes) else ",".join(recent_uids)
                    typ2, d2 = self.conn.uid("FETCH", uid_str, "(UID FLAGS RFC822.HEADER)")
                    if typ2 != "OK" or not d2:
                        continue
                    # d2 contains alternating tuples (header meta, body) + terminating bytes. Parse bulk.
                    for item in d2:
                        if not isinstance(item, tuple) or len(item) != 2:
                            continue
                        hdr_part, body_part = item
                        hdr_s = hdr_part.decode(errors="replace") if isinstance(hdr_part, bytes) else str(hdr_part)
                        m_uid = re.search(r"UID\s+(\d+)", hdr_s)
                        if not m_uid:
                            continue
                        u_s = m_uid.group(1)
                        m_flags = re.search(r"FLAGS\s+\((.*?)\)", hdr_s)
                        flags = m_flags.group(1).split() if m_flags and m_flags.group(1) else []
                        raw_header = body_part if isinstance(body_part, bytes) else b""
                        if not raw_header:
                            continue
                        try:
                            msg = email_lib.message_from_bytes(raw_header)
                            subject = decode_mime_header(msg.get("Subject",""))
                            date_hdr = msg.get("Date","")
                            try:
                                date_iso = email_lib.utils.parsedate_to_datetime(date_hdr).isoformat() if date_hdr else None
                            except Exception:
                                date_iso = None
                            messages_for_thread.append({
                                "uid": u_s,
                                "mailbox": cand_mb,
                                "messageId": msg.get("Message-ID",""),
                                "inReplyTo": msg.get("In-Reply-To",""),
                                "references": msg.get("References",""),
                                "subject": subject,
                                "date": date_iso,
                                "from": parse_address(msg.get("From","")),
                                "to": parse_address(msg.get("To","")),
                                "sender": parse_address(msg.get("From",""))[0] if parse_address(msg.get("From","")) else {"name":"","email":""},
                                "flags": flags,
                                "read": "\\Seen" in flags,
                                "snippet": "",
                                "hasAttachments": False,
                            })
                        except Exception:
                            continue
                except Exception:
                    continue
            if not messages_for_thread:
                conversation = build_conversation([target])
                return {
                    "conversation": conversation,
                    "messages": [target],
                    "currentMessage": target,
                    "threadId": conversation.get("id"),
                }
            # Build thread tree to find thread containing target
            # Include target in list if not already (it should be in recent_uids if within limit)
            # Ensure target is included
            if not any(m.get("uid")==target.get("uid") for m in messages_for_thread):
                messages_for_thread.append({
                    "uid": target.get("uid"),
                    "messageId": target.get("messageId",""),
                    "inReplyTo": target.get("inReplyTo",""),
                    "references": target.get("references",""),
                    "subject": target.get("subject",""),
                    "date": target.get("date"),
                    "from": target.get("from",[]),
                    "to": target.get("to",[]),
                    "sender": target.get("sender"),
                    "flags": target.get("flags",[]),
                    "read": target.get("read"),
                    "snippet": target.get("snippet",""),
                    "hasAttachments": target.get("hasAttachments",False),
                })
            # Build threads
            threads = build_thread_tree(messages_for_thread)
            # Find thread that contains target uid
            target_thread = None
            for t in threads:
                if any(m.get("uid")==target.get("uid") for m in t["messages"]):
                    target_thread = t
                    break
            if not target_thread:
                # Fallback: use normalized subject thread
                subj_norm = normalize_subject(target.get("subject",""))
                target_thread = next((t for t in threads if t["threadId"]==subj_norm), None)
            if not target_thread:
                conversation = build_conversation([target])
                return {"conversation": conversation, "messages": [target], "currentMessage": target, "threadId": conversation.get("id")}
            # Bulk fetch full messages per mailbox (1 round-trip per mailbox, not per message)
            from collections import defaultdict
            from apps.mail.services.parser import parse_message
            full_messages = []
            # Group thread messages by mailbox
            grouped = defaultdict(list)
            for mm in sorted(target_thread["messages"], key=lambda x: x.get("date") or ""):
                grouped[mm.get("mailbox") or mailbox].append(mm)
            # Map to hold parsed results uid->parsed
            parsed_by_uid: Dict[str, Any] = {target.get("uid"): target} if target.get("uid") else {}
            for g_mb, g_msgs in grouped.items():
                # Separate target already parsed, fetch rest bulk
                need = [m for m in g_msgs if not (m.get("uid")==target.get("uid") and g_mb==mailbox)]
                if not need:
                    continue
                uid_str = ",".join(m.get("uid") for m in need)
                try:
                    self._select_mailbox(g_mb, readonly=True)
                    typ, data = self.conn.uid("FETCH", uid_str, "(UID FLAGS RFC822)")
                    if typ != "OK" or not data:
                        for m in need:
                            full_messages.append(m)
                        continue
                    # Build uid -> raw + flags map from bulk response
                    bulk_map: Dict[str, Any] = {}
                    for item in data:
                        if not isinstance(item, tuple) or len(item)!=2:
                            continue
                        hdr_part, body_part = item
                        hdr_s = hdr_part.decode(errors="replace") if isinstance(hdr_part, bytes) else str(hdr_part)
                        m_uid = re.search(r"UID\s+(\d+)", hdr_s)
                        if not m_uid:
                            continue
                        uid = m_uid.group(1)
                        m_flags = re.search(r"FLAGS\s+\((.*?)\)", hdr_s)
                        flags = m_flags.group(1).split() if m_flags and m_flags.group(1) else []
                        raw = body_part if isinstance(body_part, bytes) else b""
                        if raw:
                            try:
                                parsed = parse_message(raw, uid=uid, flags=flags, mailbox=g_mb)
                                bulk_map[uid] = parsed
                            except Exception:
                                pass
                    for m in need:
                        if m.get("uid") in bulk_map:
                            parsed_by_uid[m.get("uid")] = bulk_map[m.get("uid")]
                        else:
                            parsed_by_uid[m.get("uid")] = m
                except Exception:
                    for m in need:
                        parsed_by_uid[m.get("uid")] = m
            # Reassemble in chronological order including target
            for mm in sorted(target_thread["messages"], key=lambda x: x.get("date") or ""):
                uid = mm.get("uid")
                if uid in parsed_by_uid:
                    full_messages.append(parsed_by_uid[uid])
                elif uid == target.get("uid"):
                    full_messages.append(target)
                else:
                    full_messages.append(mm)
            # Deduplicate by uid preserve order
            seen=set()
            deduped_full=[]
            for fm in full_messages:
                uid=fm.get("uid")
                if uid not in seen:
                    seen.add(uid)
                    deduped_full.append(fm)
            full_messages=deduped_full
            # Deduplicate quoted messages in currentMessage against thread
            try:
                # target quoted vs other messages
                thread_bodies_for_dedup = [fm for fm in full_messages if fm.get("uid") != target.get("uid")]
                deduped = deduplicate_quoted_against_thread(thread_bodies_for_dedup, target.get("quotedMessages", []))
                target["quotedMessages"] = deduped
                target["quoteCount"] = len(deduped)
            except Exception:
                pass
            # Sort chronologically oldest -> newest
            full_messages_sorted = sorted(full_messages, key=lambda x: x.get("date") or "")
            conversation = build_conversation(full_messages_sorted)
            conversation["threadId"] = target_thread["threadId"]
            return {
                "conversation": conversation,
                "messages": full_messages_sorted,
                "currentMessage": target,
                "threadId": target_thread["threadId"],
            }
        except Exception as e:
            import logging
            logging.getLogger("mail").debug("get_thread failed: %s", e)
            from apps.mail.services.parser import build_conversation
            conversation = build_conversation([target])
            return {"conversation": conversation, "messages": [target], "currentMessage": target, "threadId": conversation.get("id")}

    def get_attachment(self, mailbox: str, uid: str, part_index: str = None, filename: str = None):
        """
        Stream attachment. Returns (bytes, filename, mime)
        part_index is the IMAP BODY part number, if known. Alternative: find by filename.
        We'll fetch BODYSTRUCTURE then determine part.
        """
        self._select_mailbox(mailbox, readonly=True)
        # Get structure
        typ, data = self.conn.uid("FETCH", str(uid), "(BODYSTRUCTURE)")
        if typ != "OK":
            raise Exception("Failed to fetch structure")

        # Simplify: iterate over possible part numbers and try to find attachment
        # Common: fetch RFC822 and parse via email library to extract part by filename
        typ2, data2 = self.conn.uid("FETCH", str(uid), "(RFC822)")
        if typ2 != "OK" or not data2 or data2[0] is None:
            raise Exception("Message not found")
        raw = None
        for item in data2:
            if isinstance(item, tuple) and len(item) == 2:
                if isinstance(item[1], bytes):
                    raw = item[1]
                    break
        if raw is None:
            raise Exception("Failed to fetch message")

        import email
        from email.header import decode_header

        msg = email.message_from_bytes(raw)
        # Walk to find attachment
        target_part = None
        target_payload = None
        target_mime = None
        target_filename = None

        # If part_index provided, try to fetch via BODY.PEEK[part_index]
        if part_index:
            try:
                typ3, data3 = self.conn.uid("FETCH", str(uid), f"(BODY.PEEK[{part_index}])")
                if typ3 == "OK" and data3 and data3[0]:
                    if isinstance(data3[0], tuple):
                        payload = data3[0][1]
                        # Also fetch header for this part to get filename/mime
                        # For simplicity walk msg to find part with same index? Instead guess
                    else:
                        payload = data3[0]
                    # Find corresponding part in msg walk by index
                    # IMAP part numbers are 1-indexed; walk order
                    parts = list(msg.walk())
                    # part_index like "2" or "1.2"
                    # We'll try to map: if simple integer, use that index in walk skipping multipart containers? Simpler: use filename fallback
                    pass
            except Exception:
                pass

        # Walk and match by filename or mime
        for part in msg.walk():
            if part.is_multipart():
                continue
            fname = part.get_filename()
            if fname:
                try:
                    fname_decoded = "".join(
                        t.decode(c or "utf-8", errors="replace") if isinstance(t, bytes) else t
                        for t, c in decode_header(fname)
                    )
                except Exception:
                    fname_decoded = fname
            else:
                fname_decoded = None
            ctype = part.get_content_type()
            disp = (part.get_content_disposition() or "").lower()

            # If filename matches requested, or if no filename filter and this looks like attachment
            if filename and fname_decoded == filename:
                target_part = part
                break
            if not filename and not part_index:
                # if part is attachment (disposition attachment or has filename)
                if disp == "attachment" or fname_decoded:
                    # if only one attachment, return first; but we need to identify which one requested via query param attachment_id?
                    # We'll return first if filename not specified and only called with one attachment - handled by caller passing filename
                    pass

        # Better: if filename provided, search, else use part_index logic via walking with counter
        # If still not found, try to use the nth attachment as attachment_id index
        if target_part is None and filename:
            # Search again with more lenient
            for part in msg.walk():
                if part.is_multipart():
                    continue
                fname = part.get_filename()
                if fname:
                    try:
                        fname_decoded = "".join(
                            t.decode(c or "utf-8", errors="replace") if isinstance(t, bytes) else t
                            for t, c in decode_header(fname)
                        )
                    except Exception:
                        fname_decoded = fname
                    if fname_decoded == filename or (filename in (fname_decoded or "")):
                        target_part = part
                        break
        if target_part is None and part_index is not None:
            # treat part_index as attachment index (0-based)
            try:
                idx = int(part_index)
                attachments = [p for p in msg.walk() if not p.is_multipart() and (p.get_content_disposition() == "attachment" or p.get_filename())]
                if 0 <= idx < len(attachments):
                    target_part = attachments[idx]
            except Exception:
                pass

        # Fallback: first attachment
        if target_part is None:
            # Find first attachment
            for part in msg.walk():
                if part.is_multipart():
                    continue
                if part.get_content_disposition() == "attachment" or part.get_filename():
                    target_part = part
                    break
        if target_part is None:
            raise Exception("Attachment not found")

        payload = target_part.get_payload(decode=True) or b""
        fname = target_part.get_filename() or filename or "attachment"
        try:
            fname = "".join(
                t.decode(c or "utf-8", errors="replace") if isinstance(t, bytes) else t
                for t, c in decode_header(fname)
            )
        except Exception:
            pass
        # Sanitize filename: remove path, control chars
        import os
        fname = os.path.basename(fname).replace("\n", "").replace("\r", "").strip() or "attachment"
        # Limit length
        if len(fname) > 200:
            fname = fname[:200]
        ctype = target_part.get_content_type() or "application/octet-stream"

        return payload, fname, ctype

    # --- Flags ---
    def set_flag(self, mailbox: str, uid: str, flag: str, value: bool):
        self._select_mailbox(mailbox)
        op = "+FLAGS" if value else "-FLAGS"
        typ, data = self.conn.uid("STORE", str(uid), op, f"({flag})")
        if typ != "OK":
            raise Exception(f"Failed to set flag {flag}")

    def mark_read(self, mailbox: str, uid: str, read: bool):
        self.set_flag(mailbox, uid, "\\Seen", read)

    def star(self, mailbox: str, uid: str, starred: bool):
        self.set_flag(mailbox, uid, "\\Flagged", starred)

    # --- Move / Copy / Delete ---
    def move_message(self, source_mailbox: str, uid: str, dest_mailbox: str):
        self._select_mailbox(source_mailbox)
        # Try UID MOVE if supported (RFC 6851)
        try:
            typ, data = self.conn.uid("MOVE", str(uid), f'"{dest_mailbox}"')
            if typ == "OK":
                return
        except Exception:
            pass
        # Fallback: COPY + STORE \Deleted + EXPUNGE
        typ, data = self.conn.uid("COPY", str(uid), f'"{dest_mailbox}"')
        if typ != "OK":
            raise Exception(f"Copy to {dest_mailbox} failed")
        typ, data = self.conn.uid("STORE", str(uid), "+FLAGS", "(\\Deleted)")
        if typ == "OK":
            self.conn.expunge()

    def copy_message(self, source_mailbox: str, uid: str, dest_mailbox: str):
        self._select_mailbox(source_mailbox)
        typ, data = self.conn.uid("COPY", str(uid), f'"{dest_mailbox}"')
        if typ != "OK":
            raise Exception(f"Copy failed")

    def delete_message(self, mailbox: str, uid: str):
        self._select_mailbox(mailbox)
        typ, data = self.conn.uid("STORE", str(uid), "+FLAGS", "(\\Deleted)")
        if typ != "OK":
            raise Exception("Delete failed")
        self.conn.expunge()

    def expunge(self, mailbox: str):
        self._select_mailbox(mailbox)
        self.conn.expunge()

    # --- Search ---
    def search(self, mailbox: str, criteria: str, page=1, page_size=50):
        # Direct IMAP search criteria string, e.g., 'FROM "bob@example.com"'
        self._select_mailbox(mailbox, readonly=True)
        typ, data = self.conn.uid("SEARCH", None, criteria)
        if typ != "OK":
            raise Exception("Search failed")
        uids = data[0].split() if data and data[0] else []
        total = len(uids)
        uids = uids[::-1]
        start = (page-1)*page_size
        page_uids = uids[start:start+page_size]
        # Reuse list logic for page_uids
        if not page_uids:
            return {"messages": [], "total": total, "page": page, "pageSize": page_size}
        # Use fallback fetch
        messages = self._fallback_list_fetch(page_uids, mailbox)
        return {"messages": messages, "total": total, "page": page, "pageSize": page_size}

    # --- Append (for drafts) ---
    def append_message(self, mailbox: str, raw_message: bytes, flags="\\Draft"):
        # Append to mailbox, return the new UID when the server supports UIDPLUS.
        import time
        date = imaplib.Time2Internaldate(time.time())
        try:
            typ, data = self.conn.append(f'"{mailbox}"', f"({flags})", date, raw_message)
            if typ != "OK":
                raise Exception(f"APPEND failed: {data}")
        except imaplib.IMAP4.error as e:
            raise Exception(f"APPEND error: {e}")
        # Try UIDPLUS APPENDUID response: e.g. [APPENDUID 123 456]
        try:
            if data and data[0]:
                raw = data[0].decode(errors="replace") if isinstance(data[0], bytes) else str(data[0])
                m = re.search(r"APPENDUID\s+\d+\s+(\d+)", raw)
                if m:
                    return m.group(1)
        except Exception:
            pass
        # Fallback: newest UID in mailbox
        try:
            self._select_mailbox(mailbox, readonly=True)
            typ2, data2 = self.conn.uid("SEARCH", None, "ALL")
            if typ2 == "OK" and data2 and data2[0]:
                uids = data2[0].split()
                if uids:
                    return uids[-1].decode() if isinstance(uids[-1], bytes) else str(uids[-1])
        except Exception:
            pass
        return None

    def save_draft(self, mailbox: str, raw_message: bytes, draft_uid: str = None):
        # Replace-in-place: delete the previous autosave first so each compose
        # session maps to exactly ONE IMAP message (prevents hundreds of drafts).
        if draft_uid:
            try:
                self._select_mailbox(mailbox)
                self.conn.uid("STORE", str(draft_uid), "+FLAGS", "(\\Deleted)")
                self.conn.expunge()
            except Exception:
                pass
        new_uid = self.append_message(mailbox, raw_message, flags="\\Draft")
        return new_uid

    def delete_draft(self, mailbox: str, draft_uid: str):
        """Delete a single draft by UID. Used for discard + post-send cleanup."""
        self._select_mailbox(mailbox)
        typ, _ = self.conn.uid("STORE", str(draft_uid), "+FLAGS", "(\\Deleted)")
        if typ != "OK":
            raise Exception("Draft delete failed")
        self.conn.expunge()

    def cleanup_duplicate_drafts(self, mailbox: str, keep_newest: int = 10):
        """One-time janitor: keep only the N newest drafts, delete the rest.
        Returns (kept, deleted). Call from POST /drafts/ {action: cleanup}."""
        from apps.mail.services.parser import normalize_subject
        self._select_mailbox(mailbox, readonly=True)
        typ, data = self.conn.uid("SEARCH", None, "ALL")
        if typ != "OK" or not data or not data[0]:
            return 0, 0
        uids = data[0].split()
        if len(uids) <= keep_newest:
            return len(uids), 0
        # Oldest first (SEARCH returns ascending); delete all but newest N.
        to_delete = uids[: len(uids) - keep_newest]
        uid_str = b",".join(to_delete).decode() if isinstance(to_delete[0], bytes) else ",".join(to_delete)
        self._select_mailbox(mailbox)
        self.conn.uid("STORE", uid_str, "+FLAGS", "(\\Deleted)")
        self.conn.expunge()
        return keep_newest, len(to_delete)
