"""
Vá MD4 cho ldap3 NTLM bind.

OpenSSL 3 (Debian bookworm trong image python:3.12-slim) chuyển MD4 sang
legacy provider không nạp mặc định → `hashlib.new('md4')` báo
"unsupported hash type MD4". ldap3 cần MD4 để tính NT hash khi bind NTLM vào AD.

Định tuyến 'md4' sang Cryptodome.Hash.MD4 (pycryptodomex — đã có sẵn theo
impacket) thay vì tự cài đặt lại thuật toán. Chỉ vá khi OpenSSL thật sự thiếu MD4;
idempotent (gọi nhiều lần vô hại).
"""
from __future__ import annotations

import hashlib


def _openssl_has_md4() -> bool:
    try:
        hashlib.new("md4")
        return True
    except (ValueError, TypeError):
        return False


def install() -> bool:
    """
    Bảo đảm hashlib.new('md4') dùng được. Trả True nếu MD4 khả dụng sau khi gọi.
    """
    if _openssl_has_md4():
        return True

    try:
        from Cryptodome.Hash import MD4
    except ImportError:
        return False  # không vá được — để lỗi gốc nổi lên rõ ràng

    _orig_new = hashlib.new

    def _patched_new(name, data=b"", **kwargs):
        if isinstance(name, str) and name.lower() == "md4":
            h = MD4.new()
            if data:
                h.update(data)
            return h
        return _orig_new(name, data, **kwargs)

    hashlib.new = _patched_new
    return True
