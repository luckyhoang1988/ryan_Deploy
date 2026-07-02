from rest_framework import serializers

from .models import Machine, MachineGroup


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


class MachineGroupSerializer(serializers.ModelSerializer):
    machine_count = serializers.IntegerField(source="machines.count", read_only=True)

    class Meta:
        model = MachineGroup
        fields = ["id", "name", "description", "machines", "machine_count"]
