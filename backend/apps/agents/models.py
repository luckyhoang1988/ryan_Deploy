from django.conf import settings
from django.db import models
from django.utils import timezone

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


class EnrollmentSecret(TimeStampedModel):
    """
    Secret dùng CHUNG cho self-enrollment hàng loạt — khác AgentToken (1 token/máy). Máy tự
    đổi secret này lấy 1 AgentToken thật của riêng nó qua enroll_machine() (services.py), nên
    bản thân secret không cấp quyền poll job. Lưu hash một chiều, giống AgentToken.token_hash.
    """

    ad_ou = models.CharField(
        max_length=512, blank=True,
        help_text="Giới hạn theo OU (khớp DN từ AD sync). Để trống = global — dùng được cho mọi máy.",
    )
    secret_hash = models.CharField(max_length=64, unique=True, db_index=True)
    secret_prefix = models.CharField(
        max_length=8, blank=True, help_text="Phần đầu secret (không bí mật) để admin nhận diện trong UI/audit",
    )
    expires_at = models.DateTimeField(
        null=True, blank=True,
        help_text="Để trống = không bao giờ tự hết hạn (chỉ dùng khi admin chủ động chọn "
                   "'never_expires', ví dụ secret tĩnh đóng cứng vào MSI cài đặt).",
    )
    max_uses = models.PositiveIntegerField(null=True, blank=True)
    use_count = models.PositiveIntegerField(default=0)
    revoked_at = models.DateTimeField(null=True, blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL,
    )
    note = models.CharField(max_length=255, blank=True)

    class Meta:
        verbose_name = "Enrollment secret"
        verbose_name_plural = "Enrollment secrets"
        indexes = [models.Index(fields=["ad_ou"])]

    def __str__(self):
        return f"EnrollmentSecret({self.ad_ou or 'global'}, {self.secret_prefix}…)"

    @property
    def is_active(self) -> bool:
        if self.revoked_at is not None:
            return False
        if self.expires_at is not None and timezone.now() >= self.expires_at:
            return False
        if self.max_uses is not None and self.use_count >= self.max_uses:
            return False
        return True
