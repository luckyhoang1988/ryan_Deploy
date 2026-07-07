from django.conf import settings
from django.db import models

from apps.core.models import TimeStampedModel


class AgentToken(TimeStampedModel):
    """
    Token xác thực agent (mặt phẳng tin cậy tách biệt hoàn toàn khỏi RBAC người dùng).
    Lưu hash một chiều (sha256) — server chỉ cần so khớp, không bao giờ cần hiển thị lại
    token gốc, khác với DeployCredential/ADConfig (dùng Fernet vault vì phải giải mã lại).
    """

    # ForeignKey (không phải OneToOne): mỗi lần xoay token tạo 1 bản ghi mới, giữ lại các bản ghi
    # đã revoke để tra lịch sử/audit — OneToOne sẽ chặn việc cấp lại token sau lần revoke đầu tiên.
    machine = models.ForeignKey(
        "machines.Machine", on_delete=models.CASCADE, related_name="agent_tokens",
    )
    token_hash = models.CharField(max_length=64, unique=True, db_index=True)
    token_prefix = models.CharField(
        max_length=8, blank=True, help_text="Phần đầu token (không bí mật) để admin nhận diện trong UI/audit",
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL,
    )
    revoked_at = models.DateTimeField(null=True, blank=True)
    last_used_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        verbose_name = "Agent token"
        verbose_name_plural = "Agent tokens"
        constraints = [
            # Chỉ 1 token active (chưa revoke) tại một thời điểm cho mỗi máy.
            models.UniqueConstraint(
                fields=["machine"], condition=models.Q(revoked_at__isnull=True),
                name="agents_agenttoken_one_active_per_machine",
            ),
        ]

    def __str__(self):
        status = "revoked" if self.revoked_at else "active"
        return f"AgentToken({self.machine.hostname}, {self.token_prefix}…, {status})"

    @property
    def is_active(self) -> bool:
        return self.revoked_at is None
