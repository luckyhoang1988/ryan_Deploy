from django.conf import settings
from django.db import models
from django.utils.functional import cached_property

from apps.core.models import TimeStampedModel

# to_attr dùng chung khi cần prefetch "bản mới nhất đã duyệt" cho nhiều Package cùng lúc
# (list view / compute_updates) — tránh N+1 do latest_version tự query mỗi package.
# Dùng: Prefetch("versions", queryset=PackageVersion.objects.filter(approved=True)
#                 .order_by("-created_at"), to_attr=APPROVED_VERSIONS_ATTR)
APPROVED_VERSIONS_ATTR = "_approved_versions_prefetched"

# Tên 3 thư mục gốc mặc định của cây Package Library (mirror PDQ Deploy), seed bởi
# migration 0005 và dùng lại bởi catalog_seed.py khi gán folder cho package mới.
DEFAULT_FOLDER_NAME = "Packages"


class InstallerType(models.TextChoices):
    MSI = "msi", "Windows Installer (.msi)"
    EXE = "exe", "Executable (.exe)"
    MSU = "msu", "Windows Update (.msu)"
    MSP = "msp", "Patch (.msp)"
    MSIX = "msix", "MSIX/AppX (.msix/.appx)"
    ZIP = "zip", "Archive nhiều file (.zip, tự giải nén)"


class AutoDownloadPolicy(models.TextChoices):
    """Chính sách tự tải & duyệt version mới từ download_url (mirror PDQ Auto Download)."""

    MANUAL = "manual", "Thủ công (admin duyệt)"
    IMMEDIATE = "immediate", "Duyệt ngay khi tải"
    AUTOMATIC = "automatic", "Tự duyệt sau N ngày"


class VersionSource(models.TextChoices):
    UPLOAD = "upload", "Upload thủ công"
    URL = "url", "Tải từ URL"


def installer_upload_path(instance, filename):
    """Đường lưu file trong repository: repository/<package_slug>/<version>/<filename>."""
    pkg = instance.package
    return f"repository/{pkg.id}_{pkg.name}/{instance.version}/{filename}"


class PackageFolder(TimeStampedModel):
    """Thư mục cây điều hướng Package Library (mirror PDQ Deploy: Packages/Custom
    Packages/Remove Updates...). Lồng nhau qua `parent` (adjacency-list, đủ dùng cho
    độ sâu nông của cây này — không cần MPTT/treebeard)."""

    name = models.CharField(max_length=255)
    parent = models.ForeignKey(
        "self", null=True, blank=True, on_delete=models.CASCADE, related_name="children"
    )

    class Meta:
        ordering = ["name"]
        unique_together = ("parent", "name")

    def __str__(self):
        return self.name


class Package(TimeStampedModel):
    """Một phần mềm cần triển khai (VD Microsoft Office, 7-Zip)."""

    name = models.CharField(max_length=255, unique=True, db_index=True)
    vendor = models.CharField(max_length=255, blank=True)
    description = models.TextField(blank=True)
    folder = models.ForeignKey(
        PackageFolder, null=True, blank=True, on_delete=models.SET_NULL, related_name="packages"
    )

    # System requirements (dùng để kiểm tra điều kiện cài đặt)
    min_os = models.CharField(max_length=128, blank=True)
    min_ram_gb = models.PositiveIntegerField(default=0)
    min_disk_gb = models.PositiveIntegerField(default=0)

    # License tracking
    total_licenses = models.PositiveIntegerField(default=0)
    used_licenses = models.PositiveIntegerField(default=0)

    # --- Catalog / Auto Download (lấy cảm hứng PDQ Deploy) ---
    # Nguồn evergreen: URL luôn trả bản mới nhất của phần mềm (vd link vendor). Để trống =
    # không tự tải, chỉ upload thủ công.
    download_url = models.URLField(blank=True, max_length=1024)
    auto_download = models.CharField(
        max_length=16, choices=AutoDownloadPolicy.choices, default=AutoDownloadPolicy.MANUAL
    )
    # Số ngày chờ trước khi tự duyệt version tải về (chỉ dùng khi auto_download=automatic).
    auto_approve_after_days = models.PositiveIntegerField(default=7)
    # Chuỗi con DisplayName để khớp InstalledSoftware khi dò cập nhật. Trống = suy từ
    # verify_name của version mới nhất, rồi tới name.
    inventory_name = models.CharField(
        max_length=255, blank=True,
        help_text="Tên phần mềm trong registry để dò máy lỗi thời (vd 'Google Chrome').",
    )

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return self.name

    @property
    def available_licenses(self):
        return max(self.total_licenses - self.used_licenses, 0)

    @cached_property
    def latest_version(self):
        """
        Version mới nhất đã DUYỆT. None nếu chưa có.

        cached_property: tránh query lặp lại trên CÙNG instance (vd match_name gọi lại).
        Nếu queryset đã prefetch qua APPROVED_VERSIONS_ATTR (xem module docstring), dùng
        luôn kết quả đó thay vì query mới — tránh N+1 khi liệt kê nhiều Package.
        """
        prefetched = getattr(self, APPROVED_VERSIONS_ATTR, None)
        if prefetched is not None:
            return prefetched[0] if prefetched else None
        return self.versions.filter(approved=True).first()

    @property
    def match_name(self) -> str:
        """Chuỗi khớp InstalledSoftware: inventory_name > verify_name của latest > name."""
        if self.inventory_name:
            return self.inventory_name
        latest = self.latest_version
        if latest and latest.verify_name:
            return latest.verify_name
        return self.name


