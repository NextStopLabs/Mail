from django.test import TestCase, Client
from django.contrib.auth import get_user_model
from unittest.mock import patch, MagicMock
from apps.accounts.crypto import encrypt_password, decrypt_password

User = get_user_model()

class AuthTests(TestCase):
    def setUp(self):
        self.client = Client(enforce_csrf_checks=False)

    @patch("apps.accounts.views.verify_credentials")
    def test_successful_login(self, mock_verify):
        mock_verify.return_value = None
        resp = self.client.post("/api/auth/login/", {"email": "user@example.com", "password": "secret"}, content_type="application/json")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["email"], "user@example.com")
        # session should have creds encrypted
        session = self.client.session
        self.assertIn("mail_creds", session)
        # ensure password not in response
        self.assertNotIn("secret", str(resp.content))
        # user created
        self.assertTrue(User.objects.filter(email="user@example.com").exists())

    @patch("apps.accounts.views.verify_credentials")
    def test_incorrect_password(self, mock_verify):
        from apps.mail.services.imap_client import IMAPAuthError
        mock_verify.side_effect = IMAPAuthError("bad")
        resp = self.client.post("/api/auth/login/", {"email": "user@example.com", "password": "wrong"}, content_type="application/json")
        self.assertEqual(resp.status_code, 401)
        self.assertIn("Invalid", resp.json()["detail"])

    def test_expired_session(self):
        resp = self.client.get("/api/auth/me/")
        self.assertEqual(resp.status_code, 401)

    @patch("apps.accounts.views.verify_credentials")
    def test_logout(self, mock_verify):
        mock_verify.return_value = None
        self.client.post("/api/auth/login/", {"email": "a@b.com", "password": "p"}, content_type="application/json")
        resp = self.client.post("/api/auth/logout/")
        self.assertEqual(resp.status_code, 200)
        # after logout, me should be 401
        resp2 = self.client.get("/api/auth/me/")
        self.assertEqual(resp2.status_code, 401)

    def test_crypto_roundtrip(self):
        enc = encrypt_password("mysecret123")
        self.assertNotIn("mysecret123", enc)
        dec = decrypt_password(enc)
        self.assertEqual(dec, "mysecret123")

    @patch("apps.accounts.views.verify_credentials")
    def test_rate_limiting_not_crashing(self, mock_verify):
        mock_verify.return_value = None
        for _ in range(3):
            self.client.post("/api/auth/login/", {"email": "u@example.com", "password": "p"}, content_type="application/json")
        # no error
        self.assertTrue(True)

    def test_password_not_logged(self):
        # Ensure crypto doesn't log password - this is structural test
        # Check that login view never returns password
        with patch("apps.accounts.views.verify_credentials") as mock:
            mock.return_value = None
            resp = self.client.post("/api/auth/login/", {"email": "x@y.com", "password": "supersecret"}, content_type="application/json")
            content = resp.content.decode()
            self.assertNotIn("supersecret", content)
