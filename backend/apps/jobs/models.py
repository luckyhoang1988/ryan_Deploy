from django.db import models

from apps.core.models import TimeStampedModel


class JobStatus(models.TextChoices):
    PENDING = "pending", "Chờ"
    QUEUED = "queued", "Đã vào hàng đợi"
    RUNNING = "running", "Đang chạy"
    SUCCESS = "success", "Thành công"
    SUCCESS_REBOOT = "success_reboot", "Thành công (cần reboot)"
    FAILED = "failed", "Thất bại"
    SKIPPED = "skipped", "Bỏ qua"
    CANCELLED = "cancelled", "Đã hủy"


# Các step trong quy trình push (để hiển thị tiến độ chi tiết)
class JobStep(models.TextChoices):
    PRECHECK = "precheck", "Kiểm tra trước"
    COPY = "copy", "Copy file"
    EXECUTE = "execute", "Thực thi cài đặt"
    COLLECT = "collect", "Thu kết quả"
    VERIFY = "verify", "Hậu kiểm"
    CLEANUP = "cleanup", "Dọn dẹp"
    DONE = "done", "Xong"


class Job(TimeStampedModel):
    """
    Một đơn vị công việc: đẩy 1 deployment tới 1 máy.
    Một Deployment fan-out thành N Job (N = số máy đích).
    """

    deployment = models.ForeignKey(
        "deployments.Deployment", on_delete=models.CASCADE, related_name="jobs"
    )
    machine = models.ForeignKey("machines.Machine", on_delete=models.PROTECT, related_name="jobs")

    status = models.CharField(
        max_length=20, choices=JobStatus.choices, default=JobStatus.PENDING, db_index=True
    )
    current_step = models.CharField(max_length=20, choices=JobStep.choices, blank=True)

    exit_code = models.IntegerField(null=True, blank=True)
    output = models.TextField(blank=True)
    error_output = models.TextField(blank=True)

    attempts = models.PositiveIntegerField(default=0)
    celery_task_id = models.CharField(max_length=255, blank=True, db_index=True)

    started_at = models.DateTimeField(null=True, blank=True)
    finished_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]
        unique_together = ("deployment", "machine")
        indexes = [
            models.Index(fields=["deployment", "status"]),
        ]

    def __str__(self):
        return f"Job#{self.pk} {self.machine} [{self.status}]"

    @property
    def is_terminal(self) -> bool:
        return self.status in (
            JobStatus.SUCCESS,
            JobStatus.SUCCESS_REBOOT,
            JobStatus.FAILED,
            JobStatus.SKIPPED,
            JobStatus.CANCELLED,
        )
