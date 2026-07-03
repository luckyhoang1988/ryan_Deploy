from django.conf import settings
from django.db import models


class AuditLog(models.Model):
    """Nhật ký kiểm toán: ai làm gì, khi nào, trên đối tượng/máy nào."""

    class Action(models.TextChoices):
        PACKAGE_UPLOAD = "package_upload", "Upload package"
        PACKAGE_UPDATE = "package_update", "Sửa package"
        PACKAGE_DELETE = "package_delete", "Xóa package"
        PACKAGE_VERSION_DELETE = "package_version_delete", "Xóa version"
        CREDENTIAL_CREATE = "credential_create", "Tạo credential"
        CREDENTIAL_UPDATE = "credential_update", "Sửa credential"
        CREDENTIAL_DELETE = "credential_delete", "Xóa credential"
        DEPLOYMENT_CREATE = "deployment_create", "Tạo deployment"
        DEPLOYMENT_UPDATE = "deployment_update", "Sửa deployment"
        DEPLOYMENT_DELETE = "deployment_delete", "Xóa deployment"
        DEPLOYMENT_TRIGGER = "deployment_trigger", "Kích hoạt deployment"
        DEPLOYMENT_CANCEL = "deployment_cancel", "Hủy deployment"
        JOB_START = "job_start", "Bắt đầu job"
        JOB_FINISH = "job_finish", "Kết thúc job"
        MACHINE_SYNC = "machine_sync", "Đồng bộ máy từ AD"

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL
    )
    action = models.CharField(max_length=32, choices=Action.choices, db_index=True)

    # Đối tượng liên quan (lỏng, không FK cứng để log bền vững)
    target_type = models.CharField(max_length=64, blank=True)
    target_id = models.CharField(max_length=64, blank=True)
    machine_hostname = models.CharField(max_length=255, blank=True)

    detail = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.created_at:%Y-%m-%d %H:%M} {self.action} by {self.user}"

    @classmethod
    def record(cls, action, user=None, target=None, machine_hostname="", **detail):
        """Helper ghi log nhanh."""
        target_type = target.__class__.__name__ if target is not None else ""
        target_id = str(getattr(target, "pk", "")) if target is not None else ""
        return cls.objects.create(
            user=user if (user and getattr(user, "is_authenticated", False)) else None,
            action=action,
            target_type=target_type,
            target_id=target_id,
            machine_hostname=machine_hostname,
            detail=detail,
        )
