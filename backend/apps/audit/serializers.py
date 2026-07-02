from rest_framework import serializers

from .models import AuditLog


class AuditLogSerializer(serializers.ModelSerializer):
    username = serializers.CharField(source="user.username", read_only=True, default="")
    action_display = serializers.CharField(source="get_action_display", read_only=True)

    class Meta:
        model = AuditLog
        fields = [
            "id",
            "created_at",
            "action",
            "action_display",
            "username",
            "target_type",
            "target_id",
            "machine_hostname",
            "detail",
        ]
