from django.conf import settings
from rest_framework import serializers

from . import repository
from .models import InstallerType, Package, PackageDownload, PackageFolder, PackageVersion


class PackageFolderSerializer(serializers.ModelSerializer):
    class Meta:
        model = PackageFolder
        fields = ["id", "name", "parent", "created_at"]

    def validate_parent(self, parent):
        # Chặn đặt cha là chính nó hoặc hậu duệ của nó — nếu không, dựng cây (đệ quy theo
        # parent ở frontend) sẽ lặp vô hạn. Chỉ áp dụng khi sửa (self.instance có sẵn);
        # folder mới tạo không thể là tổ tiên của chính nó.
        if parent is None or self.instance is None:
            return parent
        node = parent
        while node is not None:
            if node.pk == self.instance.pk:
                raise serializers.ValidationError(
                    "Không thể đặt thư mục cha là chính nó hoặc thư mục con của nó."
                )
            node = node.parent
        return parent


class PackageVersionSerializer(serializers.ModelSerializer):
    package_name = serializers.CharField(source="package.name", read_only=True)
    # Không bắt buộc: nếu để trống, create() tự suy ra từ đuôi file installer.
    installer_type = serializers.ChoiceField(choices=InstallerType.choices, required=False)

    def validate_installer_file(self, upload):
        # Chặn upload installer quá lớn (đầy đĩa repository). None xảy ra khi update không
        # đổi file → bỏ qua.
        if upload is None:
            return upload
        max_mb = settings.RYANDEPLOY.get("MAX_INSTALLER_MB", 2048)
        if upload.size > max_mb * 1024 * 1024:
            raise serializers.ValidationError(
                f"File installer {upload.size / (1024 * 1024):.0f} MB vượt giới hạn {max_mb} MB."
            )
        return upload

    def validate(self, attrs):
        # Archive .zip sẽ bị PushExecutor giải nén (tar.exe, quyền SYSTEM) trên MỌI máy
        # đích -> chặn zip-slip/zip-bomb NGAY tại đây, trước khi archive kịp lưu vào
        # repository và có cơ hội được đẩy ra fleet.
        upload = attrs.get("installer_file")
        if upload is not None:
            itype = attrs.get("installer_type") or repository.detect_installer_type(upload.name)
            if itype == InstallerType.ZIP:
                max_mb = settings.RYANDEPLOY.get("MAX_INSTALLER_MB", 2048)
                try:
                    repository.validate_zip_archive(upload, max_mb * 10 * 1024 * 1024)
                except ValueError as e:
                    raise serializers.ValidationError({"installer_file": str(e)})
        return attrs

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
            "verify_name",
            "sha256",
            "file_size",
            "success_exit_codes",
            "source",
            "download_url",
            "approved",
            "approved_at",
            "created_at",
        ]
        read_only_fields = ["sha256", "file_size", "source", "approved", "approved_at", "created_at"]

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

    def update(self, instance, validated_data):
        # Sửa version thường chỉ đổi metadata (lệnh cài, verify_name…). Nếu admin thay
        # installer_file thì phải tính lại checksum + kích thước, nếu không integrity
        # check sẽ so với sha256 cũ và luôn báo lỗi.
        upload = validated_data.get("installer_file")
        if upload is not None:
            validated_data["sha256"] = repository.compute_sha256(upload)
            validated_data["file_size"] = upload.size
            if not validated_data.get("installer_type"):
                validated_data["installer_type"] = repository.detect_installer_type(upload.name)
        return super().update(instance, validated_data)


class PackageSerializer(serializers.ModelSerializer):
    available_licenses = serializers.IntegerField(read_only=True)
    versions = PackageVersionSerializer(many=True, read_only=True)
    latest_version = serializers.SerializerMethodField()

    def get_latest_version(self, obj):
        latest = obj.latest_version
        return {"id": latest.id, "version": latest.version} if latest else None

    class Meta:
        model = Package
        fields = [
            "id",
            "name",
            "vendor",
            "description",
            "folder",
            "min_os",
            "min_ram_gb",
            "min_disk_gb",
            "total_licenses",
            "used_licenses",
            "available_licenses",
            "download_url",
            "auto_download",
            "auto_approve_after_days",
            "inventory_name",
            "latest_version",
            "versions",
            "created_at",
        ]


class PackageDownloadSerializer(serializers.ModelSerializer):
    package_name = serializers.CharField(source="package.name", read_only=True)
    requested_by_name = serializers.CharField(source="requested_by.username", read_only=True)

    class Meta:
        model = PackageDownload
        fields = [
            "id",
            "package",
            "package_name",
            "url",
            "version_str",
            "status",
            "package_version",
            "sha256",
            "file_size",
            "error",
            "requested_by_name",
            "created_at",
        ]
