from rest_framework import serializers

from apps.agents.models import EnrollmentSecret

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
            "connection_mode",
            "agent_version",
        ]
        read_only_fields = ["agent_version"]


class MachineDetailSerializer(MachineSerializer):
    """Serializer cho machine detail — thêm trạng thái token agent (không bao giờ lộ token
    gốc, chỉ prefix + mốc thời gian) để admin theo dõi token 'chết' (agent ngừng poll) hoặc
    đã bị thu hồi. Tách riêng khỏi MachineSerializer để tránh N+1 query khi list nhiều máy."""

    agent_token = serializers.SerializerMethodField()

    class Meta(MachineSerializer.Meta):
        fields = MachineSerializer.Meta.fields + ["agent_token"]

    def get_agent_token(self, obj):
        token = obj.agent_tokens.order_by("-created_at").first()
        if token is None:
            return None
        return {
            "token_prefix": token.token_prefix,
            "created_at": token.created_at,
            "last_used_at": token.last_used_at,
            "revoked_at": token.revoked_at,
            "is_active": token.is_active,
        }


class EnrollmentSecretSerializer(serializers.ModelSerializer):
    """Read-only — tạo/thu hồi secret đi qua action riêng (EnrollmentSecretViewSet), không qua
    serializer này, vì cần trả raw secret 1 lần và validate expires_in_hours."""

    is_active = serializers.BooleanField(read_only=True)
    created_by_username = serializers.CharField(source="created_by.username", read_only=True, default=None)

    class Meta:
        model = EnrollmentSecret
        fields = [
            "id",
            "ad_ou",
            "secret_prefix",
            "expires_at",
            "max_uses",
            "use_count",
            "revoked_at",
            "is_active",
            "note",
            "created_at",
            "created_by_username",
        ]
        read_only_fields = fields


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