class PackageVersion(TimeStampedModel):
    """Một phiên bản installer cụ thể của Package."""

    package = models.ForeignKey(Package, on_delete=models.CASCADE, related_name="versions")
    version = models.CharField(max_length=64)

    installer_file = models.FileField(upload_to=installer_upload_path)
    installer_type = models.CharField(max_length=8, choices=InstallerType.choices)

    # Lệnh silent-install thực thi trên máy đích (Phase 2 tự gợi ý theo loại installer)
    install_command = models.TextField(
        blank=True,
        help_text="Lệnh cài đặt silent. Dùng {file} làm placeholder cho đường dẫn installer trên máy đích.",
    )
    uninstall_command = models.TextField(blank=True)

    # Hậu kiểm cài đặt: sau khi installer báo thành công, kiểm registry Uninstall xem có
    # DisplayName chứa chuỗi này không (chống "false success" — installer trả 0 nhưng
    # không cài gì). Để TRỐNG = bỏ qua hậu kiểm. So khớp chuỗi con, không phân biệt hoa/thường.
    verify_name = models.CharField(
        max_length=255,
        blank=True,
        help_text="Tên phần mềm để hậu kiểm sau cài (vd 'Firefox'). Trống = không kiểm.",
    )

    # Toàn vẹn file
    sha256 = models.CharField(max_length=64, blank=True, db_index=True)
    file_size = models.BigIntegerField(default=0)

    # Mã exit code coi là thành công (0 và 3010 = cần reboot mặc định)
    success_exit_codes = models.JSONField(default=list, blank=True)

    # --- Catalog provenance & duyệt (lấy cảm hứng PDQ Deploy) ---
    # Nguồn gốc version: upload thủ công hay tải từ URL. URL đã tải (cho Download History).
    source = models.CharField(
        max_length=8, choices=VersionSource.choices, default=VersionSource.UPLOAD
    )
    download_url = models.URLField(blank=True, max_length=1024)
    # approved=True mới được coi là "latest" cho dò cập nhật & deploy 1 chạm. Mặc định True
    # để version upload thủ công (và dữ liệu cũ khi migrate) dùng được ngay; version tải tự
    # động sẽ được duyệt theo policy của Package.
    approved = models.BooleanField(default=True)
    approved_at = models.DateTimeField(null=True, blank=True)

    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL
    )

    class Meta:
        ordering = ["-created_at"]
        unique_together = ("package", "version")

    def __str__(self):
        return f"{self.package.name} {self.version}"


class PackageDownload(TimeStampedModel):
    """Nhật ký một lần tải installer từ URL (Download History kiểu PDQ Deploy)."""

    class Status(models.TextChoices):
        DOWNLOADING = "downloading", "Đang tải"
        SUCCESS = "success", "Thành công"
        UNCHANGED = "unchanged", "Không đổi (đã có)"
        FAILED = "failed", "Thất bại"

    package = models.ForeignKey(Package, on_delete=models.CASCADE, related_name="downloads")
    url = models.URLField(max_length=1024)
    version_str = models.CharField(max_length=64, blank=True)
    status = models.CharField(
        max_length=16, choices=Status.choices, default=Status.DOWNLOADING, db_index=True
    )
    # Version tạo ra khi thành công; SET_NULL để giữ lịch sử cả khi version bị xóa sau này.
    package_version = models.ForeignKey(
        PackageVersion, null=True, blank=True, on_delete=models.SET_NULL, related_name="downloads"
    )
    sha256 = models.CharField(max_length=64, blank=True)
    file_size = models.BigIntegerField(default=0)
    error = models.TextField(blank=True)
    requested_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL
    )

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.package.name} ← {self.url} [{self.status}]"
