from rest_framework import serializers

from .models import Deployment


class DeploymentSerializer(serializers.ModelSerializer):
    package_name = serializers.CharField(source="package_version.package.name", read_only=True)
    version = serializers.CharField(source="package_version.version", read_only=True)

    total_count = serializers.IntegerField(read_only=True)
    success_count = serializers.IntegerField(read_only=True)
    failed_count = serializers.IntegerField(read_only=True)
    pending_count = serializers.IntegerField(read_only=True)

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
