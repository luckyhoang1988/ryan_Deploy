import logging

from django.db import transaction
from django.db.models import Count, Q
from django.utils import timezone
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import ValidationError
from rest_framework.response import Response
from rest_framework.throttling import ScopedRateThrottle

from apps.audit.models import AuditLog
from apps.core.permissions import ROLE_ADMIN, IsOperatorOrAbove, has_role
from apps.jobs.models import JobStatus

from .models import ADMIN_ONLY_ACTIONS, Deployment, DeploymentSchedule, DeploymentStatus
from .orchestrator import cancel_deployment, launch_deployment
from .serializers import DeploymentScheduleSerializer, DeploymentSerializer

logger = logging.getLogger("apps.deployments")


class DeploymentViewSet(viewsets.ModelViewSet):
    # Đếm trạng thái job bằng annotate (1 query cho cả list) thay vì 4 property/deployment
    # → tránh N+1. prefetch target_machines vì serializer trả danh sách máy đích.
    queryset = (
        Deployment.objects.select_related("package_version__package", "credential")
        .prefetch_related("target_machines")
        .annotate(
            n_total=Count("jobs"),
            n_success=Count(
                "jobs",
                filter=Q(jobs__status__in=[JobStatus.SUCCESS, JobStatus.SUCCESS_REBOOT]),
            ),
            n_failed=Count("jobs", filter=Q(jobs__status=JobStatus.FAILED)),
            n_pending=Count(
                "jobs",
                filter=Q(
                    jobs__status__in=[JobStatus.PENDING, JobStatus.QUEUED, JobStatus.RUNNING]
                ),
            ),
        )
        # annotate thêm GROUP BY khiến queryset mất thứ tự ngầm định → chỉ định rõ để
        # pagination ổn định (tránh UnorderedObjectListWarning).
        .order_by("-created_at")
    )
    serializer_class = DeploymentSerializer

    def get_queryset(self):
        # ?status=running — dùng cho panel "Đang chạy" toàn cục (Layout.jsx).
        qs = super().get_queryset()
        status_param = self.request.query_params.get("status")
        if status_param:
            qs = qs.filter(status=status_param)
        return qs

    def get_throttles(self):
        # Chống spam các action ghi/tốn kém (trigger/cancel có thể đẩy hàng trăm máy).
        # Các action đọc khác không giới hạn thêm (ngoài throttle mặc định).
        if self.action in ("trigger", "cancel"):
            self.throttle_scope = "deployment_action"
            return [ScopedRateThrottle()]
        return super().get_throttles()

    def perform_create(self, serializer):
        deployment = serializer.save()
        AuditLog.record(
            AuditLog.Action.DEPLOYMENT_CREATE,
            user=self.request.user,
            target=deployment,
            name=deployment.name,
        )

    def perform_update(self, serializer):
        # Không cho sửa deployment đang chạy (cấu hình đang được orchestrator dùng).
        if serializer.instance.status == DeploymentStatus.RUNNING:
            raise ValidationError(
                "Không thể sửa deployment đang chạy. Hãy hủy (cancel) trước."
            )
        deployment = serializer.save()
        AuditLog.record(
            AuditLog.Action.DEPLOYMENT_UPDATE,
            user=self.request.user,
            target=deployment,
            name=deployment.name,
        )

    def perform_destroy(self, instance):
        # Chặn xóa khi đang chạy — job đang đẩy tới máy, xóa sẽ bỏ rơi tác vụ nền.
        if instance.status == DeploymentStatus.RUNNING:
            raise ValidationError(
                "Không thể xóa deployment đang chạy. Hãy hủy (cancel) trước rồi xóa."
            )
        name = instance.name
        saved_pk = instance.pk
        instance.delete()  # Job liên quan CASCADE tự xóa theo.
        instance.pk = saved_pk  # giữ target_id cho bản ghi audit sau khi delete()
        AuditLog.record(
            AuditLog.Action.DEPLOYMENT_DELETE,
            user=self.request.user,
            target=instance,
            name=name,
        )

    @action(detail=True, methods=["post"])
    def trigger(self, request, pk=None):
        """Kích hoạt deployment: fan-out thành các job và đẩy song song."""
        deployment = self.get_object()

        if deployment.action in ADMIN_ONLY_ACTIONS and not has_role(request.user, ROLE_ADMIN):
            return Response(
                {"detail": "Chỉ admin được kích hoạt reboot/shutdown."},
                status=status.HTTP_403_FORBIDDEN,
            )

        if deployment.status == DeploymentStatus.RUNNING:
            return Response(
                {"detail": "Deployment đang chạy."}, status=status.HTTP_409_CONFLICT
            )
        if deployment.target_machines.count() == 0:
            return Response(
                {"detail": "Chưa có máy đích nào."}, status=status.HTTP_400_BAD_REQUEST
            )

        # Có lịch hẹn ở tương lai → chỉ đánh dấu SCHEDULED, beat task sẽ tự kích hoạt
        # (apps.deployments.tasks.trigger_scheduled_deployments).
        if deployment.scheduled_at and deployment.scheduled_at > timezone.now():
            deployment.status = DeploymentStatus.SCHEDULED
            deployment.save(update_fields=["status"])
            AuditLog.record(
                AuditLog.Action.DEPLOYMENT_TRIGGER,
                user=request.user,
                target=deployment,
                scheduled_at=deployment.scheduled_at.isoformat(),
            )
            return Response(
                {
                    "detail": "Đã lên lịch.",
                    "scheduled_at": deployment.scheduled_at.isoformat(),
                    "status": deployment.status,
                },
                status=status.HTTP_202_ACCEPTED,
            )

        # Claim nguyên tử: chỉ đúng 1 request đổi được trạng thái sang RUNNING. Chặn race
        # 2 request POST /trigger/ đồng thời (double-click) cùng vượt qua check ở trên rồi
        # cùng gọi launch_deployment → chord kép cho cùng 1 deployment.
        with transaction.atomic():
            claimed = (
                Deployment.objects.filter(pk=deployment.pk)
                .exclude(status=DeploymentStatus.RUNNING)
                .update(status=DeploymentStatus.RUNNING, started_at=timezone.now())
            )
        if not claimed:
            return Response(
                {"detail": "Deployment đang chạy."}, status=status.HTTP_409_CONFLICT
            )
        deployment.refresh_from_db()

        # launch_deployment có thể ném lỗi (broker/DB) sau khi đã đặt RUNNING → revert
        # về FAILED để không kẹt, và báo lỗi rõ cho client thay vì 500 trần trụi.
        try:
            job_count = launch_deployment(deployment)
        except Exception:
            logger.exception("launch_deployment lỗi cho %s (trigger thủ công)", deployment.id)
            deployment.status = DeploymentStatus.FAILED
            deployment.finished_at = timezone.now()
            deployment.save(update_fields=["status", "finished_at"])
            return Response(
                {"detail": "Không kích hoạt được deployment (lỗi hệ thống)."},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

        AuditLog.record(
            AuditLog.Action.DEPLOYMENT_TRIGGER,
            user=request.user,
            target=deployment,
            job_count=job_count,
        )

        if job_count == 0:
            # resolve_targets() (áp targeting_rule) lọc hết máy đích — không có gì để chạy.
            # Đóng lại tránh kẹt ở trạng thái trước đó, và báo rõ thay vì "Đã kích hoạt."
            # gây hiểu lầm với jobs: 0 (giống correction đã có ở beat path — tasks.py).
            deployment.status = DeploymentStatus.COMPLETED
            deployment.finished_at = timezone.now()
            deployment.save(update_fields=["status", "finished_at"])
            return Response(
                {
                    "detail": "Không có máy đích hợp lệ sau khi áp targeting rule — không có job nào được tạo.",
                    "jobs": 0,
                    "status": deployment.status,
                },
                status=status.HTTP_200_OK,
            )

        return Response(
            {"detail": "Đã kích hoạt.", "jobs": job_count, "status": deployment.status},
            status=status.HTTP_202_ACCEPTED,
        )

    @action(detail=True, methods=["get"])
    def preview_targets(self, request, pk=None):
        """Xem trước danh sách máy sẽ chạy sau khi áp targeting_rule (Phase 3)."""
        from .targeting import resolve_targets

        deployment = self.get_object()
        machines = resolve_targets(deployment)
        return Response(
            {
                "count": len(machines),
                "machines": [{"id": m.id, "hostname": m.hostname} for m in machines],
            }
        )

    @action(detail=True, methods=["post"])
    def cancel(self, request, pk=None):
        deployment = self.get_object()
        # Claim nguyên tử: chỉ đúng 1 request đổi được SCHEDULED/RUNNING → CANCELLED, tránh
        # hủy 2 lần chồng chéo hoặc hủy đúng lúc finalize_deployment đang tổng kết.
        with transaction.atomic():
            claimed = (
                Deployment.objects.filter(
                    pk=deployment.pk,
                    status__in=[DeploymentStatus.SCHEDULED, DeploymentStatus.RUNNING],
                ).update(status=DeploymentStatus.CANCELLED, finished_at=timezone.now())
            )
        deployment.refresh_from_db()
        if not claimed:
            return Response(
                {
                    "detail": f"Không thể hủy deployment ở trạng thái "
                              f"'{deployment.get_status_display()}'."
                },
                status=status.HTTP_409_CONFLICT,
            )
        cancel_deployment(deployment)
        AuditLog.record(
            AuditLog.Action.DEPLOYMENT_CANCEL, user=request.user, target=deployment
        )
        return Response({"detail": "Đã hủy."}, status=status.HTTP_200_OK)


class DeploymentScheduleViewSet(viewsets.ModelViewSet):
    """
    Lịch lặp (recurring/repeating) — CRUD. Kích hoạt thật do beat task
    `apps.deployments.tasks.trigger_due_schedules` xử lý, không có action thủ công ở đây.
    """

    queryset = (
        DeploymentSchedule.objects.select_related("package_version__package", "credential")
        .prefetch_related("target_machines")
        .order_by("-created_at")
    )
    serializer_class = DeploymentScheduleSerializer
    permission_classes = [IsOperatorOrAbove]

    @staticmethod
    def _check_admin_only_action(user, action):
        # Cùng ràng buộc như DeploymentViewSet.trigger: reboot/shutdown lặp lại tự động
        # trên cả fleet rủi ro cao hơn cả kích hoạt thủ công → chỉ admin được cấu hình.
        if action in ADMIN_ONLY_ACTIONS and not has_role(user, ROLE_ADMIN):
            raise ValidationError(
                {"action": "Chỉ admin được tạo/sửa lịch lặp reboot/shutdown."}
            )

    def perform_create(self, serializer):
        self._check_admin_only_action(self.request.user, serializer.validated_data.get("action"))
        schedule = serializer.save()
        AuditLog.record(
            AuditLog.Action.SCHEDULE_CREATE, user=self.request.user, target=schedule, name=schedule.name
        )

    def perform_update(self, serializer):
        action_value = serializer.validated_data.get("action") or serializer.instance.action
        self._check_admin_only_action(self.request.user, action_value)
        schedule = serializer.save()
        AuditLog.record(
            AuditLog.Action.SCHEDULE_UPDATE, user=self.request.user, target=schedule, name=schedule.name
        )

    def perform_destroy(self, instance):
        name = instance.name
        saved_pk = instance.pk
        instance.delete()
        instance.pk = saved_pk  # giữ target_id cho bản ghi audit sau khi delete()
        AuditLog.record(
            AuditLog.Action.SCHEDULE_DELETE, user=self.request.user, target=instance, name=name
        )
