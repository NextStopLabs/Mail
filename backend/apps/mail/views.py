import logging
import email.utils
from email.message import EmailMessage
from django.http import StreamingHttpResponse, HttpResponse
from django.views.decorators.csrf import csrf_exempt
from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework.permissions import IsAuthenticated
from apps.mail.services.imap_client import mail_connection, IMAPAuthError, IMAPConnectionError
from apps.mail.services.mail_service import MailService
from apps.mail.services.smtp_service import send_mail_via_smtp, SMTPError, SMTPAuthError
from apps.accounts.crypto import decrypt_password

logger = logging.getLogger("mail")

def _get_creds(request):
    token = request.session.get("mail_creds")
    email_addr = request.session.get("mail_email")
    if not token or not email_addr:
        raise IMAPAuthError("Missing credentials")
    pwd = decrypt_password(token)
    return email_addr, pwd

MAILBOX_CACHE_TTL = 60  # seconds

def _mailbox_cache_key(request):
    email_addr = request.session.get("mail_email", "anon")
    return f"mailboxes:{email_addr}"

def _invalidate_mailbox_cache(request):
    try:
        from django.core.cache import cache
        cache.delete(_mailbox_cache_key(request))
    except Exception:
        pass

class MailboxListView(APIView):
    permission_classes = [IsAuthenticated]
    def get(self, request):
        from django.core.cache import cache
        key = _mailbox_cache_key(request)
        try:
            cached = cache.get(key)
            if cached is not None:
                return Response(cached)
        except Exception:
            pass
        try:
            with mail_connection(request) as conn:
                svc = MailService(conn)
                mailboxes = svc.list_mailboxes()
                try:
                    cache.set(key, mailboxes, MAILBOX_CACHE_TTL)
                except Exception:
                    pass
                return Response(mailboxes)
        except IMAPAuthError:
            return Response({"detail": "Authentication expired. Please log in again."}, status=401)
        except IMAPConnectionError:
            return Response({"detail": "Mail server unavailable."}, status=503)
        except Exception as e:
            logger.error("mailbox list error: %s", type(e).__name__)
            return Response({"detail": "Failed to fetch mailboxes."}, status=500)

class MessageListView(APIView):
    permission_classes = [IsAuthenticated]
    def get(self, request, mailbox):
        # mailbox is URL-encoded; decode slash?
        import urllib.parse
        mailbox = urllib.parse.unquote(mailbox)
        page = int(request.query_params.get("page", "1"))
        page_size = min(int(request.query_params.get("page_size", "50")), 100)
        search = request.query_params.get("q") or request.query_params.get("search")
        filter_by = request.query_params.get("filter")
        # support ?filter=unread|flagged
        try:
            with mail_connection(request) as conn:
                svc = MailService(conn)
                # If raw IMAP criteria provided via ?criteria=
                criteria = request.query_params.get("criteria")
                if criteria:
                    result = svc.search(mailbox, criteria, page=page, page_size=page_size)
                else:
                    result = svc.list_messages(mailbox, page=page, page_size=page_size, search=search, filter_by=filter_by)
                return Response(result)
        except IMAPAuthError:
            return Response({"detail": "Auth expired"}, status=401)
        except IMAPConnectionError:
            return Response({"detail": "Mail server unavailable"}, status=503)
        except Exception as e:
            logger.error("message list error %s: %s", mailbox, type(e).__name__)
            return Response({"detail": "Failed to fetch messages."}, status=500)

