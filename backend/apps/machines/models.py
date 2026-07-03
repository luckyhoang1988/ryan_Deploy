from django.db import models

from apps.core.models import TimeStampedModel


class Machine(TimeStampedModel):
    """Một máy trạm Windows trong domain — mục tiêu đẩy phần mềm."""

    hostname = models.CharField(max_length=255, unique=True, db_index=True)
    fqdn = models.CharField(max_length=512, blank=True, help_text="Fully-qualified domain name")
    ip_address = models.GenericIPAddressField(null=True, blank=True)

    os_name = models.CharField(max_length=128, blank=True)
    os_version = models.CharField(max_length=64, blank=True)
    ram_gb = models.PositiveIntegerField(null=True, blank=True)
    disk_free_gb = models.PositiveIntegerField(null=True, blank=True)

    ad_ou = models.CharField(max_length=512, blank=True, help_text="Distinguished Name của OU trong AD")

    is_online = models.BooleanField(default=False)
    last_seen = models.DateTimeField(null=True, blank=True)

    enabled = models.BooleanField(default=True, help_text="Cho phép đẩy phần mềm tới máy này")

    class Meta:
        ordering = ["hostname"]

    def __str__(self):
        return self.hostname

    @property
    def target_address(self):
        """Địa chỉ dùng để kết nối SMB: ưu tiên FQDN, fallback hostname/IP."""
        return self.fqdn or self.hostname or self.ip_address


class InstalledSoftware(TimeStampedModel):
    """
    Một phần mềm đã cài trên 1 máy — thu từ registry Uninstall keys qua action
    inventory. Dùng cho conditional targeting ("thiếu Chrome thì cài Chrome").
    Mỗi lần scan sẽ thay toàn bộ bản ghi của máy đó (xoá cũ, ghi mới).
    """

    machine = models.ForeignKey(Machine, on_delete=models.CASCADE, related_name="installed_software")
    name = models.CharField(max_length=512, db_index=True)  # DisplayName
    version = models.CharField(max_length=128, blank=True)  # DisplayVersion
    publisher = models.CharField(max_length=255, blank=True)
    source = models.CharField(max_length=32, default="registry")
    scanned_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        unique_together = ("machine", "name", "version")
        indexes = [models.Index(fields=["machine", "name"])]

    def __str__(self):
        return f"{self.name} {self.version} @ {self.machine.hostname}"


class ADConfig(TimeStampedModel):
    """
    Cấu hình kết nối Active Directory/LDAP — chỉnh trực tiếp từ Web UI.
    Singleton (luôn pk=1). Mật khẩu bind lưu dạng mã hóa Fernet (vault).
    Khi `enabled=True`, cấu hình này được ưu tiên hơn biến môi trường AD_*.
    """

    server = models.CharField(
        max_length=255, blank=True,
        help_text="Host hoặc URI, vd: dc01.corp.local hoặc ldaps://dc01.corp.local",
    )
    base_dn = models.CharField(
        max_length=512, blank=True, help_text="vd: DC=corp,DC=local",
    )
    search_ou = models.CharField(
        max_length=512, blank=True,
        help_text="OU giới hạn tìm kiếm (để trống = toàn bộ base_dn)",
    )
    bind_user = models.CharField(
        max_length=255, blank=True, help_text="vd: CORP\\svc_deploy",
    )
    bind_password_enc = models.TextField(blank=True, help_text="Token Fernet, không hiển thị")
    use_ssl = models.BooleanField(default=False, help_text="LDAPS (cổng 636)")
    enabled = models.BooleanField(
        default=False, help_text="Dùng cấu hình này thay cho biến môi trường AD_*",
    )

    class Meta:
        verbose_name = "Cấu hình AD"
        verbose_name_plural = "Cấu hình AD"

    def __str__(self):
        return f"ADConfig({self.server or 'chưa cấu hình'})"

    def set_password(self, raw: str):
        from apps.credentials.vault import encrypt

        self.bind_password_enc = encrypt(raw) if raw else ""

    def get_password(self) -> str:
        from apps.credentials.vault import decrypt

        return decrypt(self.bind_password_enc) if self.bind_password_enc else ""

    @classmethod
    def load(cls) -> "ADConfig":
        obj, _ = cls.objects.get_or_create(pk=1)
        return obj


class MachineGroup(TimeStampedModel):
    """Nhóm máy để chọn nhanh khi tạo deployment."""

    name = models.CharField(max_length=255, unique=True)
    description = models.TextField(blank=True)
    machines = models.ManyToManyField(Machine, related_name="groups", blank=True)

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return self.name
