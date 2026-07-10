from rest_framework import serializers

from apps.machines.models import ConnectionMode
from apps.packages.models import InstallerType

from .models import (
    PACKAGE_ACTIONS,
    Deployment,
    DeploymentAction,
    DeploymentSchedule,
    RecurrenceType,
)


def _validate_package_action(action, pv, errors_key="package_version"):
    """
    Dùng chung cho Deployment & DeploymentSchedule: install/uninstall bắt buộc có
    package_version; reboot/shutdown/inventory thì KHÔNG được gắn.
    Chỉ cho phép version đã duyệt (approved) — tránh deploy bản chờ review.
    """
    if action in PACKAGE_ACTIONS:
        if pv is None:
            raise serializers.ValidationError(
                {errors_key: f"Action '{action}' cần chọn một package version."}
            )
        if not pv.approved:
            raise serializers.ValidationError(
                {errors_key: "Version chưa được duyệt — không thể đưa vào deployment."}
            )
        if action == DeploymentAction.UNINSTALL and not (pv.uninstall_command or "").strip():
            raise serializers.ValidationError(
                {errors_key: "Package version này chưa có lệnh gỡ cài đặt (uninstall_command)."}
            )
    elif pv is not None:
        raise serializers.ValidationError(
            {errors_key: f"Action '{action}' không được gắn package version."}
        )


def _validate_agent_zip_targets(pv, machines, errors_key="target_machines"):
    """Agent v1 chưa giải nén .zip — chặn sớm lúc tạo/sửa thay vì fail lúc poll."""
    if pv is None or pv.installer_type != InstallerType.ZIP:
        return
    agent_hosts = [
        m.hostname for m in machines if getattr(m, "connection_mode", None) == ConnectionMode.AGENT
    ]
    if agent_hosts:
        raise serializers.ValidationError(
            {
                errors_key: (
                    "Package .zip chưa hỗ trợ qua agent (v1). Đổi các máy sau về "
                    f"connection_mode='smb' hoặc bỏ khỏi target: {', '.join(agent_hosts[:10])}"
                    + ("…" if len(agent_hosts) > 10 else "")
                )
            }
        )


class DeploymentSerializer(serializers.ModelSerializer):
    package_name = serializers.CharField(source="package_version.package.name", read_only=True)
    version = serializers.CharField(source="package_version.version", read_only=True)

    # Ưu tiên giá trị annotate từ queryset list (n_*, tránh N+1); nếu vắng (vd response
    # sau create — instance chưa qua annotate) thì fallback về property của model.
    total_count = serializers.SerializerMethodField()
    success_count = serializers.SerializerMethodField()
    failed_count = serializers.SerializerMethodField()
    skipped_count = serializers.SerializerMethodField()
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

    def get_skipped_count(self, obj):
        return self._count(obj, "n_skipped", "skipped_count")

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
            "skipped_count",
            "pending_count",
            "created_at",
        ]
        read_only_fields = ["status", "started_at", "finished_at"]

    def validate(self, attrs):
        # action lấy từ payload nếu có, ngược lại giữ giá trị hiện tại (partial update).
        action = attrs.get("action") or getattr(self.instance, "action", DeploymentAction.INSTALL)
        # package_version có thể vắng trong attrs (partial); lấy từ instance làm fallback.
        pv = attrs.get("package_version", getattr(self.instance, "package_version", None))
        _validate_package_action(action, pv)
        # target_machines: PrimaryKeyRelatedField đã resolve thành list Machine trong attrs;
        # partial update không gửi field → lấy từ instance.
        if "target_machines" in attrs:
            machines = attrs["target_machines"]
        elif self.instance is not None:
            machines = list(self.instance.target_machines.all())
        else:
            machines = []
        _validate_agent_zip_targets(pv, machines)
        return attrs

    def create(self, validated_data):
        request = self.context.get("request")
        if request and request.user.is_authenticated:
            validated_data["created_by"] = request.user
        return super().create(validated_data)


class DeploymentScheduleSerializer(serializers.ModelSerializer):
    package_name = serializers.CharField(source="package_version.package.name", read_only=True)
    version = serializers.CharField(source="package_version.version", read_only=True)

    class Meta:
        model = DeploymentSchedule
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
            "max_concurrency",
            "retry_limit",
            "recurrence_type",
            "interval_minutes",
            "weekly_days",
            "weekly_time",
            "enabled",
            "last_triggered_at",
            "created_at",
        ]
        read_only_fields = ["last_triggered_at", "created_at"]

    def validate(self, attrs):
        action = attrs.get("action") or getattr(self.instance, "action", DeploymentAction.INSTALL)
        pv = attrs.get("package_version", getattr(self.instance, "package_version", None))
        _validate_package_action(action, pv)
        if "target_machines" in attrs:
            machines = attrs["target_machines"]
        elif self.instance is not None:
            machines = list(self.instance.target_machines.all())
        else:
            machines = []
        _validate_agent_zip_targets(pv, machines)

        recurrence_type = attrs.get(
            "recurrence_type", getattr(self.instance, "recurrence_type", None)
        )
        interval_minutes = attrs.get(
            "interval_minutes", getattr(self.instance, "interval_minutes", None)
        )
        weekly_days = attrs.get("weekly_days", getattr(self.instance, "weekly_days", None))
        weekly_time = attrs.get("weekly_time", getattr(self.instance, "weekly_time", None))

        if recurrence_type == RecurrenceType.INTERVAL:
            if not interval_minutes or interval_minutes <= 0:
                raise serializers.ValidationError(
                    {"interval_minutes": "Lịch kiểu 'Lặp mỗi N phút' cần interval_minutes > 0."}
                )
        elif recurrence_type == RecurrenceType.WEEKLY:
            if not weekly_days:
                raise serializers.ValidationError(
                    {"weekly_days": "Lịch kiểu 'Theo ngày trong tuần' cần chọn ít nhất 1 ngày."}
                )
            if any(d < 0 or d > 6 for d in weekly_days):
                raise serializers.ValidationError(
                    {"weekly_days": "Mỗi ngày phải là số 0 (Thứ Hai) đến 6 (Chủ Nhật)."}
                )
            if weekly_time is None:
                raise serializers.ValidationError(
                    {"weekly_time": "Lịch kiểu 'Theo ngày trong tuần' cần giờ cố định."}
                )
        return attrs

    def create(self, validated_data):
        request = self.context.get("request")
        if request and request.user.is_authenticated:
            validated_data["created_by"] = request.user
        return super().create(validated_data)