class MessageDetailView(APIView):
    permission_classes = [IsAuthenticated]
    def get(self, request, mailbox, uid):
        import urllib.parse
        mailbox = urllib.parse.unquote(mailbox)
        include_thread = request.query_params.get("thread") in ("1","true","yes") or request.query_params.get("includeThread") in ("1","true","yes")
        try:
            with mail_connection(request) as conn:
                svc = MailService(conn)
                if include_thread:
                    thread_data = svc.get_thread(mailbox, uid)
                    # Return enriched structure: conversation + messages + current
                    # Keep backward compat: also include top-level message fields via currentMessage
                    resp = {
                        **thread_data["currentMessage"],
                        "conversation": thread_data["conversation"],
                        "thread": thread_data,
                        "messages": thread_data["messages"],
                        "currentMessage": thread_data["currentMessage"],
                    }
                    return Response(resp)
                else:
                    msg = svc.get_message(mailbox, uid)
                    # Attempt to enhance with conversation summary even without full thread fetch (lightweight)
                    try:
                        from apps.mail.services.parser import build_conversation
                        conv = build_conversation([msg])
                        msg["conversation"] = conv
                    except Exception:
                        pass
                    return Response(msg)
        except IMAPAuthError:
            return Response({"detail": "Auth expired"}, status=401)
        except Exception as e:
            logger.error("get message error: %s", type(e).__name__)
            return Response({"detail": "Message not found."}, status=404)

class ThreadDetailView(APIView):
    permission_classes = [IsAuthenticated]
    def get(self, request, mailbox, uid):
        import urllib.parse
        mailbox = urllib.parse.unquote(mailbox)
        try:
            with mail_connection(request) as conn:
                svc = MailService(conn)
                thread_data = svc.get_thread(mailbox, uid)
                return Response(thread_data)
        except IMAPAuthError:
            return Response({"detail": "Auth expired"}, status=401)
        except Exception as e:
            logger.error("thread error: %s", type(e).__name__)
            return Response({"detail": "Thread not found."}, status=404)

class MessageActionView(APIView):
    permission_classes = [IsAuthenticated]
    def post(self, request, mailbox, uid, action):
        import urllib.parse
        mailbox = urllib.parse.unquote(mailbox)
        try:
            with mail_connection(request) as conn:
                svc = MailService(conn)
                if action == "read":
                    read = request.data.get("read", True)
                    # accept bool or string
                    if isinstance(read, str):
                        read = read.lower() in ("true", "1", "yes")
                    svc.mark_read(mailbox, uid, bool(read))
                    _invalidate_mailbox_cache(request)
                    return Response({"detail": "ok", "read": bool(read)})
                elif action == "flag":
                    flagged = request.data.get("flagged", request.data.get("starred", True))
                    if isinstance(flagged, str):
                        flagged = flagged.lower() in ("true", "1", "yes")
                    svc.star(mailbox, uid, bool(flagged))
                    return Response({"detail": "ok", "starred": bool(flagged)})
                elif action == "move":
                    dest = request.data.get("dest") or request.data.get("mailbox") or request.data.get("folder")
                    if not dest:
                        return Response({"detail": "Destination required"}, status=400)
                    svc.move_message(mailbox, uid, dest)
                    _invalidate_mailbox_cache(request)
                    return Response({"detail": "moved", "dest": dest})
                elif action == "copy":
                    dest = request.data.get("dest") or request.data.get("mailbox")
                    if not dest:
                        return Response({"detail": "Destination required"}, status=400)
                    svc.copy_message(mailbox, uid, dest)
                    _invalidate_mailbox_cache(request)
                    return Response({"detail": "copied"})
                elif action == "delete":
                    svc.delete_message(mailbox, uid)
                    _invalidate_mailbox_cache(request)
                    return Response({"detail": "deleted"})
                else:
                    return Response({"detail": "Unknown action"}, status=400)
        except IMAPAuthError:
            return Response({"detail": "Auth expired"}, status=401)
        except Exception as e:
            logger.error("action %s error: %s", action, type(e).__name__)
            return Response({"detail": f"Action {action} failed."}, status=500)

