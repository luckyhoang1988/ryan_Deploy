from rest_framework import viewsets

from apps.core.permissions import IsAdminStrict

from .models import AuditLog
from .serializers import AuditLogSerializer


class AuditLogViewSet(viewsets.ReadOnlyModelViewSet):
    # Audit log chứa chi tiết nhạy cảm (tên credential, lỗi job, kết quả sync AD) — Tier-0,
    # chỉ admin được đọc, khớp pattern UserViewSet/DeployCredentialViewSet.
    permission_classes = [IsAdminStrict]
    queryset = AuditLog.objects.select_related("user").all()
    serializer_class = AuditLogSerializer

    def get_queryset(self):
        qs = super().get_queryset()
        action = self.request.query_params.get("action")
        if action:
            qs = qs.filter(action=action)
        return qs
