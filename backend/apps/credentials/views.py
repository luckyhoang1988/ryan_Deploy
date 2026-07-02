from rest_framework import viewsets

from apps.audit.models import AuditLog
from apps.core.permissions import IsAdmin

from .models import DeployCredential
from .serializers import DeployCredentialSerializer


class DeployCredentialViewSet(viewsets.ModelViewSet):
    """Quản lý credential deploy — chỉ admin. Password không bao giờ trả ra."""

    queryset = DeployCredential.objects.all()
    serializer_class = DeployCredentialSerializer
    permission_classes = [IsAdmin]

    def perform_create(self, serializer):
        cred = serializer.save()
        AuditLog.record(
            AuditLog.Action.CREDENTIAL_CREATE, user=self.request.user, target=cred, name=cred.name
        )
