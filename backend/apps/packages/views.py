from django.db.models import ProtectedError
from rest_framework import viewsets
from rest_framework.exceptions import ValidationError
from rest_framework.parsers import FormParser, MultiPartParser

from apps.audit.models import AuditLog
from apps.core.permissions import IsAdmin

from .models import Package, PackageVersion
from .serializers import PackageSerializer, PackageVersionSerializer


class PackageViewSet(viewsets.ModelViewSet):
    queryset = Package.objects.all()
    serializer_class = PackageSerializer
    # Tier-0: chỉ admin được tạo/sửa/xóa package (đọc vẫn cho mọi user auth).
    permission_classes = [IsAdmin]

    def perform_update(self, serializer):
        package = serializer.save()
        AuditLog.record(
            AuditLog.Action.PACKAGE_UPDATE,
            user=self.request.user,
            target=package,
            package=package.name,
        )

    def perform_destroy(self, instance):
        # Xóa Package sẽ CASCADE toàn bộ version — thu thập đường dẫn file installer
        # TRƯỚC khi xóa DB để dọn file trên đĩa sau đó (FileField không tự xóa file).
        files = [v.installer_file for v in instance.versions.all() if v.installer_file]
        name = instance.name
        saved_pk = instance.pk
        try:
            instance.delete()
        except ProtectedError:
            # Có deployment đang tham chiếu version của package (FK PROTECT).
            raise ValidationError(
                "Không thể xóa package: vẫn còn deployment đang tham chiếu tới version của nó. "
                "Hãy xóa các deployment liên quan trước."
            )
        for f in files:
            f.delete(save=False)
        # delete() đặt instance.pk = None; gán lại để bản ghi audit giữ được target_id.
        instance.pk = saved_pk
        AuditLog.record(
            AuditLog.Action.PACKAGE_DELETE,
            user=self.request.user,
            target=instance,
            package=name,
        )


class PackageVersionViewSet(viewsets.ModelViewSet):
    queryset = PackageVersion.objects.select_related("package").all()
    serializer_class = PackageVersionSerializer
    parser_classes = [MultiPartParser, FormParser]
    # Tier-0: chỉ admin được upload installer (.msi/.exe) lên repository.
    permission_classes = [IsAdmin]

    def perform_create(self, serializer):
        version = serializer.save()
        AuditLog.record(
            AuditLog.Action.PACKAGE_UPLOAD,
            user=self.request.user,
            target=version,
            package=version.package.name,
            version=version.version,
            sha256=version.sha256,
        )

    def perform_destroy(self, instance):
        installer_file = instance.installer_file
        pkg_name = instance.package.name
        ver = instance.version
        saved_pk = instance.pk
        try:
            instance.delete()
        except ProtectedError:
            raise ValidationError(
                "Không thể xóa version: đang có deployment tham chiếu tới nó. "
                "Hãy xóa các deployment liên quan trước."
            )
        # Dọn file installer trên đĩa sau khi bản ghi đã xóa thành công.
        if installer_file:
            installer_file.delete(save=False)
        instance.pk = saved_pk  # giữ target_id cho bản ghi audit sau khi delete()
        AuditLog.record(
            AuditLog.Action.PACKAGE_VERSION_DELETE,
            user=self.request.user,
            target=instance,
            package=pkg_name,
            version=ver,
        )
