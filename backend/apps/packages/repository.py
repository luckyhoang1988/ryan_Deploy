"""
Package Repository service — xử lý installer khi upload:
- Tính checksum SHA-256
- Phát hiện loại installer (msi/exe/msu/msp)
- Gợi ý lệnh silent-install mặc định
- Kiểm tra an toàn archive .zip (zip-slip/zip-bomb) trước khi cho phép đẩy tới máy đích
"""
import hashlib
import os
import zipfile

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
    # ZIP: giải nén sẵn vào {dir} trước khi lệnh chạy (xem PushExecutor._copy_payload).
    # Admin phải sửa lại đường dẫn/entry point thật bên trong archive, vd Office2016 ODT:
    #   "{dir}\setup.exe" /configure "{dir}\configuration.xml"
    "zip": '"{dir}\\setup.exe" /S',
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
    ".zip": "zip",
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


# Zip-bomb: tỉ lệ nén tối đa cho phép trên mỗi entry trước khi nghi ngờ (installer thật
# thường nén <=10:1 vì nội dung MSI/cab đã nén sẵn; zip bomb thường đạt tỉ lệ hàng nghìn:1).
_MAX_ZIP_RATIO = 100
# Số entry tối đa — chặn archive có hàng triệu entry rỗng (cũng là 1 dạng zip-bomb).
_MAX_ZIP_ENTRIES = 20000


def validate_zip_archive(file_obj, max_total_uncompressed_bytes: int) -> None:
    """
    Kiểm tra 1 archive .zip AN TOÀN trước khi cho phép lưu vào repository — archive này
    sẽ được PushExecutor giải nén bằng `tar.exe` chạy quyền SYSTEM trên MỌI máy đích của
    fleet, nên 1 file độc hại có thể ảnh hưởng hàng loạt máy nếu không chặn ở đây.

    Chặn 2 lớp:
    - zip-slip: entry có đường dẫn tuyệt đối/ổ đĩa/thoát ra ngoài thư mục giải nén (`..`).
    - zip-bomb: tỉ lệ nén bất thường trên 1 entry, hoặc tổng dung lượng giải nén vượt trần.

    Raise ValueError nếu archive không hợp lệ hoặc vi phạm 1 trong các điều kiện trên.
    Không làm thay đổi vị trí đọc của `file_obj` sau khi trả về (seek về 0).
    """
    file_obj.seek(0)
    try:
        with zipfile.ZipFile(file_obj) as zf:
            infos = zf.infolist()
            if len(infos) > _MAX_ZIP_ENTRIES:
                raise ValueError(
                    f"Archive có {len(infos)} entry, vượt giới hạn {_MAX_ZIP_ENTRIES}."
                )
            total_uncompressed = 0
            for info in infos:
                name = info.filename
                normalized = os.path.normpath(name)
                if os.path.isabs(normalized) or normalized.startswith("..") or ":" in normalized:
                    raise ValueError(f"Archive chứa đường dẫn không an toàn: '{name}'.")
                total_uncompressed += info.file_size
                if info.compress_size > 0 and info.file_size / info.compress_size > _MAX_ZIP_RATIO:
                    raise ValueError(
                        f"Entry '{name}' có tỉ lệ nén bất thường "
                        f"({info.file_size}/{info.compress_size}) — nghi zip bomb."
                    )
            if total_uncompressed > max_total_uncompressed_bytes:
                raise ValueError(
                    f"Tổng dung lượng giải nén ({total_uncompressed // (1024 * 1024)} MB) "
                    f"vượt trần {max_total_uncompressed_bytes // (1024 * 1024)} MB."
                )
    except zipfile.BadZipFile as e:
        raise ValueError(f"File không phải archive .zip hợp lệ: {e}") from e
    finally:
        file_obj.seek(0)


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
