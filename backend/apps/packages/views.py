from rest_framework import viewsets
from rest_framework.parsers import FormParser, MultiPartParser

from apps.audit.models import AuditLog

from .models import Package, PackageVersion
from .serializers import PackageSerializer, PackageVersionSerializer


class PackageViewSet(viewsets.ModelViewSet):
    queryset = Package.objects.all()
    serializer_class = PackageSerializer


class PackageVersionViewSet(viewsets.ModelViewSet):
    queryset = PackageVersion.objects.select_related("package").all()
    serializer_class = PackageVersionSerializer
    parser_classes = [MultiPartParser, FormParser]

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
