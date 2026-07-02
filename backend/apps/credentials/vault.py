"""
Credential Vault — mã hóa/giải mã secret at-rest bằng Fernet (AES-128-CBC + HMAC).

Khóa lấy từ settings.PYDEPLOY['VAULT_KEY']. Ở production BẮT BUỘC đặt key thật
(prod.py sẽ raise nếu thiếu). Ở dev, nếu thiếu key sẽ derive tạm từ SECRET_KEY
để chạy được — KHÔNG dùng cách này ở production.
"""
import base64
import hashlib
import logging

from cryptography.fernet import Fernet, InvalidToken
from django.conf import settings

logger = logging.getLogger("apps.credentials")

_fernet: Fernet | None = None


def _derive_dev_key() -> bytes:
    """Derive Fernet key tạm từ SECRET_KEY cho môi trường dev."""
    digest = hashlib.sha256(settings.SECRET_KEY.encode()).digest()
    return base64.urlsafe_b64encode(digest)


def _get_fernet() -> Fernet:
    global _fernet
    if _fernet is not None:
        return _fernet

    key = settings.PYDEPLOY.get("VAULT_KEY")
    if key:
        key_bytes = key.encode() if isinstance(key, str) else key
    else:
        logger.warning(
            "PYDEPLOY_VAULT_KEY chưa đặt — dùng key derive tạm từ SECRET_KEY (chỉ hợp lệ cho dev)."
        )
        key_bytes = _derive_dev_key()

    _fernet = Fernet(key_bytes)
    return _fernet


def encrypt(plaintext: str) -> str:
    """Mã hóa chuỗi -> token (str) để lưu DB."""
    if plaintext is None:
        plaintext = ""
    token = _get_fernet().encrypt(plaintext.encode("utf-8"))
    return token.decode("ascii")


def decrypt(token: str) -> str:
    """Giải mã token -> plaintext. Trả "" nếu token rỗng."""
    if not token:
        return ""
    try:
        return _get_fernet().decrypt(token.encode("ascii")).decode("utf-8")
    except (InvalidToken, ValueError):
        logger.error("Không giải mã được credential — sai VAULT_KEY hoặc dữ liệu hỏng.")
        raise
