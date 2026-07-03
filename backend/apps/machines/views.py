from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.core.permissions import IsAdmin, IsViewerOrAbove

from .ad_sync import test_ad_connection
from .models import ADConfig, Machine, MachineGroup
from .serializers import ADConfigSerializer, MachineGroupSerializer, MachineSerializer
from .tasks import check_all_online, sync_from_ad


class MachineViewSet(viewsets.ModelViewSet):
    queryset = Machine.objects.all()
    serializer_class = MachineSerializer
    filterset_fields = ["is_online", "enabled", "ad_ou"]
    # Mặc định chỉ admin được sửa danh sách máy / sync AD (Tier-0).
    permission_classes = [IsAdmin]

    def get_permissions(self):
        # check_online chỉ đọc trạng thái online → operator cũng được (không cần admin).
        if self.action == "check_online":
            return [IsViewerOrAbove()]
        return super().get_permissions()

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
        """
        Đồng bộ máy từ Active Directory (chạy nền — LDAP có thể chậm, không chặn web worker).
        Body tùy chọn: {"search_ou": "OU=..."}. Trả task_id để client poll /api/tasks/<id>/.
        """
        search_ou = request.data.get("search_ou")
        task = sync_from_ad.delay(search_ou, request.user.id)
        return Response(
            {"detail": "Đã bắt đầu đồng bộ AD (chạy nền).", "task_id": task.id},
            status=status.HTTP_202_ACCEPTED,
        )

    @action(detail=False, methods=["post"])
    def check_online(self, request):
        """Kiểm tra online toàn bộ máy (chạy nền — ping nhiều máy có thể lâu)."""
        task = check_all_online.delay()
        return Response(
            {"detail": "Đang kiểm tra online (chạy nền).", "task_id": task.id},
            status=status.HTTP_202_ACCEPTED,
        )


class MachineGroupViewSet(viewsets.ModelViewSet):
    queryset = MachineGroup.objects.prefetch_related("machines").all()
    serializer_class = MachineGroupSerializer


class ADConfigView(APIView):
    """
    GET  /api/ad-config/  → đọc cấu hình (không có mật khẩu).
    PUT  /api/ad-config/  → lưu cấu hình (chỉ admin).
    """

    permission_classes = [IsAdmin]

    def get(self, request):
        return Response(ADConfigSerializer(ADConfig.load()).data)

    def put(self, request):
        obj = ADConfig.load()
        serializer = ADConfigSerializer(obj, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response(serializer.data)


class ADConfigTestView(APIView):
    """POST /api/ad-config/test/ → thử kết nối + bind với cấu hình đã lưu."""

    permission_classes = [IsAdmin]

    def post(self, request):
        result = test_ad_connection()
        code = status.HTTP_200_OK if result.get("ok") else status.HTTP_400_BAD_REQUEST
        return Response(result, status=code)
