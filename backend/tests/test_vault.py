import pytest

from apps.credentials import vault


@pytest.fixture(autouse=True)
def _reset_fernet_cache():
    # _fernet là cache module-level -> phải xoá trước/sau mỗi test để test đổi
    # DEBUG/VAULT_KEY không bị dính cache từ test chạy trước (thứ tự bất kỳ).
    vault._fernet = None
    yield
    vault._fernet = None


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


def test_fallback_dev_key_allowed_when_flag_on(settings):
    settings.RYANDEPLOY = {**settings.RYANDEPLOY, "VAULT_KEY": None, "VAULT_DEV_FALLBACK": True}
    assert vault.encrypt("x")  # không raise — hành vi dev/test hiện tại không đổi


def test_fallback_dev_key_rejected_when_flag_off(settings):
    # Mô phỏng 1 settings module không bật cờ VAULT_DEV_FALLBACK (VD staging thiếu sót)
    # dù DEBUG có thể vẫn True — cờ riêng mới là tín hiệu quyết định, không phải DEBUG.
    settings.RYANDEPLOY = {**settings.RYANDEPLOY, "VAULT_KEY": None, "VAULT_DEV_FALLBACK": False}
    with pytest.raises(RuntimeError, match="VAULT_KEY"):
        vault.encrypt("x")
