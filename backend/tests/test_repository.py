import io

import pytest
from rest_framework.serializers import ValidationError

from apps.packages import repository
from apps.packages.serializers import PackageVersionSerializer


class _FakeUpload:
    def __init__(self, size):
        self.size = size


def test_installer_size_over_limit_rejected(settings):
    settings.PYDEPLOY = {**settings.PYDEPLOY, "MAX_INSTALLER_MB": 1}
    s = PackageVersionSerializer()
    with pytest.raises(ValidationError):
        s.validate_installer_file(_FakeUpload(2 * 1024 * 1024))  # 2MB > 1MB


def test_installer_size_within_limit_ok(settings):
    settings.PYDEPLOY = {**settings.PYDEPLOY, "MAX_INSTALLER_MB": 10}
    s = PackageVersionSerializer()
    upload = _FakeUpload(1 * 1024 * 1024)  # 1MB < 10MB
    assert s.validate_installer_file(upload) is upload
    assert s.validate_installer_file(None) is None  # update không đổi file → bỏ qua


def test_detect_installer_type():
    assert repository.detect_installer_type("Setup.MSI") == "msi"
    assert repository.detect_installer_type("app.exe") == "exe"
    assert repository.detect_installer_type("KB123.msu") == "msu"
    assert repository.detect_installer_type("patch.MSP") == "msp"
    assert repository.detect_installer_type("noext") == "exe"  # mặc định


def test_default_install_command():
    assert "msiexec" in repository.default_install_command("msi")
    assert "wusa" in repository.default_install_command("msu")
    assert "{file}" in repository.default_install_command("exe")


def test_compute_sha256_known_value():
    digest = repository.compute_sha256(io.BytesIO(b"hello"))
    assert digest == "2cf24dba5fb0a30e26e83b2ac5b9e29e1b161e5c1fa7425e73043362938b9824"


def test_compute_sha256_path(tmp_path):
    p = tmp_path / "f.bin"
    p.write_bytes(b"hello")
    assert repository.compute_sha256_path(str(p)) == (
        "2cf24dba5fb0a30e26e83b2ac5b9e29e1b161e5c1fa7425e73043362938b9824"
    )


class _FakeFile:
    def __init__(self, path):
        self.path = path


class _FakePV:
    def __init__(self, path, sha256):
        self.installer_file = _FakeFile(path)
        self.sha256 = sha256


def test_verify_integrity_match(tmp_path):
    p = tmp_path / "inst.bin"
    p.write_bytes(b"hello")
    good = "2cf24dba5fb0a30e26e83b2ac5b9e29e1b161e5c1fa7425e73043362938b9824"
    ok, actual = repository.verify_integrity(_FakePV(str(p), good))
    assert ok and actual == good


def test_verify_integrity_tampered(tmp_path):
    p = tmp_path / "inst.bin"
    p.write_bytes(b"TAMPERED")
    ok, actual = repository.verify_integrity(_FakePV(str(p), "0" * 64))
    assert not ok


def test_verify_integrity_no_hash_skips(tmp_path):
    p = tmp_path / "inst.bin"
    p.write_bytes(b"whatever")
    ok, _ = repository.verify_integrity(_FakePV(str(p), ""))
    assert ok  # không có hash lưu -> bỏ qua kiểm tra
