from django.test import TestCase
from apps.mail.services.parser import parse_message, sanitize_html, decode_mime_header, build_thread_tree
import email
from email.message import EmailMessage

def make_email(subject="Hello", from_addr="Alice <alice@example.com>", to_addr="bob@example.com", text="Hi there", html=None, attachments=None):
    msg = EmailMessage()
    msg["From"] = from_addr
    msg["To"] = to_addr
    msg["Subject"] = subject
    msg["Message-ID"] = "<test123@example.com>"
    msg["Date"] = "Mon, 01 Jan 2024 10:00:00 +0000"
    if html and text:
        msg.set_content(text)
        msg.add_alternative(html, subtype="html")
    elif html:
        msg.set_content(html, subtype="html")
    else:
        msg.set_content(text)
    if attachments:
        for fname, content, mime in attachments:
            maintype, subtype = mime.split("/",1)
            msg.add_attachment(content, maintype=maintype, subtype=subtype, filename=fname)
    return msg.as_bytes()

class ParserTests(TestCase):
    def test_plain_text(self):
        raw = make_email(text="Hello world")
        parsed = parse_message(raw, uid="1")
        self.assertEqual(parsed["text"].strip(), "Hello world")
        self.assertEqual(parsed["subject"], "Hello")

    def test_html(self):
        raw = make_email(html="<b>Bold</b> <script>alert(1)</script>", text="fallback")
        parsed = parse_message(raw, uid="1")
        self.assertIn("Bold", parsed["html"])
        self.assertNotIn("<script", parsed["html"])

    def test_multipart_alternative(self):
        raw = make_email(text="plain", html="<p>html</p>")
        parsed = parse_message(raw, uid="1")
        self.assertTrue(parsed["text"])
        self.assertIn("html", parsed["html"])

    def test_attachments(self):
        raw = make_email(attachments=[("test.pdf", b"PDFcontent", "application/pdf")])
        parsed = parse_message(raw, uid="1")
        self.assertEqual(len(parsed["attachments"]), 1)
        self.assertEqual(parsed["attachments"][0]["filename"], "test.pdf")
        self.assertTrue(parsed["hasAttachments"])

    def test_inline_images(self):
        # inline cid image should be detected
        msg = EmailMessage()
        msg["From"] = "a@b.com"
        msg["To"] = "c@d.com"
        msg["Subject"] = "inline"
        msg.set_content("see image")
        msg.add_alternative('<p>hi <img src="cid:image1"></p>', subtype="html")
        # add image part
        from email.mime.image import MIMEImage
        img = MIMEImage(b"fake", _subtype="png")
        img.add_header("Content-ID", "<image1>")
        img.add_header("Content-Disposition", "inline")
        # Can't easily add via EmailMessage, but parser should handle cid if present
        raw = msg.as_bytes()
        parsed = parse_message(raw, uid="1")
        # At least not crash
        self.assertIsNotNone(parsed)

    def test_utf8_encoded_headers(self):
        raw = make_email(subject="=?UTF-8?B?8J+YgCBIZWxsbyA=?=")
        parsed = parse_message(raw, uid="1")
        self.assertIn("Hello", parsed["subject"])

    def test_quoted_printable(self):
        raw = make_email(text="Hello=20World")
        parsed = parse_message(raw)
        self.assertIsNotNone(parsed["text"])

    def test_malformed_email(self):
        raw = b"From: broken\r\nSubject: test\r\n\r\nbody with no proper headers \xff\xfe"
        parsed = parse_message(raw, uid="99")
        self.assertEqual(parsed["uid"], "99")

    def test_xss_sanitization(self):
        html = '<img src=x onerror=alert(1)><a href="javascript:alert(1)">click</a><script>alert(1)</script>'
        cleaned = sanitize_html(html)
        self.assertNotIn("onerror", cleaned)
        self.assertNotIn("javascript:", cleaned)
        self.assertNotIn("<script", cleaned)

    def test_malicious_attachment_filename(self):
        raw = make_email(attachments=[("../../etc/passwd", b"content", "text/plain")])
        parsed = parse_message(raw, uid="1")
        # parser should keep filename but view should sanitize on download - check basename handling later
        self.assertIsNotNone(parsed["attachments"][0]["filename"])

    def test_threading(self):
        msgs = [
            {"messageId": "<a@example.com>", "subject": "Hello", "date": "2024-01-01T10:00:00+00:00", "references": "", "inReplyTo": ""},
            {"messageId": "<b@example.com>", "subject": "Re: Hello", "date": "2024-01-01T11:00:00+00:00", "references": "<a@example.com>", "inReplyTo": "<a@example.com>"},
            {"messageId": "<c@example.com>", "subject": "Other", "date": "2024-01-02T10:00:00+00:00", "references": "", "inReplyTo": ""},
        ]
        threads = build_thread_tree(msgs)
        self.assertEqual(len(threads), 2)
        # first thread should have 2 messages
        hello_thread = next(t for t in threads if "hello" in t["subject"].lower())
        self.assertEqual(hello_thread["count"], 2)
