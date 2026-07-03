import logging

from django.db.models import Count, Q
from django.utils import timezone
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.throttling import ScopedRateThrottle

from apps.audit.models import AuditLog
from apps.core.permissions import ROLE_ADMIN, has_role
from apps.jobs.models import JobStatus

from .models import Deployment, DeploymentAction, DeploymentStatus
from .orchestrator import cancel_deployment, launch_deployment
from .serializers import DeploymentSerializer

# Action phá hoại cao (reboot/shutdown cả fleet) — chỉ admin được kích hoạt.
_ADMIN_ONLY_ACTIONS = (DeploymentAction.REBOOT, DeploymentAction.SHUTDOWN)

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

    @action(detail=True, methods=["post"])
    def trigger(self, request, pk=None):
        """Kích hoạt deployment: fan-out thành các job và đẩy song song."""
        deployment = self.get_object()

        if deployment.action in _ADMIN_ONLY_ACTIONS and not has_role(request.user, ROLE_ADMIN):
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
        cancel_deployment(deployment)
        deployment.status = DeploymentStatus.CANCELLED
        deployment.finished_at = timezone.now()
        deployment.save(update_fields=["status", "finished_at"])
        AuditLog.record(
            AuditLog.Action.DEPLOYMENT_CANCEL, user=request.user, target=deployment
        )
        return Response({"detail": "Đã hủy."}, status=status.HTTP_200_OK)
