import csv
import io
from datetime import timedelta

from django.db.models import ProtectedError
from django.http import HttpResponse
from django.utils import timezone
from django.utils.dateparse import parse_datetime
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.agents.models import AgentToken, EnrollmentSecret
from apps.agents.services import issue_enrollment_secret, issue_token, revoke_enrollment_secret, revoke_token
from apps.audit.models import AuditLog
from apps.core.permissions import IsAdmin, IsViewerOrAbove
from apps.core.task_registry import remember_task_owner

from .ad_sync import test_ad_connection
from .models import ADConfig, ConnectionMode, Machine, MachineGroup
from .serializers import (
    ADConfigSerializer,
    EnrollmentSecretSerializer,
    MachineDetailSerializer,
    MachineGroupSerializer,
    MachineSerializer,
)
from .tasks import sync_from_ad


class MachineViewSet(viewsets.ModelViewSet):
    queryset = Machine.objects.all()
    serializer_class = MachineSerializer
    filterset_fields = ["is_online", "enabled", "ad_ou"]
    # Mặc định chỉ admin được sửa danh sách máy / sync AD (Tier-0).
    permission_classes = [IsAdmin]

    def get_permissions(self):
        # stats, export chỉ đọc → operator cũng được.
        if self.action in ("stats", "export"):
            return [IsViewerOrAbove()]
        return super().get_permissions()

    def get_serializer_class(self):
        # Chỉ detail (retrieve) trả kèm trạng thái token agent — tránh N+1 query khi list.
        if self.action == "retrieve":
            return MachineDetailSerializer
        return super().get_serializer_class()

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
        # Máy bị disable không còn agent heartbeat/mark_stale_machines_offline nào chạm tới
        # → is_online cũ sẽ đứng hình mãi mãi, sai lệch thống kê online/offline. Xóa ngay lúc tắt.
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
        """
        Xóa tất cả máy trong DB (reset trước khi sync lại với OU mới).

        Vì AgentToken.machine là on_delete=CASCADE, xóa máy sẽ xóa luôn token agent → mọi agent
        đang chạy sẽ kẹt 401 vĩnh viễn (không tự re-enroll). Nên nếu còn token agent active mà
        client chưa gửi force=true, ta CHẶN và trả cảnh báo số agent bị ảnh hưởng để admin xác
        nhận có chủ đích, tránh vô tình giết toàn bộ agent như sự cố 2026-07-09.
        """
        force = bool(request.data.get("force"))
        active_tokens = AgentToken.objects.filter(revoked_at__isnull=True).count()
        if active_tokens and not force:
            return Response(
                {
                    "detail": f"Còn {active_tokens} máy đang có token agent active. Xóa máy sẽ "
                              f"xóa luôn token (CASCADE) khiến các agent này kẹt 401 và KHÔNG tự "
                              f"đăng ký lại — phải cài lại agent hoặc xóa token thủ công trên máy. "
                              f"Gửi lại với force=true nếu thực sự muốn xóa.",
                    "agent_tokens_affected": active_tokens,
                    "requires_force": True,
                },
                status=status.HTTP_409_CONFLICT,
            )
        machines_before = Machine.objects.count()
        try:
            count, _ = Machine.objects.all().delete()
        except ProtectedError:
            return Response(
                {"detail": "Không thể xóa: một số máy còn job liên kết. Hãy xóa/hoàn tất "
                           "các deployment liên quan trước."},
                status=status.HTTP_409_CONFLICT,
            )
        # Audit: đây là hành động Tier-0 phá hủy (đã giết toàn bộ agent hôm 2026-07-09).
        # Ghi lại ai đã ép force để xóa cả khi còn token agent active → có dấu vết truy vết.
        AuditLog.record(
            AuditLog.Action.MACHINE_PURGE_ALL,
            user=request.user,
            machines_before=machines_before,
            objects_deleted=count,
            agent_tokens_destroyed=active_tokens,
            forced=force,
        )
        return Response(
            {"detail": f"Đã xóa {count} máy.", "deleted": count, "agent_tokens_destroyed": active_tokens},
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

    @action(detail=True, methods=["post"], permission_classes=[IsAdmin])
    def provision_agent_token(self, request, pk=None):
        """Cấp (hoặc xoay) token agent cho máy — hiển thị token gốc đúng 1 lần, không lấy lại được."""
        machine = self.get_object()
        raw = issue_token(machine, request.user)
        AuditLog.record(
            AuditLog.Action.AGENT_TOKEN_ISSUE, user=request.user,
            target=machine, machine_hostname=machine.hostname,
        )
        return Response({"token": raw}, status=status.HTTP_201_CREATED)

    @action(detail=True, methods=["post"], permission_classes=[IsAdmin])
    def revoke_agent_token(self, request, pk=None):
        """Thu hồi token agent hiện tại của máy (nếu có)."""
        machine = self.get_object()
        revoked = revoke_token(machine)
        if revoked:
            AuditLog.record(
                AuditLog.Action.AGENT_TOKEN_REVOKE, user=request.user,
                target=machine, machine_hostname=machine.hostname,
            )
        return Response({"revoked": revoked})

    @action(detail=False, methods=["post"], url_path="bulk-provision-agent-tokens", permission_classes=[IsAdmin])
    def bulk_provision_agent_tokens(self, request):
        """
        Cấp token agent hàng loạt theo danh sách machine_ids hoặc filter ad_ou — dùng khi rollout
        agent theo OU. Trả CSV hostname,token để đưa vào GPO startup script.
        """
        machine_ids = request.data.get("machine_ids")
        ad_ou = (request.data.get("ad_ou") or "").strip()
        qs = Machine.objects.filter(enabled=True)
        if machine_ids:
            qs = qs.filter(pk__in=machine_ids)
        elif ad_ou:
            qs = qs.filter(ad_ou__icontains=ad_ou)
        else:
            return Response(
                {"detail": "Cần truyền machine_ids hoặc ad_ou."}, status=status.HTTP_400_BAD_REQUEST,
            )

        machines = list(qs)
        buf = io.StringIO()
        writer = csv.writer(buf)
        writer.writerow(["hostname", "token"])
        for machine in machines:
            raw = issue_token(machine, request.user)
            writer.writerow([machine.hostname, raw])
        AuditLog.record(
            AuditLog.Action.AGENT_TOKEN_ISSUE, user=request.user,
            count=len(machines), bulk=True,
        )
        resp = HttpResponse(buf.getvalue(), content_type="text/csv; charset=utf-8")
        resp["Content-Disposition"] = 'attachment; filename="agent_tokens.csv"'
        return resp

    @action(detail=False, methods=["post"], url_path="bulk-set-connection-mode", permission_classes=[IsAdmin])
    def bulk_set_connection_mode(self, request):
        """
        Đổi connection_mode hàng loạt theo machine_ids hoặc filter ad_ou — dùng khi mở rộng
        rollout agent theo OU (plan_agent.md §8) sau khi đã xác nhận agent poll thành công qua
        last_used_at/heartbeat. Không tự cấp token — dùng bulk_provision_agent_tokens riêng.
        """
        mode = request.data.get("connection_mode")
        if mode not in ConnectionMode.values:
            return Response(
                {"detail": f"connection_mode phải là một trong: {', '.join(ConnectionMode.values)}."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        machine_ids = request.data.get("machine_ids")
        ad_ou = (request.data.get("ad_ou") or "").strip()
        qs = Machine.objects.all()
        if machine_ids:
            qs = qs.filter(pk__in=machine_ids)
        elif ad_ou:
            qs = qs.filter(ad_ou__icontains=ad_ou)
        else:
            return Response(
                {"detail": "Cần truyền machine_ids hoặc ad_ou."}, status=status.HTTP_400_BAD_REQUEST,
            )

        updated = qs.update(connection_mode=mode)
        AuditLog.record(
            AuditLog.Action.MACHINE_CONNECTION_MODE_UPDATE, user=request.user,
            connection_mode=mode, count=updated,
        )
        return Response({"updated": updated, "connection_mode": mode})


class MachineGroupViewSet(viewsets.ModelViewSet):
    queryset = MachineGroup.objects.prefetch_related("machines").all()
    serializer_class = MachineGroupSerializer
    # Nhóm máy quyết định target của deployment → cùng cấp Tier-0 như Machine: mọi user
    # đọc được (để chọn target), chỉ admin tạo/sửa/xóa.
    permission_classes = [IsAdmin]


class EnrollmentSecretViewSet(viewsets.ModelViewSet):
    """
    Quản lý secret dùng chung cho self-enrollment hàng loạt (thay thế cấp token thủ công
    từng máy khi rollout ~1000 PC). Bất biến sau khi tạo — chỉ list/retrieve/create/revoke,
    không update.
    """

    queryset = EnrollmentSecret.objects.select_related("created_by").all()
    serializer_class = EnrollmentSecretSerializer
    permission_classes = [IsAdmin]
    http_method_names = ["get", "post", "head", "options"]

    def create(self, request, *args, **kwargs):
        ad_ou = (request.data.get("ad_ou") or "").strip()
        note = (request.data.get("note") or "").strip()

        never_expires = bool(request.data.get("never_expires"))

        expires_at = request.data.get("expires_at")
        expires_in_hours = request.data.get("expires_in_hours")
        if expires_at:
            expires_at = parse_datetime(str(expires_at))
            if expires_at is None:
                return Response({"detail": "expires_at không hợp lệ (ISO 8601)."}, status=status.HTTP_400_BAD_REQUEST)
        elif expires_in_hours:
            try:
                hours = float(expires_in_hours)
                if hours <= 0:
                    raise ValueError
            except (TypeError, ValueError):
                return Response({"detail": "expires_in_hours phải là số dương."}, status=status.HTTP_400_BAD_REQUEST)
            expires_at = timezone.now() + timedelta(hours=hours)
        elif never_expires:
            expires_at = None
        else:
            return Response(
                {"detail": "Cần truyền expires_at, expires_in_hours, hoặc never_expires=true."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        max_uses = request.data.get("max_uses") or None
        if max_uses is not None:
            try:
                max_uses = int(max_uses)
                if max_uses <= 0:
                    raise ValueError
            except (TypeError, ValueError):
                return Response(
                    {"detail": "max_uses phải là số nguyên dương."}, status=status.HTTP_400_BAD_REQUEST,
                )

        raw, secret = issue_enrollment_secret(
            ad_ou, expires_at, max_uses=max_uses, user=request.user, note=note,
        )
        AuditLog.record(
            AuditLog.Action.AGENT_ENROLLMENT_SECRET_CREATE, user=request.user,
            ad_ou=ad_ou or "global",
            expires_at=expires_at.isoformat() if expires_at else "never",
            max_uses=max_uses,
        )
        data = EnrollmentSecretSerializer(secret).data
        data["secret"] = raw
        return Response(data, status=status.HTTP_201_CREATED)

    @action(detail=True, methods=["post"])
    def revoke(self, request, pk=None):
        secret = self.get_object()
        revoked = revoke_enrollment_secret(secret)
        if revoked:
            AuditLog.record(
                AuditLog.Action.AGENT_ENROLLMENT_SECRET_REVOKE, user=request.user,
                ad_ou=secret.ad_ou or "global", secret_prefix=secret.secret_prefix,
            )
        return Response({"revoked": revoked})


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
