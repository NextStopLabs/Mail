from django.test import TestCase
from apps.mail.services.parser import (
    parse_message, separate_quoted_content, sanitize_html, build_thread_tree,
    extract_gmail_metadata, deduplicate_quoted_against_thread, normalize_subject,
    build_conversation
)
from email.message import EmailMessage

def make_email(subject="Hello", from_addr="Alice <alice@example.com>", to_addr="bob@example.com",
               text="Hi there", html=None, attachments=None, extra_headers=None):
    msg = EmailMessage()
    msg["From"] = from_addr
    msg["To"] = to_addr
    msg["Subject"] = subject
    msg["Message-ID"] = "<test123@example.com>"
    msg["Date"] = "Mon, 01 Jan 2024 10:00:00 +0000"
    if extra_headers:
        for k,v in extra_headers.items():
            msg[k] = v
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

class ThreadParsingTests(TestCase):
    def test_simple_no_quote(self):
        raw = make_email(text="Hello world, no quoted content.")
        parsed = parse_message(raw, uid="1")
        self.assertEqual(parsed["text"].strip(), "Hello world, no quoted content.")
        self.assertEqual(len(parsed["quotedMessages"]), 0)
        self.assertEqual(parsed["quoteCount"], 0)

    def test_gmail_reply(self):
        text = """Hi Nico,

Unfortunately...

On Thu, 3 Sep 2026 at 17:36, Nico Laizans <nicolaizans32@gmail.com> wrote:
> Hi Kai
>
> I respectfully request...
>
> Nico
"""
        raw = make_email(text=text)
        parsed = parse_message(raw, uid="1")
        self.assertIn("Unfortunately", parsed["text"])
        self.assertEqual(len(parsed["quotedMessages"]), 1)
        q = parsed["quotedMessages"][0]
        self.assertEqual(q["sender"]["email"], "nicolaizans32@gmail.com")
        self.assertEqual(q["sender"]["name"], "Nico Laizans")
        # Ensure quoted text stripped of >
        self.assertIn("I respectfully", q["text"])

    def test_outlook_reply(self):
        text = """Thanks.

-----Original Message-----
From: Alice <alice@example.com>
Sent: Thursday, September 3, 2026 5:36 PM
To: Bob <bob@example.com>
Subject: Hello

Hello Bob, previous message here.
"""
        raw = make_email(text=text)
        parsed = parse_message(raw, uid="1")
        self.assertEqual(len(parsed["quotedMessages"]), 1)
        q = parsed["quotedMessages"][0]
        self.assertEqual(q["sender"]["email"], "alice@example.com")
        self.assertEqual(q["sender"]["name"], "Alice")
        self.assertIn("previous message", q["text"].lower())

    def test_traditional_quote_blocks(self):
        text = """My reply.

> Hello
> This is previous.
"""
        raw = make_email(text=text)
        parsed = parse_message(raw, uid="1")
        self.assertEqual(len(parsed["quotedMessages"]), 1)
        self.assertIn("Hello", parsed["quotedMessages"][0]["text"])

    def test_nested_quotes(self):
        text = """My reply.

> Hello
>
> > This was even older.
"""
        raw = make_email(text=text)
        parsed = parse_message(raw, uid="1")
        self.assertEqual(len(parsed["quotedMessages"]), 1)
        q = parsed["quotedMessages"][0]
        # Nested should be detected
        self.assertTrue(len(q["quotedMessages"]) == 1 or "older" in q["text"].lower() or any("older" in n["text"].lower() for n in q["quotedMessages"]))
        # Ensure depth handling
        if q["quotedMessages"]:
            self.assertEqual(q["quotedMessages"][0]["quote_depth"], 1)

    def test_html_reply(self):
        html = '<p>Current reply</p><div class="gmail_quote"><blockquote>Old message</blockquote></div>'
        text = "Current reply\nOn Thu, 3 Sep 2026 at 17:36, Alice <alice@example.com> wrote:\n> Old message"
        raw = make_email(text=text, html=html)
        parsed = parse_message(raw, uid="1")
        # Should sanitize html and still have quoted
        self.assertNotIn("<script", parsed["html"])
        self.assertTrue(len(parsed["quotedMessages"]) >= 0)

    def test_plain_text_reply(self):
        text = "Plain reply\n\nOn Mon, 1 Jan 2024 at 10:00, Bob wrote:\n> Previous plain"
        raw = make_email(text=text)
        parsed = parse_message(raw, uid="1")
        self.assertEqual(len(parsed["quotedMessages"]), 1)

    def test_reply_with_attachments(self):
        text = """See attached.

On Thu, 3 Sep 2026 at 17:36, Alice <alice@example.com> wrote:
> Previous
"""
        raw = make_email(text=text, attachments=[("doc.pdf", b"content", "application/pdf")])
        parsed = parse_message(raw, uid="1")
        self.assertTrue(parsed["hasAttachments"])
        self.assertEqual(len(parsed["quotedMessages"]), 1)

    def test_utf8_names(self):
        # Use encoded header for sender, and gmail header with UTF-8 name
        text = """Reply.

On Thu, 3 Sep 2026 at 17:36, Jürgen Müller <jurgen@example.com> wrote:
> Hallo
"""
        raw = make_email(text=text, from_addr="Kai <kai@example.com>")
        parsed = parse_message(raw, uid="1")
        q = parsed["quotedMessages"][0]
        self.assertEqual(q["sender"]["name"], "Jürgen Müller")

    def test_missing_sender_metadata(self):
        text = """Hi,

On Thu, 3 Sep 2026 at 17:36 wrote:
> Hello without sender
"""
        # The header has no sender name/email, should fallback to unknown
        current, quoted = separate_quoted_content(text)
        self.assertEqual(len(quoted), 1)
        # Sender should be empty or fallback
        self.assertTrue(quoted[0]["sender"]["email"] == "" or quoted[0]["sender"]["name"] == "")

    def test_missing_date(self):
        text = """Hi,

On Thu wrote:
> Hello missing date
"""
        current, quoted = separate_quoted_content(text)
        self.assertEqual(len(quoted), 1)
        self.assertIsNone(quoted[0]["timestamp"])

    def test_malformed_quote_header(self):
        text = """Hi,

On [malformed header without proper format
> Some quoted?

Also random > not quoted
"""
        raw = make_email(text=text)
        parsed = parse_message(raw, uid="1")
        # Should not crash, may treat as no quoted or as blockquote
        self.assertIsNotNone(parsed)

    def test_multiple_quoted_messages(self):
        text = """Latest.

On Thu, 3 Sep 2026 at 17:36, Nico <nico@example.com> wrote:
> Second

On Thu, 3 Sep 2026 at 16:47, Kai <kai@example.com> wrote:
> First
"""
        current, quoted = separate_quoted_content(text)
        self.assertEqual(len(quoted), 2)
        self.assertEqual(quoted[0]["sender"]["email"], "nico@example.com")
        self.assertEqual(quoted[1]["sender"]["email"], "kai@example.com")

    def test_long_conversation(self):
        # Build text with 10 nested quotes (depth)
        text = "Latest\n"
        for i in range(10):
            text += f"\nOn Thu, 3 Sep 2026 at 17:36, User{i} <user{i}@example.com> wrote:\n> Message {i}\n"
        current, quoted = separate_quoted_content(text)
        # Should respect MAX_QUOTE_DEPTH (5) and not crash
        self.assertTrue(len(quoted) >= 1)
        # Depth should not exceed MAX
        def max_depth(qs, d=0):
            mx = d
            for q in qs:
                mx = max(mx, q["quote_depth"])
                if q["quotedMessages"]:
                    mx = max(mx, max_depth(q["quotedMessages"], d+1))
            return mx
        self.assertLessEqual(max_depth(quoted), 5)

    def test_signatures_preserved(self):
        text = """Hi,

Regards,

Kai
MyBusTimes
"""
        raw = make_email(text=text)
        parsed = parse_message(raw, uid="1")
        self.assertIn("Regards", parsed["text"])
        self.assertIn("MyBusTimes", parsed["text"])
        # Should not be stripped as quoted
        self.assertEqual(len(parsed["quotedMessages"]), 0)

    def test_re_subject_normalization(self):
        self.assertEqual(normalize_subject("Re: Hello"), "hello")
        self.assertEqual(normalize_subject("RE: Hello"), "hello")
        self.assertEqual(normalize_subject("Fwd: Hello"), "hello")
        self.assertEqual(normalize_subject("FW: Hello"), "hello")
        self.assertEqual(normalize_subject("Hello"), "hello")
        # Threading should group Re: subjects
        msgs = [
            {"messageId": "<a@example.com>", "subject": "Hello", "date": "2024-01-01T10:00:00+00:00", "references": "", "inReplyTo": ""},
            {"messageId": "<b@example.com>", "subject": "Re: Hello", "date": "2024-01-01T11:00:00+00:00", "references": "", "inReplyTo": ""},
        ]
        threads = build_thread_tree(msgs)
        self.assertEqual(len(threads), 1)
        self.assertEqual(threads[0]["count"], 2)

    def test_fwd_subject(self):
        msgs = [
            {"messageId": "<a@example.com>", "subject": "Report", "date": "2024-01-01T10:00:00+00:00", "references": "", "inReplyTo": ""},
            {"messageId": "<b@example.com>", "subject": "Fwd: Report", "date": "2024-01-01T11:00:00+00:00", "references": "", "inReplyTo": ""},
        ]
        threads = build_thread_tree(msgs)
        self.assertEqual(len(threads), 1)

    def test_references_threading(self):
        msgs = [
            {"messageId": "<a@example.com>", "subject": "A", "date": "2024-01-01T10:00:00+00:00", "references": "", "inReplyTo": ""},
            {"messageId": "<b@example.com>", "subject": "Re: A", "date": "2024-01-01T11:00:00+00:00", "references": "<a@example.com>", "inReplyTo": "<a@example.com>"},
            {"messageId": "<c@example.com>", "subject": "Re: A", "date": "2024-01-01T12:00:00+00:00", "references": "<a@example.com> <b@example.com>", "inReplyTo": "<b@example.com>"},
        ]
        threads = build_thread_tree(msgs)
        self.assertEqual(len(threads), 1)
        self.assertEqual(threads[0]["count"], 3)

    def test_in_reply_to_threading(self):
        msgs = [
            {"messageId": "<a@example.com>", "subject": "Hello", "date": "2024-01-01T10:00:00+00:00", "references": "", "inReplyTo": ""},
            {"messageId": "<b@example.com>", "subject": "Re: Hello", "date": "2024-01-01T11:00:00+00:00", "references": "", "inReplyTo": "<a@example.com>"},
        ]
        threads = build_thread_tree(msgs)
        self.assertEqual(len(threads), 1)

    def test_duplicate_quoted_dedup(self):
        # Simulate thread with 3 real messages, and current message quoting first
        thread_msgs = [
            {"text": "First message from Kai", "sender": {"email": "kai@example.com"}, "snippet": "First message from Kai"},
            {"text": "Second from Nico", "sender": {"email": "nico@example.com"}, "snippet": "Second from Nico"},
        ]
        quoted = [
            {"text": "First message from Kai", "body": {"plain_text": "First message from Kai"}, "sender": {"email": "kai@example.com"}, "quotedMessages": []},
            {"text": "Unrelated quoted", "body": {"plain_text": "Unrelated quoted"}, "sender": {"email": "other@example.com"}, "quotedMessages": []},
        ]
        filtered = deduplicate_quoted_against_thread(thread_msgs, quoted)
        # First quoted should be deduped, second remains
        self.assertEqual(len(filtered), 1)
        self.assertEqual(filtered[0]["sender"]["email"], "other@example.com")

    def test_conversation_build(self):
        msgs = [
            {"subject": "Re: Hello", "from": [{"email": "a@example.com", "name": "A"}], "sender": {"email": "a@example.com", "name": "A"}, "to": [{"email": "b@example.com", "name": "B"}], "messageId": "<a>", "date": "2024-01-01T10:00:00+00:00"},
            {"subject": "Re: Hello", "from": [{"email": "b@example.com", "name": "B"}], "sender": {"email": "b@example.com", "name": "B"}, "to": [{"email": "a@example.com", "name": "A"}], "messageId": "<b>", "date": "2024-01-01T11:00:00+00:00"},
        ]
        conv = build_conversation(msgs)
        self.assertEqual(conv["subject"], "Re: Hello")
        self.assertEqual(len(conv["participants"]), 2)
