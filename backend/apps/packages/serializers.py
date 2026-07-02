from rest_framework import serializers

from . import repository
from .models import Package, PackageVersion


class PackageVersionSerializer(serializers.ModelSerializer):
    package_name = serializers.CharField(source="package.name", read_only=True)

    class Meta:
        model = PackageVersion
        fields = [
            "id",
            "package",
            "package_name",
            "version",
            "installer_file",
            "installer_type",
            "install_command",
            "uninstall_command",
            "sha256",
            "file_size",
            "success_exit_codes",
            "created_at",
        ]
        read_only_fields = ["sha256", "file_size", "created_at"]

    def create(self, validated_data):
        upload = validated_data.get("installer_file")

        # Tự phát hiện loại installer nếu chưa cung cấp
        if not validated_data.get("installer_type") and upload is not None:
            validated_data["installer_type"] = repository.detect_installer_type(upload.name)

        itype = validated_data.get("installer_type", "exe")

        # Gợi ý lệnh silent nếu admin để trống
        if not validated_data.get("install_command"):
            validated_data["install_command"] = repository.default_install_command(itype)

        # Mã exit code thành công mặc định
        if not validated_data.get("success_exit_codes"):
            validated_data["success_exit_codes"] = list(repository.DEFAULT_SUCCESS_EXIT_CODES)

        # Checksum + kích thước
        if upload is not None:
            validated_data["sha256"] = repository.compute_sha256(upload)
            validated_data["file_size"] = upload.size

        request = self.context.get("request")
        if request and request.user.is_authenticated:
            validated_data["created_by"] = request.user

        return super().create(validated_data)


class PackageSerializer(serializers.ModelSerializer):
    available_licenses = serializers.IntegerField(read_only=True)
    versions = PackageVersionSerializer(many=True, read_only=True)

    class Meta:
        model = Package
        fields = [
            "id",
            "name",
            "vendor",
            "description",
            "min_os",
            "min_ram_gb",
            "min_disk_gb",
            "total_licenses",
            "used_licenses",
            "available_licenses",
            "versions",
            "created_at",
        ]
