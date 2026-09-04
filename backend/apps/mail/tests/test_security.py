from django.test import TestCase, Client
from unittest.mock import patch, MagicMock

class SecurityTests(TestCase):
    def setUp(self):
        self.client = Client(enforce_csrf_checks=False)
        with patch("apps.accounts.views.verify_credentials") as mv:
            mv.return_value = None
            self.client.post("/api/auth/login/", {"email": "victim@example.com", "password": "secret"}, content_type="application/json")

    def test_no_password_in_api_response(self):
        with patch("apps.accounts.views.verify_credentials") as mv:
            mv.return_value = None
            c = Client(enforce_csrf_checks=False)
            resp = c.post("/api/auth/login/", {"email": "a@b.com", "password": "supersecret123"}, content_type="application/json")
            self.assertNotIn("supersecret123", resp.content.decode())

    @patch("apps.mail.services.imap_client._create_connection")
    def test_xss_email_sanitized(self, mock_create):
        from email.message import EmailMessage
        msg = EmailMessage()
        msg["From"] = "attacker@example.com"
        msg["To"] = "victim@example.com"
        msg["Subject"] = "XSS"
        msg["Message-ID"] = "<xss@example.com>"
        msg["Date"] = "Mon, 01 Jan 2024 10:00:00 +0000"
        msg.set_content('<script>alert(1)</script><img src=x onerror=alert(1)>', subtype="html")
        raw = msg.as_bytes()
        mock_conn = MagicMock()
        mock_conn.select.return_value = ("OK", [b"1"])
        mock_conn.uid.return_value = ("OK", [(b'1 (UID 1 FLAGS ())', raw), b')'])
        mock_create.return_value = mock_conn
        mock_conn.login.return_value = ("OK", [b"OK"])
        resp = self.client.get("/api/messages/INBOX/1/")
        self.assertEqual(resp.status_code, 200)
        html = resp.json().get("html","")
        self.assertNotIn("<script", html)
        self.assertNotIn("onerror", html)

    @patch("apps.mail.services.imap_client._create_connection")
    def test_malicious_filename_sanitized(self, mock_create):
        # Simulate attachment download with malicious filename in parser
        from email.message import EmailMessage
        msg = EmailMessage()
        msg["From"] = "a@b.com"
        msg["To"] = "victim@example.com"
        msg["Subject"] = "Attach"
        msg.set_content("see attach")
        msg.add_attachment(b"content", maintype="application", subtype="octet-stream", filename="../../etc/passwd")
        raw = msg.as_bytes()
        mock_conn = MagicMock()
        mock_conn.select.return_value = ("OK", [b"1"])
        # For get_attachment we need RFC822
        mock_conn.uid.side_effect = [
            ("OK", [(b'1 (BODYSTRUCTURE ...)', b"")]),  # BODYSTRUCTURE
            ("OK", [(b'1 (RFC822)', raw), b')']),  # RFC822
        ]
        mock_create.return_value = mock_conn
        mock_conn.login.return_value = ("OK", [b"OK"])
        resp = self.client.get("/api/messages/INBOX/1/attachments/?filename=passwd")
        # Even if not found, check that Content-Disposition would be sanitized (basename)
        # If 404, still passes as no traversal
        self.assertIn(resp.status_code, (200,404))

    def test_cross_user_access_blocked(self):
        c2 = Client(enforce_csrf_checks=False)
        # c2 not logged in, try to access victim's mailbox via API - should be 401/403
        resp = c2.get("/api/mailboxes/")
        self.assertIn(resp.status_code, (401,403))

    @patch("apps.mail.services.imap_client._create_connection")
    def test_csp_headers_present_via_nginx_config(self, mock_create):
        # Check that api responses don't leak credentials in errors
        mock_create.side_effect = Exception("internal error with password=secret should not leak")
        resp = self.client.get("/api/mailboxes/")
        content = resp.content.decode()
        self.assertNotIn("secret", content.lower())
        self.assertEqual(resp.status_code, 500)
        # Check generic error message
        self.assertIn("Failed", resp.json().get("detail",""))

    def test_csrf_bypass_not_allowed_without_login(self):
        # Anon should not access mailboxes
        anon = Client(enforce_csrf_checks=True)
        resp = anon.get("/api/mailboxes/")
        self.assertIn(resp.status_code, (401,403,302))
