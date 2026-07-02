from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response

from apps.audit.models import AuditLog

from .models import Machine, MachineGroup
from .serializers import MachineGroupSerializer, MachineSerializer
from .tasks import check_all_online, sync_from_ad


class MachineViewSet(viewsets.ModelViewSet):
    queryset = Machine.objects.all()
    serializer_class = MachineSerializer
    filterset_fields = ["is_online", "enabled", "ad_ou"]

    def get_queryset(self):
        qs = super().get_queryset()
        online = self.request.query_params.get("is_online")
        if online in ("true", "false"):
            qs = qs.filter(is_online=(online == "true"))
        group_id = self.request.query_params.get("group")
        if group_id:
            qs = qs.filter(groups__id=group_id)
        return qs

    @action(detail=False, methods=["post"])
    def sync_ad(self, request):
        """Đồng bộ máy từ Active Directory. Body tùy chọn: {"search_ou": "OU=..."}"""
        search_ou = request.data.get("search_ou")
        result = sync_from_ad(search_ou=search_ou)
        AuditLog.record(
            AuditLog.Action.MACHINE_SYNC, user=request.user, search_ou=search_ou or "", **result
        )
        code = status.HTTP_200_OK if not result.get("error") else status.HTTP_400_BAD_REQUEST
        return Response(result, status=code)

    @action(detail=False, methods=["post"])
    def check_online(self, request):
        """Kiểm tra trạng thái online của tất cả máy ngay lập tức."""
        result = check_all_online()
        return Response(result, status=status.HTTP_200_OK)


class MachineGroupViewSet(viewsets.ModelViewSet):
    queryset = MachineGroup.objects.prefetch_related("machines").all()
    serializer_class = MachineGroupSerializer
