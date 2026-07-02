import pytest

from apps.credentials import vault


def test_encrypt_decrypt_roundtrip():
    token = vault.encrypt("S3cr3t!Pass")
    assert token != "S3cr3t!Pass"
    assert vault.decrypt(token) == "S3cr3t!Pass"


def test_encrypt_empty():
    assert vault.decrypt(vault.encrypt("")) == ""
    assert vault.decrypt("") == ""


def test_decrypt_invalid_raises():
    with pytest.raises(Exception):
        vault.decrypt("not-a-valid-fernet-token")


def test_ciphertext_differs_each_time():
    # Fernet dùng IV ngẫu nhiên -> 2 lần mã hóa cùng plaintext ra khác nhau
    assert vault.encrypt("same") != vault.encrypt("same")
