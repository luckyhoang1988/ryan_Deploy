from django.conf import settings
from django.db import models

from apps.core.models import TimeStampedModel


class InstallerType(models.TextChoices):
    MSI = "msi", "Windows Installer (.msi)"
    EXE = "exe", "Executable (.exe)"
    MSU = "msu", "Windows Update (.msu)"
    MSP = "msp", "Patch (.msp)"
    MSIX = "msix", "MSIX/AppX (.msix/.appx)"


def installer_upload_path(instance, filename):
    """Đường lưu file trong repository: repository/<package_slug>/<version>/<filename>."""
    pkg = instance.package
    return f"repository/{pkg.id}_{pkg.name}/{instance.version}/{filename}"


class Package(TimeStampedModel):
    """Một phần mềm cần triển khai (VD Microsoft Office, 7-Zip)."""

    name = models.CharField(max_length=255, unique=True, db_index=True)
    vendor = models.CharField(max_length=255, blank=True)
    description = models.TextField(blank=True)

    # System requirements (dùng để kiểm tra điều kiện cài đặt)
    min_os = models.CharField(max_length=128, blank=True)
    min_ram_gb = models.PositiveIntegerField(default=0)
    min_disk_gb = models.PositiveIntegerField(default=0)

    # License tracking
    total_licenses = models.PositiveIntegerField(default=0)
    used_licenses = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return self.name

    @property
    def available_licenses(self):
        return max(self.total_licenses - self.used_licenses, 0)


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

    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL
    )

    class Meta:
        ordering = ["-created_at"]
        unique_together = ("package", "version")

    def __str__(self):
        return f"{self.package.name} {self.version}"
