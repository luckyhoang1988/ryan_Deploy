import io
import zipfile

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from rest_framework.serializers import ValidationError

from apps.packages import repository
from apps.packages.models import Package
from apps.packages.serializers import PackageVersionSerializer


class _FakeUpload:
    def __init__(self, size):
        self.size = size


def test_installer_size_over_limit_rejected(settings):
    settings.RYANDEPLOY = {**settings.RYANDEPLOY, "MAX_INSTALLER_MB": 1}
    s = PackageVersionSerializer()
    with pytest.raises(ValidationError):
        s.validate_installer_file(_FakeUpload(2 * 1024 * 1024))  # 2MB > 1MB


def test_installer_size_within_limit_ok(settings):
    settings.RYANDEPLOY = {**settings.RYANDEPLOY, "MAX_INSTALLER_MB": 10}
    s = PackageVersionSerializer()
    upload = _FakeUpload(1 * 1024 * 1024)  # 1MB < 10MB
    assert s.validate_installer_file(upload) is upload
    assert s.validate_installer_file(None) is None  # update không đổi file → bỏ qua


def test_detect_installer_type():
    assert repository.detect_installer_type("Setup.MSI") == "msi"
    assert repository.detect_installer_type("app.exe") == "exe"
    assert repository.detect_installer_type("KB123.msu") == "msu"
    assert repository.detect_installer_type("patch.MSP") == "msp"
    assert repository.detect_installer_type("App.msix") == "msix"
    assert repository.detect_installer_type("App.MSIXBUNDLE") == "msix"
    assert repository.detect_installer_type("App.appx") == "msix"
    assert repository.detect_installer_type("noext") == "exe"  # mặc định
    assert repository.detect_installer_type("Office2016.zip") == "zip"


def test_upload_without_installer_type_autodetects(db, settings, tmp_path):
    # Form upload không gửi installer_type → serializer phải qua is_valid() (required=False)
    # và create() tự suy ra loại từ đuôi file. Regression cho lỗi "installer_type required".
    settings.MEDIA_ROOT = str(tmp_path)
    pkg = Package.objects.create(name="Firefox")
    upload = SimpleUploadedFile("Firefox Installer.exe", b"MZ-fake-binary")
    s = PackageVersionSerializer(data={"package": pkg.id, "version": "1", "installer_file": upload})
    assert s.is_valid(), s.errors
    pv = s.save()
    assert pv.installer_type == "exe"
    assert "{file}" in pv.install_command


def test_default_install_command():
    assert "msiexec" in repository.default_install_command("msi")
    assert "wusa" in repository.default_install_command("msu")
    assert "{file}" in repository.default_install_command("exe")
    msix = repository.default_install_command("msix")
    assert "Add-AppxProvisionedPackage" in msix and "{file}" in msix
    assert "{dir}" in repository.default_install_command("zip")


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


def _make_zip(entries: dict[str, bytes], compress=zipfile.ZIP_DEFLATED) -> io.BytesIO:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", compress) as zf:
        for name, data in entries.items():
            zf.writestr(name, data)
    buf.seek(0)
    return buf


def test_validate_zip_archive_accepts_normal_zip():
    z = _make_zip({"setup.exe": b"MZ-fake", "configuration.xml": b"<config/>"})
    repository.validate_zip_archive(z, max_total_uncompressed_bytes=10 * 1024 * 1024)  # không raise


def test_validate_zip_archive_rejects_path_traversal():
    z = _make_zip({"../../evil.exe": b"payload"})
    with pytest.raises(ValueError, match="đường dẫn không an toàn"):
        repository.validate_zip_archive(z, max_total_uncompressed_bytes=10 * 1024 * 1024)


def test_validate_zip_archive_rejects_absolute_path():
    z = _make_zip({"C:\\Windows\\System32\\evil.dll": b"payload"})
    with pytest.raises(ValueError, match="đường dẫn không an toàn"):
        repository.validate_zip_archive(z, max_total_uncompressed_bytes=10 * 1024 * 1024)


def test_validate_zip_archive_rejects_zip_bomb_ratio():
    # 50MB toàn số 0 nén cực tốt -> tỉ lệ nén vượt xa ngưỡng cho phép.
    z = _make_zip({"bomb.bin": b"\x00" * (50 * 1024 * 1024)})
    with pytest.raises(ValueError, match="zip bomb"):
        repository.validate_zip_archive(z, max_total_uncompressed_bytes=1024 * 1024 * 1024)


def test_validate_zip_archive_rejects_total_size_over_cap():
    z = _make_zip({"a.bin": b"A" * 2000, "b.bin": b"B" * 2000}, compress=zipfile.ZIP_STORED)
    with pytest.raises(ValueError, match="Tổng dung lượng"):
        repository.validate_zip_archive(z, max_total_uncompressed_bytes=1000)


def test_validate_zip_archive_rejects_bad_zip():
    with pytest.raises(ValueError, match="không phải archive"):
        repository.validate_zip_archive(io.BytesIO(b"not a zip"), max_total_uncompressed_bytes=1024)


def test_serializer_rejects_malicious_zip_upload(db, settings, tmp_path):
    settings.MEDIA_ROOT = str(tmp_path)
    pkg = Package.objects.create(name="Office2016")
    evil = SimpleUploadedFile(
        "Office2016.zip", _make_zip({"../../evil.exe": b"payload"}).getvalue()
    )
    s = PackageVersionSerializer(data={"package": pkg.id, "version": "1", "installer_file": evil})
    assert not s.is_valid()
    assert "installer_file" in s.errors
