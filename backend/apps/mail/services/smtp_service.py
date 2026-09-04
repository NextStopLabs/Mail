import smtplib
import ssl
import logging
from email.message import EmailMessage
from email.utils import formatdate, make_msgid
from typing import List, Optional
from django.conf import settings

logger = logging.getLogger("mail")

class SMTPError(Exception):
    pass

class SMTPAuthError(SMTPError):
    pass

def send_mail_via_smtp(
    from_email: str,
    password: str,
    to: List[str],
    cc: List[str] = None,
    bcc: List[str] = None,
    subject: str = "",
    text_body: str = "",
    html_body: str = None,
    reply_to: str = None,
    in_reply_to: str = None,
    references: str = None,
    attachments: List[dict] = None,
) -> str:
    host = settings.MAIL_SMTP_HOST
    port = settings.MAIL_SMTP_PORT
    sec = settings.MAIL_SMTP_SECURITY.upper()

    msg = EmailMessage()
    msg["From"] = from_email
    msg["To"] = ", ".join(to)
    if cc:
        msg["Cc"] = ", ".join(cc)
    if bcc:
        # BCC not added to header but used in envelope
        pass
    msg["Subject"] = subject
    msg["Date"] = formatdate(localtime=True)
    msg["Message-ID"] = make_msgid(domain=from_email.split("@")[-1])
    if reply_to:
        msg["Reply-To"] = reply_to
    if in_reply_to:
        msg["In-Reply-To"] = in_reply_to
    if references:
        msg["References"] = references

    # Body: prefer html alternative
    if html_body and text_body:
        msg.set_content(text_body)
        msg.add_alternative(html_body, subtype="html")
    elif html_body:
        msg.set_content(html_body, subtype="html")
    else:
        msg.set_content(text_body or "")

    if attachments:
        for att in attachments:
            # att: {filename, content, mime}
            filename = att.get("filename", "attachment")
            content = att.get("content")  # bytes
            mime = att.get("mime", "application/octet-stream")
            # sanitize filename
            filename = filename.replace("\n", "").replace("\r", "").strip() or "attachment"
            maintype, subtype = mime.split("/", 1) if "/" in mime else ("application", "octet-stream")
            msg.add_attachment(content, maintype=maintype, subtype=subtype, filename=filename)

    # Recipients for SMTP envelope
    recipients = list(to) + (cc or []) + (bcc or [])

    try:
        if sec == "SSL":
            ctx = ssl.create_default_context()
            server = smtplib.SMTP_SSL(host, port, context=ctx, timeout=20)
        else:
            server = smtplib.SMTP(host, port, timeout=20)
            if sec == "STARTTLS":
                ctx = ssl.create_default_context()
                server.starttls(context=ctx)
        try:
            server.login(from_email, password)
            server.send_message(msg, from_addr=from_email, to_addrs=recipients)
        finally:
            try:
                server.quit()
            except Exception:
                pass
    except smtplib.SMTPAuthenticationError as e:
        logger.warning("SMTP auth failed for %s", from_email)
        raise SMTPAuthError("SMTP authentication failed") from e
    except smtplib.SMTPRecipientsRefused as e:
        raise SMTPError(f"Recipients refused: {e}") from e
    except smtplib.SMTPException as e:
        logger.error("SMTP error: %s", type(e).__name__)
        raise SMTPError(str(e)) from e
    except OSError as e:
        logger.error("SMTP connection error: %s", e)
        raise SMTPError("Could not connect to mail server") from e

    return msg["Message-ID"]
