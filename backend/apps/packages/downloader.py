"""
Downloader — tải installer từ URL ngoài vào Package Repository (mirror "Download
Selected" của PDQ Deploy).

Dùng `urllib.request` (stdlib) — project không có `requests`, và pin cryptography==42
(do impacket) khiến việc thêm dep là rủi ro. Chỉ admin được gọi (SSRF surface): validate
scheme http/https, trần dung lượng, timeout.
"""
import http.client
import ipaddress
import logging
import os
import socket
import tempfile
from urllib.parse import unquote, urlparse
from urllib.request import HTTPHandler, HTTPSHandler, Request, build_opener

from django.conf import settings
from django.core.files import File
from django.utils import timezone

from . import repository
from .models import (
    AutoDownloadPolicy,
    InstallerType,
    PackageDownload,
    PackageVersion,
    VersionSource,
)

logger = logging.getLogger("apps.packages")

_CHUNK = 65536
_USER_AGENT = "RyanDeploy/1.0 (+package-catalog)"


class DownloadError(Exception):
    """Lỗi tải/khởi tạo version — thông điệp an toàn để trả về client."""


def _resolve_validated_ip(hostname: str) -> str:
    """
    Chặn SSRF: resolve hostname, từ chối nếu BẤT KỲ IP nào rơi vào dải nội bộ/đặc biệt
    (loopback, link-local — gồm 169.254.169.254 cloud metadata, RFC1918 private,
    reserved, multicast). Admin-only nhưng vẫn là bề mặt SSRF nên phải chặn cứng.

    Trả về 1 IP hợp lệ (bản ghi đầu tiên) để PIN kết nối vào đúng IP này — xem
    _PinnedHTTPConnection/_PinnedHTTPSConnection. Nếu chỉ validate rồi để urllib tự resolve
    lại lúc connect thật (như bản cũ), sẽ có cửa sổ TOCTOU DNS-rebinding: DNS trả IP công
    khai lúc check, đổi sang IP nội bộ lúc connect thật (attacker kiểm soát DNS của domain
    họ đưa cho admin tải).
    """
    if not hostname:
        raise DownloadError("URL thiếu hostname.")
    try:
        infos = socket.getaddrinfo(hostname, None)
    except socket.gaierror as exc:
        raise DownloadError(f"Không resolve được host '{hostname}': {exc}") from exc
    for _family, _type, _proto, _canon, sockaddr in infos:
        ip = ipaddress.ip_address(sockaddr[0])
        # Unwrap IPv4-mapped IPv6 (::ffff:a.b.c.d) về dạng IPv4 trước khi kiểm tra — phòng
        # thủ chiều sâu, không phụ thuộc hoàn toàn vào việc stdlib ipaddress của MỌI phiên
        # bản Python đều tự phân loại đúng is_private/is_loopback cho dạng địa chỉ này.
        if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped:
            ip = ip.ipv4_mapped
        if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved or ip.is_multicast:
            raise DownloadError(
                f"URL trỏ tới địa chỉ nội bộ/đặc biệt ({ip}) — không cho phép (chống SSRF)."
            )
    return infos[0][4][0]


def _ensure_public_host(hostname: str) -> None:
    """Kiểm tra sớm (fail-fast trước khi tạo bản ghi PackageDownload trong fetch()) — validate
    thật sự (kèm PIN chống TOCTOU) diễn ra lại ngay trước lúc connect, xem _SafeHTTPHandler/
    _SafeHTTPSHandler bên dưới."""
    _resolve_validated_ip(hostname)


class _PinnedHTTPConnection(http.client.HTTPConnection):
    """Kết nối thẳng tới IP đã validate (_pinned_ip) — không tự resolve lại hostname lúc
    connect, đóng cửa sổ TOCTOU DNS-rebinding giữa lúc validate và lúc connect thật."""

    _pinned_ip = ""

    def connect(self):
        self.sock = socket.create_connection(
            (self._pinned_ip, self.port), self.timeout, self.source_address
        )
        if self._tunnel_host:
            self._tunnel()


class _PinnedHTTPSConnection(http.client.HTTPSConnection):
    """Như trên, cho HTTPS — TCP connect() dùng IP đã pin, còn SNI/xác thực chứng chỉ TLS vẫn
    dùng đúng hostname gốc (self.host) nên không ảnh hưởng tính đúng đắn của việc xác thực TLS."""

    _pinned_ip = ""

    def connect(self):
        sock = socket.create_connection(
            (self._pinned_ip, self.port), self.timeout, self.source_address
        )
        if self._tunnel_host:
            self.sock = sock
            self._tunnel()
            server_hostname = self._tunnel_host
        else:
            server_hostname = self.host
        self.sock = self._context.wrap_socket(sock, server_hostname=server_hostname)


class _SafeHTTPHandler(HTTPHandler):
    """Validate + pin IP ngay trước khi mở TỪNG kết nối — kể cả sau mỗi lần redirect
    (OpenerDirector gọi lại http_open/https_open cho URL đích mới mỗi lần redirect), nên
    redirect sang IP nội bộ cũng bị chặn mà không cần handler redirect riêng."""

    def http_open(self, req):
        pinned_ip = _resolve_validated_ip(urlparse(req.full_url).hostname)

        def factory(host, **kwargs):
            conn = _PinnedHTTPConnection(host, **kwargs)
            conn._pinned_ip = pinned_ip
            return conn

        return self.do_open(factory, req)


class _SafeHTTPSHandler(HTTPSHandler):
    def https_open(self, req):
        pinned_ip = _resolve_validated_ip(urlparse(req.full_url).hostname)

        def factory(host, **kwargs):
            conn = _PinnedHTTPSConnection(host, **kwargs)
            conn._pinned_ip = pinned_ip
            return conn

        # context: dùng self._context (đã build sẵn ở HTTPSHandler.__init__, gồm cả
        # check_hostname/verify_mode) — không tự lấy self._check_hostname vì thuộc tính này
        # không tồn tại xuyên suốt mọi phiên bản Python (Python 3.14 gộp hẳn vào context,
        # bỏ attribute riêng — xác nhận bằng chạy thật, không đoán theo trí nhớ API cũ).
        return self.do_open(factory, req, context=self._context)


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
    opener = build_opener(_SafeHTTPHandler(), _SafeHTTPSHandler())
    fd, temp_path = tempfile.mkstemp(prefix="ryandeploy_dl_")
    written = 0
    try:
        # noqa: S310 — scheme đã validate ở fetch(); host (kể cả sau redirect) được
        # _SafeHTTPHandler/_SafeHTTPSHandler validate + PIN đúng IP ngay trước khi connect,
        # không còn khoảng hở TOCTOU DNS-rebinding giữa lúc check và lúc connect thật.
        with opener.open(req, timeout=timeout) as resp:
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
    parsed = urlparse(url)
    scheme = parsed.scheme.lower()
    if scheme not in ("http", "https"):
        raise DownloadError("URL phải dùng scheme http hoặc https.")
    _ensure_public_host(parsed.hostname)

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
        if itype == InstallerType.ZIP:
            # Cùng lỗ hổng zip-slip/zip-bomb như upload thủ công (serializers.py), nhưng
            # đường tải-từ-URL này KHÔNG đi qua PackageVersionSerializer nên phải tự kiểm.
            max_mb = cfg.get("MAX_INSTALLER_MB", 2048)
            with open(temp_path, "rb") as fh:
                try:
                    repository.validate_zip_archive(fh, max_mb * 10 * 1024 * 1024)
                except ValueError as e:
                    raise DownloadError(f"Archive .zip không an toàn: {e}") from e

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
