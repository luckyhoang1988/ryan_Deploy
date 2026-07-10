from rest_framework import viewsets

from apps.audit.models import AuditLog
from apps.core.permissions import IsAdminStrict

from .models import DeployCredential
from .serializers import DeployCredentialSerializer


class DeployCredentialViewSet(viewsets.ModelViewSet):
    """Quản lý credential deploy — chỉ admin (kể cả đọc, không lộ username/domain cho viewer)."""

    queryset = DeployCredential.objects.all()
    serializer_class = DeployCredentialSerializer
    permission_classes = [IsAdminStrict]

    def perform_create(self, serializer):
        cred = serializer.save()
        AuditLog.record(
            AuditLog.Action.CREDENTIAL_CREATE, user=self.request.user, target=cred, name=cred.name
        )

    def perform_update(self, serializer):
        cred = serializer.save()
        AuditLog.record(
            AuditLog.Action.CREDENTIAL_UPDATE, user=self.request.user, target=cred, name=cred.name
        )

    def perform_destroy(self, instance):
        # Ghi log TRƯỚC khi xóa để còn giữ được tên/pk trong bản ghi kiểm toán.
        AuditLog.record(
            AuditLog.Action.CREDENTIAL_DELETE,
            user=self.request.user,
            target=instance,
            name=instance.name,
        )
        instance.delete()
