from django.conf import settings
from django.db import models

from apps.core.models import TimeStampedModel


class DeploymentStatus(models.TextChoices):
    DRAFT = "draft", "Nháp"
    SCHEDULED = "scheduled", "Đã lên lịch"
    RUNNING = "running", "Đang chạy"
    COMPLETED = "completed", "Hoàn thành"
    COMPLETED_WITH_ERRORS = "completed_errors", "Hoàn thành (có lỗi)"
    FAILED = "failed", "Thất bại"
    CANCELLED = "cancelled", "Đã hủy"


class DeploymentAction(models.TextChoices):
    INSTALL = "install", "Cài đặt"
    UNINSTALL = "uninstall", "Gỡ cài đặt"
    REBOOT = "reboot", "Khởi động lại"
    SHUTDOWN = "shutdown", "Tắt máy"
    INVENTORY = "inventory", "Quét phần mềm (inventory)"


# Action cần một PackageVersion (installer/command); còn lại chạy payload-less/script.
PACKAGE_ACTIONS = frozenset({DeploymentAction.INSTALL, DeploymentAction.UNINSTALL})


class Deployment(TimeStampedModel):
    """Một chiến dịch chạy 1 tác vụ (cài/gỡ/reboot/shutdown/inventory) trên nhiều máy."""

    name = models.CharField(max_length=255)
    # install/uninstall cần package_version; reboot/shutdown/inventory để trống.
    action = models.CharField(
        max_length=16, choices=DeploymentAction.choices, default=DeploymentAction.INSTALL, db_index=True
    )
    package_version = models.ForeignKey(
        "packages.PackageVersion",
        on_delete=models.PROTECT,
        related_name="deployments",
        null=True,
        blank=True,
    )
    credential = models.ForeignKey(
        "credentials.DeployCredential", on_delete=models.PROTECT, related_name="deployments"
    )

    target_machines = models.ManyToManyField("machines.Machine", related_name="deployments")

    status = models.CharField(
        max_length=24, choices=DeploymentStatus.choices, default=DeploymentStatus.DRAFT, db_index=True
    )

    # Lịch chạy — null = chạy ngay khi trigger
    scheduled_at = models.DateTimeField(null=True, blank=True)

    # Điều kiện targeting (Phase 3): vd {"exclude_if_software": "Google Chrome", "min_version": "120"}.
    # null = chạy trên toàn bộ target_machines.
    targeting_rule = models.JSONField(null=True, blank=True)

    # Điều phối
    max_concurrency = models.PositiveIntegerField(default=15)
    retry_limit = models.PositiveIntegerField(default=1)

    started_at = models.DateTimeField(null=True, blank=True)
    finished_at = models.DateTimeField(null=True, blank=True)

    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL
    )

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.name} ({self.get_status_display()})"

    # --- Bộ đếm trạng thái job (tính từ jobs liên quan) ---
    @property
    def total_count(self):
        return self.jobs.count()

    @property
    def success_count(self):
        # Bao gồm cả "success_reboot" (exit 3010: cài xong, cần reboot) — nhất quán
        # với dashboard core/views.py và logic finalize_deployment.
        return self.jobs.filter(status__in=["success", "success_reboot"]).count()

    @property
    def failed_count(self):
        return self.jobs.filter(status="failed").count()

    @property
    def pending_count(self):
        return self.jobs.filter(status__in=["pending", "queued", "running"]).count()
