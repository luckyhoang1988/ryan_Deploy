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


class Deployment(TimeStampedModel):
    """Một chiến dịch đẩy 1 PackageVersion tới nhiều máy."""

    name = models.CharField(max_length=255)
    package_version = models.ForeignKey(
        "packages.PackageVersion", on_delete=models.PROTECT, related_name="deployments"
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