class BulkActionView(APIView):
    permission_classes = [IsAuthenticated]
    def post(self, request):
        # body: {mailbox, uids: [], action: "read|flag|move|delete", value, dest}
        mailbox = request.data.get("mailbox")
        uids = request.data.get("uids", [])
        action = request.data.get("action")
        if not mailbox or not uids or not action:
            return Response({"detail": "mailbox, uids, action required"}, status=400)
        results = []
        try:
            with mail_connection(request) as conn:
                svc = MailService(conn)
                for uid in uids:
                    try:
                        if action == "read":
                            svc.mark_read(mailbox, str(uid), bool(request.data.get("value", True)))
                        elif action == "flag":
                            svc.star(mailbox, str(uid), bool(request.data.get("value", True)))
                        elif action == "delete":
                            svc.delete_message(mailbox, str(uid))
                        elif action == "move":
                            dest = request.data.get("dest")
                            svc.move_message(mailbox, str(uid), dest)
                        results.append({"uid": uid, "ok": True})
                    except Exception as e:
                        results.append({"uid": uid, "ok": False, "error": type(e).__name__})
                _invalidate_mailbox_cache(request)
                return Response({"results": results})
        except IMAPAuthError:
            return Response({"detail": "Auth expired"}, status=401)
        except Exception as e:
            logger.error("bulk action error: %s", e)
            return Response({"detail": "Bulk action failed"}, status=500)

class AttachmentView(APIView):
    permission_classes = [IsAuthenticated]
    def get(self, request, mailbox, uid):
        import urllib.parse
        mailbox = urllib.parse.unquote(mailbox)
        part = request.query_params.get("part")
        filename = request.query_params.get("filename")
        # also support attachment index via part
        try:
            with mail_connection(request) as conn:
                svc = MailService(conn)
                data, fname, mime = svc.get_attachment(mailbox, uid, part_index=part, filename=filename)
                # Security: sanitize mime, never trust sender mime
                # Validate mime is plausible
                if "/" not in mime:
                    mime = "application/octet-stream"
                # Content-Disposition: attachment with sanitized filename
                # Prevent XSS via mime sniffing: set X-Content-Type-Options
                response = HttpResponse(data, content_type=mime)
                # Use RFC 5987 for filename
                safe_fname = fname.replace('"', "_")
                response["Content-Disposition"] = f'attachment; filename="{safe_fname}"'
                response["X-Content-Type-Options"] = "nosniff"
                response["Content-Length"] = str(len(data))
                # Stream large files? For now small; to stream large would use StreamingHttpResponse
                # Avoid loading huge into RAM: check size limit
                if len(data) > 50 * 1024 * 1024:
                    return Response({"detail": "Attachment too large"}, status=413)
                return response
        except Exception as e:
            logger.error("attachment fetch error: %s", type(e).__name__)
            return Response({"detail": "Attachment not found"}, status=404)

