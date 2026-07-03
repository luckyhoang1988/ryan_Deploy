"""Celery tasks cấp deployment (khác apps/jobs/tasks.py là cấp từng job)."""
import logging

from celery import shared_task
from django.db import transaction
from django.utils import timezone

from .models import Deployment, DeploymentStatus
from .orchestrator import launch_deployment

logger = logging.getLogger("apps.deployments")


@shared_task
def trigger_scheduled_deployments():
    """
    Beat task (chạy mỗi phút): kích hoạt các deployment đã tới giờ hẹn.

    Quét deployment ở trạng thái SCHEDULED có `scheduled_at <= now`, claim từng cái
    một cách nguyên tử (đổi SCHEDULED→RUNNING bằng UPDATE có điều kiện) để tránh
    double-trigger nếu beat chạy chồng, rồi fan-out qua launch_deployment.
    """
    now = timezone.now()
    due_ids = list(
        Deployment.objects.filter(
            status=DeploymentStatus.SCHEDULED,
            scheduled_at__isnull=False,
            scheduled_at__lte=now,
        ).values_list("id", flat=True)
    )

    launched = 0
    for dep_id in due_ids:
        # Claim nguyên tử: chỉ đúng 1 tiến trình đổi được SCHEDULED→RUNNING.
        with transaction.atomic():
            claimed = (
                Deployment.objects.filter(id=dep_id, status=DeploymentStatus.SCHEDULED)
                .update(status=DeploymentStatus.RUNNING)
            )
        if not claimed:
            continue
        deployment = Deployment.objects.get(id=dep_id)
        count = launch_deployment(deployment)
        if count == 0:
            # Không có máy đích enabled → không có gì để chạy, đóng lại tránh kẹt RUNNING.
            deployment.status = DeploymentStatus.COMPLETED
            deployment.finished_at = timezone.now()
            deployment.save(update_fields=["status", "finished_at"])
        launched += 1
        logger.info("Đã kích hoạt deployment hẹn giờ %s (%s job)", dep_id, count)

    return {"launched": launched, "due": len(due_ids)}


@shared_task
def reconcile_stuck_deployments():
    """
    Beat task (mỗi 5 phút): lưới an toàn cho chord.

    Callback `finalize_deployment` chạy khi group job hoàn tất. Nếu nó KHÔNG chạy
    (worker chết giữa chừng, hoặc job bị revoke/terminate khi hủy làm vỡ chord),
    deployment sẽ kẹt ở RUNNING vĩnh viễn. Task này quét các deployment RUNNING mà
    MỌI job đã ở trạng thái kết thúc rồi gọi finalize để tổng kết lại.
    """
    from apps.jobs.models import Job, JobStatus
    from apps.jobs.tasks import finalize_deployment

    terminal = [
        JobStatus.SUCCESS,
        JobStatus.SUCCESS_REBOOT,
        JobStatus.FAILED,
        JobStatus.SKIPPED,
        JobStatus.CANCELLED,
    ]
    reconciled = 0
    for dep_id in Deployment.objects.filter(status=DeploymentStatus.RUNNING).values_list(
        "id", flat=True
    ):
        jobs = Job.objects.filter(deployment_id=dep_id)
        if not jobs.exists():
            continue  # vừa chuyển RUNNING, job chưa kịp tạo → để yên
        if jobs.exclude(status__in=terminal).exists():
            continue  # còn job đang chạy → chưa xong, không đụng
        finalize_deployment(None, dep_id)
        reconciled += 1
        logger.info("Reconcile: tổng kết lại deployment kẹt RUNNING %s", dep_id)

    return {"reconciled": reconciled}
