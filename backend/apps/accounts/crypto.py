import base64
import hashlib
from django.conf import settings
from cryptography.fernet import Fernet, InvalidToken

def _derive_key() -> bytes:
    # Derive Fernet key from SECRET_KEY (32 url-safe base64)
    digest = hashlib.sha256(settings.SECRET_KEY.encode()).digest()
    return base64.urlsafe_b64encode(digest)

_fernet = None

def get_fernet() -> Fernet:
    global _fernet
    if _fernet is None:
        _fernet = Fernet(_derive_key())
    return _fernet

def encrypt_password(plain: str) -> str:
    return get_fernet().encrypt(plain.encode()).decode()

def decrypt_password(token: str) -> str:
    try:
        return get_fernet().decrypt(token.encode()).decode()
    except InvalidToken:
        raise ValueError("Invalid credential token")