class SendView(APIView):
    permission_classes = [IsAuthenticated]
    def post(self, request):
        # Expect: to, cc, bcc, subject, text, html, attachments (base64), inReplyTo, references, mailbox for draft cleanup
        data = request.data
        to = data.get("to", [])
        if isinstance(to, str):
            to = [to]
        cc = data.get("cc", [])
        if isinstance(cc, str):
            cc = [cc]
        bcc = data.get("bcc", [])
        if isinstance(bcc, str):
            bcc = [bcc]
        subject = data.get("subject", "")
        text_body = data.get("text") or data.get("body") or ""
        html_body = data.get("html")
        in_reply_to = data.get("inReplyTo")
        references = data.get("references")
        attachments = data.get("attachments", [])  # list of {filename, content (base64), mime}

        if not to:
            return Response({"detail": "Recipient required"}, status=400)

        # Validate email addresses superficially
        import re
        email_re = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
        for addr in to + (cc or []) + (bcc or []):
            if addr and not email_re.match(addr.strip()):
                return Response({"detail": f"Invalid recipient: {addr}"}, status=400)

        # Parse attachments base64
        parsed_attachments = []
        for att in attachments or []:
            try:
                import base64
                content_b64 = att.get("content", "")
                # If already bytes-like
                if isinstance(content_b64, str) and content_b64.startswith("data:"):
                    # data uri
                    content_b64 = content_b64.split(",", 1)[1]
                content = base64.b64decode(content_b64) if content_b64 else b""
                if len(content) > 25 * 1024 * 1024:
                    return Response({"detail": f"Attachment {att.get('filename')} too large"}, status=413)
                # Sanitize filename and mime
                fname = (att.get("filename") or "attachment").replace("\n","").replace("\r","").strip()
                mime = att.get("mime") or att.get("contentType") or "application/octet-stream"
                # Basic mime validation
                if "/" not in mime:
                    mime = "application/octet-stream"
                parsed_attachments.append({"filename": fname[:200], "content": content, "mime": mime})
            except Exception:
                return Response({"detail": "Invalid attachment encoding"}, status=400)

        try:
            email_addr, pwd = _get_creds(request)
        except IMAPAuthError:
            return Response({"detail": "Auth expired"}, status=401)

        try:
            msg_id = send_mail_via_smtp(
                from_email=email_addr,
                password=pwd,
                to=to,
                cc=cc if cc else None,
                bcc=bcc if bcc else None,
                subject=subject,
                text_body=text_body,
                html_body=html_body,
                in_reply_to=in_reply_to,
                references=references,
                attachments=parsed_attachments if parsed_attachments else None,
            )
            # Append to Sent folder if possible (best effort)
            try:
                # Build raw message to append to Sent
                msg = EmailMessage()
                msg["From"] = email_addr
                msg["To"] = ", ".join(to)
                if cc:
                    msg["Cc"] = ", ".join(cc)
                msg["Subject"] = subject
                msg["Date"] = email.utils.formatdate(localtime=True)
                msg["Message-ID"] = msg_id
                if html_body and text_body:
                    msg.set_content(text_body)
                    msg.add_alternative(html_body, subtype="html")
                elif html_body:
                    msg.set_content(html_body, subtype="html")
                else:
                    msg.set_content(text_body or "")
                for att in parsed_attachments:
                    maintype, subtype = att["mime"].split("/",1) if "/" in att["mime"] else ("application","octet-stream")
                    msg.add_attachment(att["content"], maintype=maintype, subtype=subtype, filename=att["filename"])
                raw = msg.as_bytes()
                with mail_connection(request) as conn:
                    svc = MailService(conn)
                    # Find Sent mailbox dynamically
                    mailboxes = svc.list_mailboxes()
                    sent_name = next((m["fullName"] for m in mailboxes if m["role"] == "sent"), "Sent")
                    try:
                        svc.append_message(sent_name, raw, flags="\\Seen")
                    except Exception:
                        # Try INBOX.Sent
                        try:
                            svc.append_message("INBOX.Sent", raw, flags="\\Seen")
                        except Exception:
                            pass
            except Exception as e:
                logger.debug("append to sent failed: %s", e)

            # Delete the autosaved draft so sent mail doesn't leave a duplicate behind.
            draft_uid = data.get("draftUid") or data.get("draft_uid")
            draft_mailbox = data.get("draftMailbox") or data.get("draft_mailbox") or data.get("mailbox")
            if draft_uid:
                try:
                    with mail_connection(request) as conn:
                        svc = MailService(conn)
                        if not draft_mailbox or draft_mailbox in ("Drafts", "Draft"):
                            mailboxes = svc.list_mailboxes()
                            draft_mailbox = next((m["fullName"] for m in mailboxes if m["role"] == "drafts"), draft_mailbox or "Drafts")
                        svc.delete_draft(draft_mailbox, str(draft_uid))
                except Exception as e:
                    logger.debug("delete sent draft failed: %s", e)
            _invalidate_mailbox_cache(request)

            return Response({"detail": "Sent", "messageId": msg_id})
        except SMTPAuthError:
            return Response({"detail": "SMTP authentication failed. Please re-login."}, status=401)
        except SMTPError as e:
            logger.error("smtp send error: %s", str(e)[:200])
            return Response({"detail": "Failed to send email. Please check recipients and try again."}, status=502)
        except Exception as e:
            logger.error("send error: %s", type(e).__name__)
            return Response({"detail": "Failed to send email."}, status=500)

