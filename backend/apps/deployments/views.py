from django.utils import timezone
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response

from apps.audit.models import AuditLog

from .models import Deployment, DeploymentStatus
from .orchestrator import cancel_deployment, launch_deployment
from .serializers import DeploymentSerializer


class DeploymentViewSet(viewsets.ModelViewSet):
    queryset = Deployment.objects.select_related("package_version__package", "credential").all()
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
