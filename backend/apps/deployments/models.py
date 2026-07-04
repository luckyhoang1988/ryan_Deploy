from django.conf import settings
from django.db import models
from django.utils import timezone

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

# Action phá hoại cao (reboot/shutdown cả fleet) — chỉ admin được kích hoạt, dù kích hoạt
# thủ công (DeploymentViewSet.trigger) hay qua lịch lặp (DeploymentScheduleViewSet).
ADMIN_ONLY_ACTIONS = frozenset({DeploymentAction.REBOOT, DeploymentAction.SHUTDOWN})


class RecurrenceType(models.TextChoices):
    INTERVAL = "interval", "Lặp mỗi N phút"
    WEEKLY = "weekly", "Theo ngày trong tuần"


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
    # Không null khi Deployment này được sinh ra tự động bởi 1 lịch lặp (xem
    # DeploymentSchedule.spawn_deployment) — cho phép UI liệt kê lịch sử các lần chạy
    # của 1 lịch. SET_NULL khi xóa lịch: giữ nguyên lịch sử deployment đã chạy.
    schedule = models.ForeignKey(
        "DeploymentSchedule", null=True, blank=True, on_delete=models.SET_NULL, related_name="deployments"
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


class DeploymentSchedule(TimeStampedModel):
    """
    Lịch lặp lại (kiểu PDQ 'Repeating'/'Recurring') — một CẤU HÌNH mẫu, KHÔNG phải một lần
    chạy. Mỗi lần tới giờ, beat task `trigger_due_schedules` clone thành 1 `Deployment` MỚI
    (spawn_deployment) rồi launch — giữ đầy đủ lịch sử job/audit từng lần chạy, khác với
    `Deployment.scheduled_at` (chạy đúng 1 lần rồi thôi).
    """

    name = models.CharField(max_length=255)
    action = models.CharField(
        max_length=16, choices=DeploymentAction.choices, default=DeploymentAction.INSTALL
    )
    package_version = models.ForeignKey(
        "packages.PackageVersion",
        on_delete=models.PROTECT,
        related_name="deployment_schedules",
        null=True,
        blank=True,
    )
    credential = models.ForeignKey(
        "credentials.DeployCredential", on_delete=models.PROTECT, related_name="deployment_schedules"
    )
    target_machines = models.ManyToManyField("machines.Machine", related_name="deployment_schedules")
    targeting_rule = models.JSONField(null=True, blank=True)
    max_concurrency = models.PositiveIntegerField(default=15)
    retry_limit = models.PositiveIntegerField(default=1)

    recurrence_type = models.CharField(max_length=16, choices=RecurrenceType.choices)
    # INTERVAL: chạy lại mỗi N phút kể từ lần chạy trước (None/0 = chưa cấu hình).
    interval_minutes = models.PositiveIntegerField(null=True, blank=True)
    # WEEKLY: danh sách thứ trong tuần theo datetime.weekday() (0=Thứ Hai .. 6=Chủ Nhật) +
    # giờ cố định trong ngày (giờ địa phương TIME_ZONE của server).
    weekly_days = models.JSONField(default=list, blank=True)
    weekly_time = models.TimeField(null=True, blank=True)

    enabled = models.BooleanField(default=True, help_text="Tắt để tạm dừng lịch mà không phải xóa.")
    last_triggered_at = models.DateTimeField(null=True, blank=True)

    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL
    )

    class Meta:
        ordering = ["-created_at"]
        verbose_name = "Lịch lặp deployment"

    def __str__(self):
        return f"{self.name} ({self.get_recurrence_type_display()})"

    def is_due(self, now=None) -> bool:
        """True nếu đã tới lúc kích hoạt lần tiếp theo."""
        if not self.enabled:
            return False
        now = now or timezone.now()

        if self.recurrence_type == RecurrenceType.INTERVAL:
            if not self.interval_minutes:
                return False
            if self.last_triggered_at is None:
                return True
            elapsed = (now - self.last_triggered_at).total_seconds()
            return elapsed >= self.interval_minutes * 60

        if self.recurrence_type == RecurrenceType.WEEKLY:
            if self.weekly_time is None or not self.weekly_days:
                return False
            local_now = timezone.localtime(now)
            if local_now.weekday() not in self.weekly_days:
                return False
            scheduled_today = local_now.replace(
                hour=self.weekly_time.hour,
                minute=self.weekly_time.minute,
                second=0,
                microsecond=0,
            )
            if local_now < scheduled_today:
                return False  # chưa tới giờ hôm nay
            if self.last_triggered_at and timezone.localtime(self.last_triggered_at) >= scheduled_today:
                return False  # hôm nay đã kích hoạt rồi
            return True

        return False

    def spawn_deployment(self, now=None) -> Deployment:
        """Clone cấu hình lịch thành 1 Deployment MỚI (chưa launch)."""
        now = now or timezone.now()
        dep = Deployment.objects.create(
            name=f"{self.name} — {timezone.localtime(now):%Y-%m-%d %H:%M}",
            action=self.action,
            package_version=self.package_version,
            credential=self.credential,
            targeting_rule=self.targeting_rule,
            max_concurrency=self.max_concurrency,
            retry_limit=self.retry_limit,
            created_by=self.created_by,
            schedule=self,
        )
        dep.target_machines.set(self.target_machines.all())
        return dep
