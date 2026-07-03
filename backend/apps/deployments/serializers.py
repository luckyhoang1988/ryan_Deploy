from rest_framework import serializers

from .models import Deployment, DeploymentAction, PACKAGE_ACTIONS


class DeploymentSerializer(serializers.ModelSerializer):
    package_name = serializers.CharField(source="package_version.package.name", read_only=True)
    version = serializers.CharField(source="package_version.version", read_only=True)

    # Ưu tiên giá trị annotate từ queryset list (n_*, tránh N+1); nếu vắng (vd response
    # sau create — instance chưa qua annotate) thì fallback về property của model.
    total_count = serializers.SerializerMethodField()
    success_count = serializers.SerializerMethodField()
    failed_count = serializers.SerializerMethodField()
    pending_count = serializers.SerializerMethodField()

    @staticmethod
    def _count(obj, annotated, prop):
        value = getattr(obj, annotated, None)
        return value if value is not None else getattr(obj, prop)

    def get_total_count(self, obj):
        return self._count(obj, "n_total", "total_count")

    def get_success_count(self, obj):
        return self._count(obj, "n_success", "success_count")

    def get_failed_count(self, obj):
        return self._count(obj, "n_failed", "failed_count")

    def get_pending_count(self, obj):
        return self._count(obj, "n_pending", "pending_count")

    class Meta:
        model = Deployment
        fields = [
            "id",
            "name",
            "action",
            "package_version",
            "package_name",
            "version",
            "credential",
            "target_machines",
            "targeting_rule",
            "status",
            "scheduled_at",
            "max_concurrency",
            "retry_limit",
            "started_at",
            "finished_at",
            "total_count",
            "success_count",
            "failed_count",
            "pending_count",
            "created_at",
        ]
        read_only_fields = ["status", "started_at", "finished_at"]

    def validate(self, attrs):
        # action lấy từ payload nếu có, ngược lại giữ giá trị hiện tại (partial update).
        action = attrs.get("action") or getattr(self.instance, "action", DeploymentAction.INSTALL)
        # package_version có thể vắng trong attrs (partial); lấy từ instance làm fallback.
        pv = attrs.get("package_version", getattr(self.instance, "package_version", None))

        if action in PACKAGE_ACTIONS:
            if pv is None:
                raise serializers.ValidationError(
                    {"package_version": f"Action '{action}' cần chọn một package version."}
                )
            if action == DeploymentAction.UNINSTALL and not (pv.uninstall_command or "").strip():
                raise serializers.ValidationError(
                    {"package_version": "Package version này chưa có lệnh gỡ cài đặt (uninstall_command)."}
                )
        elif pv is not None:
            # reboot/shutdown/inventory không gắn package_version.
            raise serializers.ValidationError(
                {"package_version": f"Action '{action}' không được gắn package version."}
            )
        return attrs

    def create(self, validated_data):
        request = self.context.get("request")
        if request and request.user.is_authenticated:
            validated_data["created_by"] = request.user
        return super().create(validated_data)