class DraftView(APIView):
    permission_classes = [IsAuthenticated]
    def post(self, request):
        # Save draft: to, cc, bcc, subject, text, html, mailbox?, draftUid
        # Or cleanup: {action: "cleanup", keep: 10}
        data = request.data
        if data.get("action") == "cleanup":
            keep = data.get("keep", 10)
            try:
                keep = max(1, min(int(keep), 100))
            except Exception:
                keep = 10
            try:
                with mail_connection(request) as conn:
                    svc = MailService(conn)
                    mailbox = data.get("mailbox") or "Drafts"
                    if mailbox in ("Drafts", "Draft"):
                        mailboxes = svc.list_mailboxes()
                        draft_mbox = next((m["fullName"] for m in mailboxes if m["role"] == "drafts"), mailbox)
                    else:
                        draft_mbox = mailbox
                    kept, deleted = svc.cleanup_duplicate_drafts(draft_mbox, keep_newest=keep)
                    _invalidate_mailbox_cache(request)
                    return Response({"detail": f"Cleaned up drafts: kept {kept}, deleted {deleted}", "kept": kept, "deleted": deleted, "mailbox": draft_mbox})
            except IMAPAuthError:
                return Response({"detail": "Auth expired"}, status=401)
            except Exception as e:
                logger.error("draft cleanup error: %s", type(e).__name__)
                return Response({"detail": "Failed to clean up drafts"}, status=500)

        mailbox = data.get("mailbox") or "Drafts"
        draft_uid = data.get("draftUid") or data.get("uid")
        to = data.get("to", [])
        if isinstance(to, str):
            to = [to]
        cc = data.get("cc", [])
        bcc = data.get("bcc", [])
        subject = (data.get("subject", "") or "").strip()
        text_body = data.get("text") or data.get("body") or ""
        html_body = data.get("html") or ""
        attachments_in = data.get("attachments", []) or []

        # Guard: never store completely empty drafts (a major source of pile-up).
        if not to and not cc and not bcc and not subject and not (text_body or "").strip() and not attachments_in:
            return Response({"detail": "Empty draft skipped", "skipped": True})

        try:
            email_addr, _ = _get_creds(request)
        except IMAPAuthError:
            return Response({"detail": "Auth expired"}, status=401)

        # Build MIME message
        msg = EmailMessage()
        msg["From"] = email_addr
        if to:
            msg["To"] = ", ".join(to if isinstance(to, list) else [to])
        if cc:
            msg["Cc"] = ", ".join(cc if isinstance(cc, list) else [cc])
        if bcc:
            msg["Bcc"] = ", ".join(bcc if isinstance(bcc, list) else [bcc])
        msg["Subject"] = subject
        msg["Date"] = email.utils.formatdate(localtime=True)
        msg["X-Mailer"] = "NextStop Webmail"

        if html_body and text_body:
            msg.set_content(text_body)
            msg.add_alternative(html_body, subtype="html")
        elif html_body:
            msg.set_content(html_body, subtype="html")
        else:
            msg.set_content(text_body or "")

        # Attachments if any
        for att in data.get("attachments", []) or []:
            try:
                import base64
                content = base64.b64decode(att.get("content",""))
                fname = att.get("filename","attachment")
                mime = att.get("mime","application/octet-stream")
                maintype, subtype = mime.split("/",1) if "/" in mime else ("application","octet-stream")
                msg.add_attachment(content, maintype=maintype, subtype=subtype, filename=fname)
            except Exception:
                continue

        raw = msg.as_bytes()
        try:
            with mail_connection(request) as conn:
                svc = MailService(conn)
                # Detect drafts folder dynamically if provided is generic
                if mailbox in ("Drafts", "Draft"):
                    mailboxes = svc.list_mailboxes()
                    draft_mbox = next((m["fullName"] for m in mailboxes if m["role"] == "drafts"), mailbox)
                else:
                    draft_mbox = mailbox
                new_uid = svc.save_draft(draft_mbox, raw, draft_uid=str(draft_uid) if draft_uid else None)
                _invalidate_mailbox_cache(request)
                return Response({"detail": "Draft saved", "uid": new_uid, "mailbox": draft_mbox})
        except Exception as e:
            logger.error("draft save error: %s", type(e).__name__)
            return Response({"detail": "Failed to save draft"}, status=500)

    def delete(self, request):
        # Discard a draft: {draftUid, mailbox}
        draft_uid = request.data.get("draftUid") or request.data.get("uid")
        mailbox = request.data.get("mailbox") or "Drafts"
        if not draft_uid:
            return Response({"detail": "draftUid required"}, status=400)
        try:
            with mail_connection(request) as conn:
                svc = MailService(conn)
                if mailbox in ("Drafts", "Draft", None, ""):
                    mailboxes = svc.list_mailboxes()
                    draft_mbox = next((m["fullName"] for m in mailboxes if m["role"] == "drafts"), "Drafts")
                else:
                    draft_mbox = mailbox
                try:
                    svc.delete_draft(draft_mbox, str(draft_uid))
                except Exception:
                    # Already gone — treat as success so the client doesn't get stuck
                    pass
                _invalidate_mailbox_cache(request)
                return Response({"detail": "Draft discarded"})
        except IMAPAuthError:
            return Response({"detail": "Auth expired"}, status=401)
        except Exception as e:
            logger.error("draft delete error: %s", type(e).__name__)
            return Response({"detail": "Failed to discard draft"}, status=500)

    def get(self, request):
        # List drafts? Use message list for drafts folder
        import urllib.parse
        mailbox = request.query_params.get("mailbox", "Drafts")
        # Resolve drafts folder name
        try:
            with mail_connection(request) as conn:
                svc = MailService(conn)
                if mailbox in ("Drafts","Draft"):
                    mailboxes = svc.list_mailboxes()
                    draft_mbox = next((m["fullName"] for m in mailboxes if m["role"]=="drafts"), mailbox)
                else:
                    draft_mbox = mailbox
                result = svc.list_messages(draft_mbox, page=1, page_size=50)
                return Response(result)
        except Exception as e:
            logger.error("draft list error: %s", e)
            return Response({"detail": "Failed to fetch drafts"}, status=500)

