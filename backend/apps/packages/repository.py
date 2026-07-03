"""
Package Repository service — xử lý installer khi upload:
- Tính checksum SHA-256
- Phát hiện loại installer (msi/exe/msu/msp)
- Gợi ý lệnh silent-install mặc định
"""
import hashlib

# Lệnh silent mặc định theo loại installer. {file} = đường dẫn installer trên máy đích.
DEFAULT_SILENT_COMMANDS = {
    "msi": 'msiexec /i "{file}" /qn /norestart',
    "msp": 'msiexec /p "{file}" /qn /norestart',
    "msu": 'wusa "{file}" /quiet /norestart',
    # MSIX/AppX: cài per-machine qua PowerShell. Cần package đã ký + cert tin cậy trên
    # máy đích (sideload). Nếu chưa tin cert, thêm bước import cert trước (xem docs).
    "msix": 'powershell -NoProfile -ExecutionPolicy Bypass -Command "Add-AppxProvisionedPackage -Online -PackagePath \'{file}\' -SkipLicense"',
    # EXE: không có chuẩn chung — mặc định để trống, admin nhập theo installer.
    # Gợi ý phổ biến trong comment cho UI:
    #   InnoSetup:     "{file}" /VERYSILENT /NORESTART
    #   NSIS:          "{file}" /S
    #   InstallShield: "{file}" /s /v"/qn"
    "exe": '"{file}" /S',
}

# Mã exit code coi là thành công theo mặc định (0 = OK, 3010 = OK cần reboot).
DEFAULT_SUCCESS_EXIT_CODES = [0, 3010]

_INSTALLER_EXTENSIONS = {
    ".msi": "msi",
    ".msp": "msp",
    ".msu": "msu",
    ".msixbundle": "msix",
    ".appxbundle": "msix",
    ".msix": "msix",
    ".appx": "msix",
    ".exe": "exe",
}


def detect_installer_type(filename: str) -> str:
    """Suy ra loại installer từ đuôi file. Mặc định 'exe'."""
    lower = filename.lower()
    for ext, itype in _INSTALLER_EXTENSIONS.items():
        if lower.endswith(ext):
            return itype
    return "exe"


def default_install_command(installer_type: str) -> str:
    return DEFAULT_SILENT_COMMANDS.get(installer_type, DEFAULT_SILENT_COMMANDS["exe"])


def compute_sha256(file_obj, chunk_size: int = 65536) -> str:
    """Tính SHA-256 của file (đọc theo chunk, không nạp toàn bộ vào RAM)."""
    sha = hashlib.sha256()
    file_obj.seek(0)
    for chunk in iter(lambda: file_obj.read(chunk_size), b""):
        if isinstance(chunk, str):
            chunk = chunk.encode("utf-8")
        sha.update(chunk)
    file_obj.seek(0)
    return sha.hexdigest()


def compute_sha256_path(path: str, chunk_size: int = 65536) -> str:
    """Tính SHA-256 của file trên đĩa theo đường dẫn."""
    sha = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(chunk_size), b""):
            sha.update(chunk)
    return sha.hexdigest()


def verify_integrity(package_version) -> tuple[bool, str]:
    """
    Xác minh installer chưa bị sửa đổi: hash file thực tế == sha256 đã lưu.
    Trả (ok, actual_hash). Nếu chưa có sha256 lưu -> coi như bỏ qua (ok=True).
    """
    expected = (package_version.sha256 or "").lower()
    if not expected:
        return True, ""
    actual = compute_sha256_path(package_version.installer_file.path).lower()
    return actual == expected, actual
