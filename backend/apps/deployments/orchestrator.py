"""
Orchestrator — fan-out một Deployment thành nhiều Job và đẩy song song.

Dùng Celery chord: group(deploy_to_machine cho mỗi máy) -> finalize_deployment.
Mức song song thực tế do worker concurrency quyết định
(docker-compose: --concurrency=${RYANDEPLOY_MAX_CONCURRENCY}).
"""
import logging

from celery import chord
from django.utils import timezone

from apps.jobs.models import Job, JobStatus
from apps.jobs.tasks import deploy_to_machine, finalize_deployment

from .models import DeploymentStatus
from .semaphore import clear_slots
from .targeting import resolve_targets

logger = logging.getLogger("apps.deployments")


def launch_deployment(deployment) -> int:
    """
    Tạo Job cho mỗi máy đích (idempotent) và enqueue chord.
    Trả về số job được đẩy vào hàng đợi.
    """
    # Áp targeting_rule (nếu có): vd chỉ cài lên máy CHƯA có phần mềm theo inventory.
    machines = resolve_targets(deployment)
    if not machines:
        return 0

    # Reset bộ đếm concurrency phòng khi còn sót từ lần chạy trước (re-trigger).
    clear_slots(deployment.id)

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
                # Reset bookkeeping từ lần chạy trước — thiếu bước này thì retrigger sau khi
                # đã hết retry_limit ở lượt trước sẽ kế thừa attempts cũ và mất hết lượt retry
                # ngay từ job đầu của lượt mới (job.attempts <= deployment.retry_limit ở
                # jobs/tasks.py so với giá trị cũ còn sót lại).
                "attempts": 0,
                "started_at": None,
                "celery_task_id": "",
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
    from ryandeploy.celery import app

    terminal = [
        JobStatus.SUCCESS,
        JobStatus.SUCCESS_REBOOT,
        JobStatus.FAILED,
        JobStatus.CANCELLED,
    ]
    pending = list(deployment.jobs.exclude(status__in=terminal))
    now = timezone.now()
    count = 0
    for job in pending:
        if job.celery_task_id:
            # terminate=True: giết cả job ĐANG cài dở (SIGTERM) chứ không chỉ chặn job
            # chưa khởi chạy — hủy deployment phải dừng được cài đặt đang diễn ra.
            app.control.revoke(job.celery_task_id, terminate=True)
        # UPDATE có điều kiện (không phải read-rồi-save) để không ghi đè job vừa được
        # _run_job chuyển sang SUCCESS/FAILED đúng lúc đang lặp qua danh sách này.
        count += Job.objects.filter(pk=job.pk).exclude(status__in=terminal).update(
            status=JobStatus.CANCELLED, finished_at=now
        )
    clear_slots(deployment.id)
    return count