class SearchView(APIView):
    permission_classes = [IsAuthenticated]
    def get(self, request):
        import urllib.parse
        mailbox = request.query_params.get("mailbox", "INBOX")
        mailbox = urllib.parse.unquote(mailbox)
        q = request.query_params.get("q", "")
        # Build IMAP search criteria from structured params if provided
        # Support: from, to, subject, since, before
        criteria_parts = []
        if request.query_params.get("from"):
            safe = request.query_params.get("from").replace('"',' ')
            criteria_parts.append(f'FROM "{safe}"')
        if request.query_params.get("subject"):
            safe = request.query_params.get("subject").replace('"',' ')
            criteria_parts.append(f'SUBJECT "{safe}"')
        if q:
            safe = q.replace('"',' ')
            # TEXT searches all
            criteria_parts.append(f'TEXT "{safe}"')
        if request.query_params.get("unread") == "true":
            criteria_parts.append("UNSEEN")
        if request.query_params.get("flagged") == "true":
            criteria_parts.append("FLAGGED")
        criteria = " ".join(criteria_parts) if criteria_parts else "ALL"
        page = int(request.query_params.get("page","1"))
        page_size = min(int(request.query_params.get("page_size","50")), 100)
        try:
            with mail_connection(request) as conn:
                svc = MailService(conn)
                result = svc.search(mailbox, criteria, page=page, page_size=page_size)
                return Response(result)
        except Exception as e:
            logger.error("search error: %s", e)
            return Response({"detail": "Search failed"}, status=500)
