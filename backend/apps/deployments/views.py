from django.db.models import Count, Q
from django.utils import timezone
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response

from apps.audit.models import AuditLog
from apps.jobs.models import JobStatus

from .models import Deployment, DeploymentStatus
from .orchestrator import cancel_deployment, launch_deployment
from .serializers import DeploymentSerializer


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

        job_count = launch_deployment(deployment)

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
