"""
Celery tasks — nối Django Job <-> PushExecutor (engine agentless).

deploy_to_machine(job_id): thực thi đẩy tới 1 máy.
finalize_deployment(_, deployment_id): tổng kết trạng thái deployment sau khi tất cả job xong.
"""
import logging

from celery import shared_task
from django.utils import timezone

from apps.executor import PushExecutor
from apps.executor.push_executor import ExecutorError

from .models import Job, JobStatus

logger = logging.getLogger("apps.jobs")

# Các step báo hiệu lỗi kết nối/tiền đề -> nên retry (khác lỗi installer)
_TRANSIENT_STEPS = {"precheck", "copy"}


@shared_task(bind=True, max_retries=5, acks_late=True)
def deploy_to_machine(self, job_id: int):
    try:
        job = Job.objects.select_related(
            "machine", "deployment__credential", "deployment__package_version"
        ).get(pk=job_id)
    except Job.DoesNotExist:
        logger.warning("Job %s không tồn tại", job_id)
        return {"job_id": job_id, "status": "missing"}

    if job.status == JobStatus.CANCELLED:
        return {"job_id": job_id, "status": "cancelled"}

    deployment = job.deployment
    machine = job.machine
    credential = deployment.credential
    pv = deployment.package_version

    job.status = JobStatus.RUNNING
    job.attempts += 1
    job.started_at = job.started_at or timezone.now()
    job.celery_task_id = self.request.id or ""
    job.save(update_fields=["status", "attempts", "started_at", "celery_task_id"])

    from apps.audit.models import AuditLog

    AuditLog.record(
        AuditLog.Action.JOB_START, target=job, machine_hostname=machine.hostname, attempt=job.attempts
    )

    # --- Phase 7: xác minh toàn vẹn installer trước khi đẩy (chống tamper) ---
    from apps.packages.repository import verify_integrity

    ok, actual = verify_integrity(pv)
    if not ok:
        job.status = JobStatus.FAILED
        job.error_output = (
            f"Toàn vẹn installer KHÔNG khớp — SHA-256 mong đợi {pv.sha256}, thực tế {actual}. "
            "Nghi ngờ file bị sửa đổi. Hủy đẩy."
        )
        job.current_step = "precheck"
        job.finished_at = timezone.now()
        job.save()
        logger.error("Integrity FAIL cho job %s (%s)", job_id, machine.hostname)
        return {"job_id": job_id, "status": "failed", "error": "integrity_mismatch"}

    def progress(step, message):
        # Cập nhật step hiện tại (nhẹ, chỉ 1 field)
        Job.objects.filter(pk=job.pk).update(current_step=step)

    executor = PushExecutor(
        host=machine.target_address,
        username=credential.username,
        password=credential.get_password(),
        domain=credential.domain,
        timeout=_job_timeout(),
        progress_cb=progress,
    )

    installer_path = pv.installer_file.path
    installer_filename = pv.installer_file.name.split("/")[-1]

    result = executor.run(
        local_installer_path=installer_path,
        installer_filename=installer_filename,
        install_command=pv.install_command,
        success_exit_codes=pv.success_exit_codes or [0, 3010],
        job_token=f"job{job.pk}",
    )

    # --- Ghi kết quả ---
    job.exit_code = result.exit_code
    job.output = "\n".join(result.log) + ("\n\n--- STDOUT ---\n" + result.stdout if result.stdout else "")
    job.error_output = result.error
    job.current_step = result.step_reached
    job.finished_at = timezone.now()

    if result.success:
        job.status = JobStatus.SUCCESS_REBOOT if result.needs_reboot else JobStatus.SUCCESS
        job.save()
        AuditLog.record(
            AuditLog.Action.JOB_FINISH,
            target=job,
            machine_hostname=machine.hostname,
            status=job.status,
            exit_code=result.exit_code,
        )
        return {"job_id": job_id, "status": job.status, "exit_code": result.exit_code}

    # --- Thất bại: quyết định retry ---
    transient = result.step_reached in _TRANSIENT_STEPS
    if transient and self.request.retries < deployment.retry_limit:
        job.status = JobStatus.QUEUED
        job.save()
        countdown = 30 * (2 ** self.request.retries)  # backoff 30s, 60s, 120s...
        logger.info("Retry job %s sau %ss (transient: %s)", job_id, countdown, result.error)
        raise self.retry(countdown=countdown, exc=ExecutorError(result.error))

    job.status = JobStatus.FAILED
    job.save()
    AuditLog.record(
        AuditLog.Action.JOB_FINISH,
        target=job,
        machine_hostname=machine.hostname,
        status=job.status,
        error=result.error[:500],
    )
    return {"job_id": job_id, "status": "failed", "error": result.error}


@shared_task
def finalize_deployment(_results, deployment_id: int):
    """Callback chord: tổng kết trạng thái deployment."""
    from apps.deployments.models import Deployment, DeploymentStatus

    try:
        deployment = Deployment.objects.get(pk=deployment_id)
    except Deployment.DoesNotExist:
        return

    failed = deployment.failed_count
    success = deployment.success_count

    if failed == 0:
        deployment.status = DeploymentStatus.COMPLETED
    elif success == 0:
        deployment.status = DeploymentStatus.FAILED
    else:
        deployment.status = DeploymentStatus.COMPLETED_WITH_ERRORS

    deployment.finished_at = timezone.now()
    deployment.save(update_fields=["status", "finished_at"])
    logger.info(
        "Deployment %s xong: %s thành công / %s thất bại", deployment_id, success, failed
    )


def _job_timeout() -> int:
    from django.conf import settings

    return settings.PYDEPLOY.get("JOB_TIMEOUT", 1800)
