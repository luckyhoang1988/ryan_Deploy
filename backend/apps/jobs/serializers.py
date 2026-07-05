from rest_framework import serializers

from apps.core.permissions import ROLE_ADMIN, ROLE_OPERATOR, has_role

from .models import Job


class JobSerializer(serializers.ModelSerializer):
    machine_hostname = serializers.CharField(source="machine.hostname", read_only=True)

    class Meta:
        model = Job
        fields = [
            "id",
            "deployment",
            "machine",
            "machine_hostname",
            "status",
            "current_step",
            "exit_code",
            "output",
            "error_output",
            "attempts",
            "started_at",
            "finished_at",
        ]

    def to_representation(self, instance):
        # output/error_output có thể chứa dữ liệu nhạy cảm từ máy đích (stdout cài đặt,
        # thông báo lỗi hệ thống) — chỉ operator/admin mới xem được nội dung log chi tiết.
        # Viewer vẫn thấy status/exit_code/current_step để theo dõi tiến độ.
        data = super().to_representation(instance)
        request = self.context.get("request")
        if request and not has_role(request.user, ROLE_OPERATOR, ROLE_ADMIN):
            data["output"] = None
            data["error_output"] = None
        return data
