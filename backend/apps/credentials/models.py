from django.db import models

from apps.core.models import TimeStampedModel

from . import vault


class DeployCredential(TimeStampedModel):
    """
    Credential domain dùng để đẩy phần mềm (kiểu 'Deployment Credential' của PDQ).
    Password được mã hóa at-rest bằng Fernet — DB chỉ chứa ciphertext.
    """

    name = models.CharField(max_length=255, unique=True, help_text="Tên gợi nhớ, VD 'svc_ryandeploy'")
    domain = models.CharField(max_length=255, blank=True, help_text="Tên domain NetBIOS, VD 'CORP'")
    username = models.CharField(max_length=255)

    # KHÔNG bao giờ lưu plaintext. Trường này chứa Fernet token.
    password_encrypted = models.TextField(editable=False, default="")

    is_default = models.BooleanField(default=False, help_text="Credential mặc định khi tạo deployment")

    class Meta:
        ordering = ["name"]
        verbose_name = "Deploy Credential"

    def __str__(self):
        return f"{self.domain}\\{self.username}" if self.domain else self.username

    # --- API mã hóa ---
    def set_password(self, raw_password: str) -> None:
        self.password_encrypted = vault.encrypt(raw_password or "")

    def get_password(self) -> str:
        return vault.decrypt(self.password_encrypted)

    @property
    def qualified_username(self) -> str:
        """Định dạng DOMAIN\\user cho xác thực NTLM."""
        return f"{self.domain}\\{self.username}" if self.domain else self.username
