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


class MachineGroup(TimeStampedModel):
    """Nhóm máy để chọn nhanh khi tạo deployment."""

    name = models.CharField(max_length=255, unique=True)
    description = models.TextField(blank=True)
    machines = models.ManyToManyField(Machine, related_name="groups", blank=True)

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return self.name
