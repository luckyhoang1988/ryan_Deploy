from rest_framework import serializers

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
