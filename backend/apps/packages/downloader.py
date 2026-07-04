"""
Downloader — tải installer từ URL ngoài vào Package Repository (mirror "Download
Selected" của PDQ Deploy).

Dùng `urllib.request` (stdlib) — project không có `requests`, và pin cryptography==42
(do impacket) khiến việc thêm dep là rủi ro. Chỉ admin được gọi (SSRF surface): validate
scheme http/https, trần dung lượng, timeout.
"""
import logging
import os
import tempfile
from urllib.parse import unquote, urlparse
from urllib.request import Request, urlopen

from django.conf import settings
from django.core.files import File
from django.utils import timezone

from . import repository
from .models import (
    AutoDownloadPolicy,
    PackageDownload,
    PackageVersion,
    VersionSource,
)

logger = logging.getLogger("apps.packages")

_CHUNK = 65536
_USER_AGENT = "RyanDeploy/1.0 (+package-catalog)"


class DownloadError(Exception):
    """Lỗi tải/khởi tạo version — thông điệp an toàn để trả về client."""


def _filename_from(url: str, content_disposition: str) -> str:
    """Suy tên file: ưu tiên Content-Disposition, fallback basename của URL path."""
    if content_disposition:
        # dạng: attachment; filename="app.msi"  hoặc filename*=UTF-8''app.msi
        for part in content_disposition.split(";"):
            part = part.strip()
            for key in ("filename*=", "filename="):
                if part.lower().startswith(key):
                    name = part[len(key):].strip().strip('"')
                    if "''" in name:  # filename*=UTF-8''app.msi
                        name = name.split("''", 1)[1]
                    name = os.path.basename(unquote(name))
                    if name:
                        return name
    path = urlparse(url).path
    name = os.path.basename(unquote(path))
    return name or "installer.bin"


def _stream_to_temp(url: str, max_bytes: int, timeout: int) -> tuple[str, str]:
    """Tải URL ra file tạm với trần dung lượng. Trả (temp_path, filename)."""
    req = Request(url, headers={"User-Agent": _USER_AGENT})
    fd, temp_path = tempfile.mkstemp(prefix="ryandeploy_dl_")
    written = 0
    try:
        with urlopen(req, timeout=timeout) as resp:  # noqa: S310 (scheme đã validate)
            filename = _filename_from(url, resp.headers.get("Content-Disposition", ""))
            with os.fdopen(fd, "wb") as out:
                while True:
                    chunk = resp.read(_CHUNK)
                    if not chunk:
                        break
                    written += len(chunk)
                    if written > max_bytes:
                        raise DownloadError(
                            f"File vượt trần {max_bytes // (1024 * 1024)} MB — hủy tải."
                        )
                    out.write(chunk)
    except DownloadError:
        _safe_unlink(temp_path)
        raise
    except Exception as exc:  # lỗi mạng/HTTP → gói lại thông điệp gọn
        _safe_unlink(temp_path)
        raise DownloadError(f"Tải thất bại: {exc}") from exc
    if written == 0:
        _safe_unlink(temp_path)
        raise DownloadError("File tải về rỗng (0 byte).")
    return temp_path, filename


def _safe_unlink(path: str):
    try:
        os.unlink(path)
    except OSError:
        pass


def _approved_on_fetch(package) -> bool:
    """Version tải về được duyệt ngay khi policy=IMMEDIATE; còn lại chờ (manual/automatic)."""
    return package.auto_download == AutoDownloadPolicy.IMMEDIATE


def fetch(package, url: str, version: str, requested_by=None) -> PackageDownload:
    """
    Tải installer từ `url` về repository và tạo PackageVersion mới cho `package`.

    - Dedup theo SHA-256: nếu trùng version đã có của package → status=unchanged, không tạo mới.
    - Trả về bản ghi PackageDownload (đã lưu) phản ánh kết quả.
    """
    scheme = urlparse(url).scheme.lower()
    if scheme not in ("http", "https"):
        raise DownloadError("URL phải dùng scheme http hoặc https.")

    version = (version or "").strip()
    if not version:
        raise DownloadError("Thiếu nhãn version cho bản tải về.")

    dl = PackageDownload.objects.create(
        package=package,
        url=url,
        version_str=version,
        status=PackageDownload.Status.DOWNLOADING,
        requested_by=requested_by if getattr(requested_by, "is_authenticated", False) else None,
    )

    cfg = settings.RYANDEPLOY
    max_bytes = cfg.get("MAX_INSTALLER_MB", 2048) * 1024 * 1024
    timeout = cfg.get("DOWNLOAD_TIMEOUT", 300)

    temp_path = None
    try:
        temp_path, filename = _stream_to_temp(url, max_bytes, timeout)
        sha256 = repository.compute_sha256_path(temp_path)
        file_size = os.path.getsize(temp_path)

        # Dedup: đã có version cùng nội dung? (cùng package)
        existing = package.versions.filter(sha256=sha256).first()
        if existing:
            dl.status = PackageDownload.Status.UNCHANGED
            dl.package_version = existing
            dl.sha256 = sha256
            dl.file_size = file_size
            dl.save(update_fields=["status", "package_version", "sha256", "file_size", "updated_at"])
            logger.info("Fetch %s: nội dung trùng version '%s', bỏ qua", package.name, existing.version)
            return dl

        # Trùng nhãn version nhưng khác nội dung → xung đột unique_together, báo rõ.
        if package.versions.filter(version=version).exists():
            raise DownloadError(
                f"Đã tồn tại version '{version}' với nội dung khác. Hãy chọn nhãn version khác."
            )

        itype = repository.detect_installer_type(filename)
        approved = _approved_on_fetch(package)
        pv = PackageVersion(
            package=package,
            version=version,
            installer_type=itype,
            install_command=repository.default_install_command(itype),
            success_exit_codes=list(repository.DEFAULT_SUCCESS_EXIT_CODES),
            sha256=sha256,
            file_size=file_size,
            source=VersionSource.URL,
            download_url=url,
            approved=approved,
            approved_at=timezone.now() if approved else None,
            created_by=dl.requested_by,
        )
        # installer_upload_path dùng pv.version → phải set trước khi save file.
        with open(temp_path, "rb") as fh:
            pv.installer_file.save(filename, File(fh), save=True)

        dl.status = PackageDownload.Status.SUCCESS
        dl.package_version = pv
        dl.sha256 = sha256
        dl.file_size = file_size
        dl.save(update_fields=["status", "package_version", "sha256", "file_size", "updated_at"])
        logger.info("Fetch %s: tạo version '%s' (%s byte)", package.name, version, file_size)
        return dl
    except DownloadError as exc:
        dl.status = PackageDownload.Status.FAILED
        dl.error = str(exc)
        dl.save(update_fields=["status", "error", "updated_at"])
        return dl
    except Exception as exc:  # lỗi bất ngờ (DB/IO) — vẫn ghi lại để hiển thị history
        logger.exception("Fetch %s lỗi ngoài dự kiến", package.name)
        dl.status = PackageDownload.Status.FAILED
        dl.error = f"Lỗi hệ thống: {exc}"
        dl.save(update_fields=["status", "error", "updated_at"])
        return dl
    finally:
        if temp_path:
            _safe_unlink(temp_path)
