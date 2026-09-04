import imaplib
import ssl
import socket
import logging
from contextlib import contextmanager
from django.conf import settings

logger = logging.getLogger("mail")

class IMAPError(Exception):
    pass

class IMAPAuthError(IMAPError):
    pass

class IMAPConnectionError(IMAPError):
    pass

def _create_connection():
    host = settings.MAIL_IMAP_HOST
    port = settings.MAIL_IMAP_PORT
    sec = settings.MAIL_IMAP_SECURITY.upper()
    timeout = 15
    try:
        if sec == "SSL":
            ctx = ssl.create_default_context()
            conn = imaplib.IMAP4_SSL(host, port, ssl_context=ctx, timeout=timeout)
        elif sec == "STARTTLS":
            conn = imaplib.IMAP4(host, port, timeout=timeout)
            ctx = ssl.create_default_context()
            typ, _ = conn.starttls(ssl_context=ctx)
            if typ != "OK":
                raise IMAPConnectionError("STARTTLS failed")
        else:
            conn = imaplib.IMAP4(host, port, timeout=timeout)
        return conn
    except (socket.timeout, socket.error, ssl.SSLError, OSError, imaplib.IMAP4.error) as e:
        raise IMAPConnectionError(f"IMAP connection failed: {type(e).__name__}") from e

def verify_credentials(email: str, password: str) -> None:
    """Verify credentials by attempting login. Raises IMAPAuthError on bad creds, IMAPConnectionError on network failure."""
    conn = None
    try:
        conn = _create_connection()
        try:
            typ, data = conn.login(email, password)
            if typ != "OK":
                raise IMAPAuthError("Authentication failed")
        except imaplib.IMAP4.error as e:
            msg = str(e).lower()
            if "auth" in msg or "login" in msg or "credential" in msg or "invalid" in msg:
                raise IMAPAuthError("Invalid credentials") from e
            # Dovecot may return NO for auth failure
            raise IMAPAuthError("Invalid credentials") from e
    except IMAPAuthError:
        raise
    except IMAPConnectionError:
        raise
    except Exception as e:
        # If exception occurred after connection but not auth, treat as connection error unless clearly auth
        raise IMAPConnectionError(str(e)) from e
    finally:
        if conn:
            try:
                conn.logout()
            except Exception:
                try:
                    conn.shutdown()
                except Exception:
                    pass

class IMAPConnection:
    """
    Per-user isolated IMAP connection with proper cleanup.
    Usage:
        with get_mail_connection(request) as conn:
            conn.select(...)
    """
    def __init__(self, email: str, password: str):
        self.email = email
        self.password = password
        self.conn = None

    def __enter__(self):
        self.conn = _create_connection()
        try:
            typ, data = self.conn.login(self.email, self.password)
            if typ != "OK":
                raise IMAPAuthError("IMAP login failed")
        except imaplib.IMAP4.error as e:
            raise IMAPAuthError("IMAP authentication failed") from e
        return self.conn

    def __exit__(self, exc_type, exc_val, exc_tb):
        if self.conn:
            try:
                self.conn.logout()
            except Exception:
                try:
                    self.conn.shutdown()
                except Exception:
                    pass
        return False

def get_credentials_from_request(request):
    """Extract and decrypt credentials from session. Raises IMAPAuthError if missing."""
    from apps.accounts.crypto import decrypt_password
    token = request.session.get("mail_creds")
    email = request.session.get("mail_email")
    if not token or not email:
        raise IMAPAuthError("Not authenticated - missing credentials")
    try:
        password = decrypt_password(token)
    except Exception:
        raise IMAPAuthError("Invalid session credentials")
    return email, password

@contextmanager
def mail_connection(request):
    email, password = get_credentials_from_request(request)
    with IMAPConnection(email, password) as conn:
        yield conn
