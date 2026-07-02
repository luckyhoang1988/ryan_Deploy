"""
Orchestrator — fan-out một Deployment thành nhiều Job và đẩy song song.

Dùng Celery chord: group(deploy_to_machine cho mỗi máy) -> finalize_deployment.
Mức song song thực tế do worker concurrency quyết định
(docker-compose: --concurrency=${PYDEPLOY_MAX_CONCURRENCY}).
"""
import logging

from celery import chord
from django.utils import timezone

from apps.jobs.models import Job, JobStatus
from apps.jobs.tasks import deploy_to_machine, finalize_deployment

from .models import DeploymentStatus

logger = logging.getLogger("apps.deployments")


def launch_deployment(deployment) -> int:
    """
    Tạo Job cho mỗi máy đích (idempotent) và enqueue chord.
    Trả về số job được đẩy vào hàng đợi.
    """
    machines = list(deployment.target_machines.filter(enabled=True))
    if not machines:
        return 0

    # Tạo/khởi tạo lại Job cho từng máy
    job_ids = []
    for machine in machines:
        job, _ = Job.objects.update_or_create(
            deployment=deployment,
            machine=machine,
            defaults={
                "status": JobStatus.QUEUED,
                "exit_code": None,
                "output": "",
                "error_output": "",
                "current_step": "",
                "finished_at": None,
            },
        )
        job_ids.append(job.pk)

    deployment.status = DeploymentStatus.RUNNING
    deployment.started_at = timezone.now()
    deployment.finished_at = None
    deployment.save(update_fields=["status", "started_at", "finished_at"])

    # Fan-out song song + callback tổng kết
    header = [deploy_to_machine.s(jid) for jid in job_ids]
    chord(header)(finalize_deployment.s(deployment.id))

    logger.info("Deployment %s: đẩy %s job", deployment.id, len(job_ids))
    return len(job_ids)


def cancel_deployment(deployment) -> int:
    """Đánh dấu các job chưa kết thúc là CANCELLED và revoke task."""
    from pydeploy.celery import app

    pending = deployment.jobs.exclude(
        status__in=[
            JobStatus.SUCCESS,
            JobStatus.SUCCESS_REBOOT,
            JobStatus.FAILED,
            JobStatus.CANCELLED,
        ]
    )
    count = 0
    for job in pending:
        if job.celery_task_id:
            app.control.revoke(job.celery_task_id, terminate=False)
        job.status = JobStatus.CANCELLED
        job.finished_at = timezone.now()
        job.save(update_fields=["status", "finished_at"])
        count += 1
    return count
