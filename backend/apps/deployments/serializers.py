from rest_framework import serializers

from .models import Deployment


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
            "package_version",
            "package_name",
            "version",
            "credential",
            "target_machines",
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

    def create(self, validated_data):
        request = self.context.get("request")
        if request and request.user.is_authenticated:
            validated_data["created_by"] = request.user
        return super().create(validated_data)
