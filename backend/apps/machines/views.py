import csv
import io

from django.db.models import ProtectedError
from django.http import HttpResponse
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.core.permissions import IsAdmin, IsViewerOrAbove
from apps.core.task_registry import remember_task_owner

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
        # check_online, stats, export chỉ đọc → operator cũng được.
        if self.action in ("check_online", "stats", "export"):
            return [IsViewerOrAbove()]
        return super().get_permissions()

    def _apply_filters(self, qs):
        """Áp dụng bộ lọc chung cho list, stats, export."""
        params = self.request.query_params
        online = params.get("is_online")
        if online in ("true", "false"):
            qs = qs.filter(is_online=(online == "true"))
        group_id = params.get("group")
        if group_id:
            qs = qs.filter(groups__id=group_id)
        search = params.get("search", "").strip()
        if search:
            qs = qs.filter(hostname__icontains=search)
        ou = params.get("ad_ou", "").strip()
        if ou:
            qs = qs.filter(ad_ou__icontains=ou)
        return qs

    def get_queryset(self):
        return self._apply_filters(super().get_queryset())

    def perform_update(self, serializer):
        # Máy bị disable không còn được check_all_online refresh → is_online cũ sẽ
        # đứng hình mãi mãi và làm sai lệch thống kê online/offline. Xóa ngay lúc tắt.
        was_enabled = serializer.instance.enabled
        serializer.save()
        if was_enabled and not serializer.instance.enabled:
            serializer.instance.is_online = False
            serializer.instance.save(update_fields=["is_online"])

    @action(detail=False, methods=["get"])
    def stats(self, request):
        """Thống kê tổng, online, offline (áp dụng bộ lọc hiện tại)."""
        qs = self._apply_filters(Machine.objects.all())
        total = qs.count()
        online = qs.filter(is_online=True).count()
        return Response({
            "total": total,
            "online": online,
            "offline": total - online,
        })

    @action(detail=False, methods=["post"])
    def sync_ad(self, request):
        """
        Đồng bộ máy từ Active Directory (chạy nền — LDAP có thể chậm, không chặn web worker).
        Body tùy chọn: {"search_ou": "OU=...", "purge": true}.
        purge=true sẽ xóa máy không còn trong kết quả AD (dùng khi đổi OU scope).
        Trả task_id để client poll /api/tasks/<id>/.
        """
        search_ou = request.data.get("search_ou")
        purge = request.data.get("purge", False)
        task = sync_from_ad.delay(search_ou, request.user.id, purge)
        remember_task_owner(task.id, request.user.id)
        return Response(
            {"detail": "Đã bắt đầu đồng bộ AD (chạy nền).", "task_id": task.id},
            status=status.HTTP_202_ACCEPTED,
        )

    @action(detail=False, methods=["post"])
    def purge_all(self, request):
        """Xóa tất cả máy trong DB (reset trước khi sync lại với OU mới)."""
        try:
            count, _ = Machine.objects.all().delete()
        except ProtectedError:
            return Response(
                {"detail": "Không thể xóa: một số máy còn job liên kết. Hãy xóa/hoàn tất "
                           "các deployment liên quan trước."},
                status=status.HTTP_409_CONFLICT,
            )
        return Response(
            {"detail": f"Đã xóa {count} máy.", "deleted": count},
        )

    @action(detail=False, methods=["post"])
    def check_online(self, request):
        """Kiểm tra online toàn bộ máy (chạy nền — ping nhiều máy có thể lâu)."""
        task = check_all_online.delay()
        remember_task_owner(task.id, request.user.id)
        return Response(
            {"detail": "Đang kiểm tra online (chạy nền).", "task_id": task.id},
            status=status.HTTP_202_ACCEPTED,
        )

    @action(detail=False, methods=["get"])
    def export(self, request):
        """Xuất danh sách máy ra file CSV (Excel-compatible, UTF-8 BOM)."""
        qs = self._apply_filters(Machine.objects.all())
        buf = io.StringIO()
        # UTF-8 BOM để Excel tự nhận encoding
        buf.write("\ufeff")
        writer = csv.writer(buf)
        writer.writerow(["Hostname", "FQDN", "OS", "OU", "Trạng thái", "IP", "Lần cuối online"])
        for m in qs.iterator():
            writer.writerow([
                m.hostname,
                m.fqdn or "",
                m.os_name or "",
                m.ad_ou or "",
                "Online" if m.is_online else "Offline",
                m.ip_address or "",
                m.last_seen.strftime("%Y-%m-%d %H:%M") if m.last_seen else "",
            ])
        resp = HttpResponse(buf.getvalue(), content_type="text/csv; charset=utf-8")
        resp["Content-Disposition"] = 'attachment; filename="machines.csv"'
        return resp


class MachineGroupViewSet(viewsets.ModelViewSet):
    queryset = MachineGroup.objects.prefetch_related("machines").all()
    serializer_class = MachineGroupSerializer
    # Nhóm máy quyết định target của deployment → cùng cấp Tier-0 như Machine: mọi user
    # đọc được (để chọn target), chỉ admin tạo/sửa/xóa.
    permission_classes = [IsAdmin]


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
