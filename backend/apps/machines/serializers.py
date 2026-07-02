from rest_framework import serializers

from .models import ADConfig, Machine, MachineGroup


class MachineSerializer(serializers.ModelSerializer):
    class Meta:
        model = Machine
        fields = [
            "id",
            "hostname",
            "fqdn",
            "ip_address",
            "os_name",
            "os_version",
            "ram_gb",
            "disk_free_gb",
            "ad_ou",
            "is_online",
            "last_seen",
            "enabled",
        ]


class ADConfigSerializer(serializers.ModelSerializer):
    """Không bao giờ trả mật khẩu ra ngoài; chỉ báo đã đặt hay chưa qua `has_password`."""

    bind_password = serializers.CharField(
        write_only=True, required=False, allow_blank=True,
        help_text="Để trống khi cập nhật = giữ mật khẩu cũ.",
    )
    has_password = serializers.SerializerMethodField()

    class Meta:
        model = ADConfig
        fields = [
            "server",
            "base_dn",
            "search_ou",
            "bind_user",
            "use_ssl",
            "enabled",
            "bind_password",
            "has_password",
            "updated_at",
        ]
        read_only_fields = ["updated_at"]

    def get_has_password(self, obj) -> bool:
        return bool(obj.bind_password_enc)

    def update(self, instance, validated_data):
        password = validated_data.pop("bind_password", None)
        for field, value in validated_data.items():
            setattr(instance, field, value)
        # Chỉ đổi mật khẩu khi người dùng nhập giá trị mới (khác rỗng).
        if password:
            instance.set_password(password)
        instance.save()
        return instance


class MachineGroupSerializer(serializers.ModelSerializer):
    machine_count = serializers.IntegerField(source="machines.count", read_only=True)

    class Meta:
        model = MachineGroup
        fields = ["id", "name", "description", "machines", "machine_count"]
