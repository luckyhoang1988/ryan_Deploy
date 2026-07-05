"""
Celery tasks — nối Django Job <-> PushExecutor (engine agentless).

deploy_to_machine(job_id): thực thi đẩy tới 1 máy.
finalize_deployment(_, deployment_id): tổng kết trạng thái deployment sau khi tất cả job xong.
"""
import logging

from celery import shared_task
from django.utils import timezone

from apps.core.realtime.broadcast import broadcast_job_step
from apps.executor import PushExecutor
from apps.executor.push_executor import ExecutorError

from .models import Job, JobStatus

logger = logging.getLogger("apps.jobs")

# Các step báo hiệu lỗi kết nối/tiền đề -> nên retry (khác lỗi installer)
_TRANSIENT_STEPS = {"precheck", "copy"}


# max_retries=None: self.retry còn dùng để CHỜ slot concurrency (semaphore), không chỉ
# để retry lỗi. Số lần retry vì lỗi thật được kiểm soát riêng qua job.attempts, nên không
# đặt trần cứng ở đây (semaphore đảm bảo luôn tiến triển: slot sẽ giải phóng khi job xong).
@shared_task(bind=True, max_retries=None, acks_late=True)
def deploy_to_machine(self, job_id: int):
    from apps.deployments.semaphore import acquire_slot, release_slot

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

    # --- Giới hạn concurrency per-deployment: xin 1 slot, đầy thì chờ ---
    ttl = _job_timeout() + 300
    if not acquire_slot(deployment.id, deployment.max_concurrency, ttl):
        logger.debug("Job %s chờ slot (max_concurrency=%s)", job_id, deployment.max_concurrency)
        raise self.retry(countdown=5)

    try:
        return _run_job(self, job, deployment, machine, credential, pv)
    finally:
        release_slot(deployment.id)


def _run_job(self, job, deployment, machine, credential, pv):
    job_id = job.pk
    job.status = JobStatus.RUNNING
    job.attempts += 1
    job.started_at = job.started_at or timezone.now()
    job.celery_task_id = self.request.id or ""
    job.save(update_fields=["status", "attempts", "started_at", "celery_task_id"])

    from apps.audit.models import AuditLog

    AuditLog.record(
        AuditLog.Action.JOB_START, target=job, machine_hostname=machine.hostname, attempt=job.attempts
    )

    # --- Dựng kế hoạch chạy theo loại action (install/uninstall/reboot/shutdown/inventory) ---
    from apps.deployments.actions import build_action_plan

    plan = build_action_plan(deployment, machine)

    # --- Phase 7: xác minh toàn vẹn installer trước khi đẩy (chống tamper) ---
    # Chỉ áp dụng khi tác vụ thực sự đẩy installer (install, uninstall-có-{file}).
    if plan.verify_installer:
        from apps.packages.repository import verify_integrity

        try:
            ok, actual = verify_integrity(pv)
        except OSError as e:
            # File installer thiếu/không đọc được trên đĩa server — không để lỗi này thoát
            # khỏi Celery task (sẽ crash task, kẹt deployment RUNNING vĩnh viễn).
            job.status = JobStatus.FAILED
            job.error_output = f"Không đọc được file installer để xác minh toàn vẹn: {e}"
            job.current_step = "precheck"
            job.finished_at = timezone.now()
            job.save()
            logger.error("Integrity check lỗi đọc file cho job %s (%s): %s", job_id, machine.hostname, e)
            return {"job_id": job_id, "status": "failed", "error": "integrity_file_missing"}
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
        # Cập nhật step hiện tại (nhẹ, chỉ 1 field) — dùng update() nên KHÔNG kích hoạt
        # post_save signal (signals.py), phải broadcast tường minh ở đây.
        Job.objects.filter(pk=job.pk).update(current_step=step)
        broadcast_job_step(job.pk, deployment.id, step)

    def is_cancelled():
        # Poll trạng thái CANCELLED giữa các bước (đặc biệt trong vòng chờ collect dài) để
        # dừng đẩy hợp tác — bổ sung cho revoke(terminate) vốn không chắc dừng sạch.
        return Job.objects.filter(pk=job.pk, status=JobStatus.CANCELLED).exists()

    # Factory: dùng cho lần chạy chính và lần hậu kiểm (mỗi lần 1 instance sạch, tránh
    # gộp log giữa hai lần chạy). Giải mã mật khẩu 1 lần.
    cred_password = credential.get_password()

    def make_executor(progress_cb=progress):
        return PushExecutor(
            host=machine.target_address,
            username=credential.username,
            password=cred_password,
            domain=credential.domain,
            timeout=_job_timeout(),
            progress_cb=progress_cb,
            cancel_check=is_cancelled,
        )

    executor = make_executor()

    result = executor.run(
        plan.command,
        local_payload_path=plan.payload_path,
        payload_filename=plan.payload_filename,
        success_exit_codes=plan.success_exit_codes,
        job_token=f"job{job.pk}",
    )

    # Bị hủy giữa chừng (cancel_check kích hoạt hoặc revoke đặt CANCELLED) → giữ nguyên
    # CANCELLED, KHÔNG ghi đè FAILED cũng không retry. Đọc lại trạng thái mới nhất từ DB.
    job.refresh_from_db(fields=["status"])
    if job.status == JobStatus.CANCELLED:
        logger.info("Job %s bị hủy trong lúc chạy — dừng", job_id)
        return {"job_id": job_id, "status": "cancelled"}

    # --- Ghi kết quả ---
    job.exit_code = result.exit_code
    job.output = "\n".join(result.log) + ("\n\n--- STDOUT ---\n" + result.stdout if result.stdout else "")
    job.error_output = result.error
    job.current_step = result.step_reached
    job.finished_at = timezone.now()

    if result.success:
        # Hậu xử lý theo action (vd inventory: parse stdout → lưu InstalledSoftware).
        # Không để lỗi post-hook làm hỏng kết quả job đã chạy thành công.
        if plan.post_hook:
            try:
                plan.post_hook(machine, result)
            except Exception as e:  # noqa: BLE001
                logger.warning("post_hook lỗi cho job %s (%s): %s", job_id, machine.hostname, e)

        # --- Hậu kiểm cài đặt (chống "false success": installer trả 0 nhưng không cài) ---
        verify_err = _verify_install(make_executor, plan, job)
        if verify_err:
            job.status = JobStatus.FAILED
            job.error_output = verify_err
            job.current_step = "verify"
            job.save()
            AuditLog.record(
                AuditLog.Action.JOB_FINISH,
                target=job,
                machine_hostname=machine.hostname,
                status=job.status,
                error=verify_err[:500],
            )
            logger.warning("Hậu kiểm FAIL job %s (%s): %s", job_id, machine.hostname, verify_err)
            return {"job_id": job_id, "status": "failed", "error": "verify_failed"}

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
    # Đếm số lần thử THẬT qua job.attempts (không dùng self.request.retries vì retries
    # còn tính cả những lần chờ slot concurrency, không phải lỗi thật).
    # result.retryable=False cho lỗi chắc chắn không tự khỏi (vd sai credential) → không retry.
    transient = result.step_reached in _TRANSIENT_STEPS and result.retryable
    if transient and job.attempts <= deployment.retry_limit:
        job.status = JobStatus.QUEUED
        job.save()
        countdown = 30 * (2 ** (job.attempts - 1))  # backoff 30s, 60s, 120s...
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


def _verify_install(make_executor, plan, job):
    """
    Hậu kiểm sau khi install/uninstall báo thành công — kiểm registry Uninstall có/không
    có phần mềm. Trả None nếu bỏ qua hoặc ĐẠT; trả chuỗi lỗi nếu KHÔNG đạt (false-success).

    Thận trọng: nếu bước hậu kiểm không chạy tới nơi (lỗi SMB/precheck → exit_code None),
    KHÔNG kết luận — giữ nguyên thành công, chỉ log (tránh biến install thật thành thất bại
    vì trục trặc kết nối lúc kiểm).
    """
    if not plan.verify_name:
        return None
    from apps.deployments.actions import VERIFY_SCRIPT_PATH

    name = plan.verify_name.replace('"', "")  # tránh vỡ tham số PowerShell
    present = "1" if plan.verify_present else "0"
    command = (
        f'powershell -NoProfile -ExecutionPolicy Bypass -File "{{file}}" '
        f'-Name "{name}" -Present {present}'
    )
    verifier = make_executor(progress_cb=None)  # giữ step "verify", không ghi đè bằng step nội bộ
    vres = verifier.run(
        command,
        local_payload_path=VERIFY_SCRIPT_PATH,
        payload_filename="ryandeploy_verify.ps1",
        success_exit_codes=[0],
        job_token=f"job{job.pk}v",
    )
    if vres.success:
        return None
    if vres.exit_code is None:
        logger.warning(
            "Hậu kiểm job %s không hoàn tất (%s) — giữ nguyên thành công", job.pk, vres.error
        )
        return None
    detail = vres.stdout.strip() or vres.error
    if plan.verify_present:
        return (
            f"Cài đặt trả thành công nhưng HẬU KIỂM THẤT BẠI: không thấy '{plan.verify_name}' "
            f"trong registry (nghi installer không thực sự cài — vd bản stub/online). {detail}"
        )
    return (
        f"Gỡ cài đặt trả thành công nhưng HẬU KIỂM THẤT BẠI: '{plan.verify_name}' VẪN còn "
        f"trong registry. {detail}"
    )


@shared_task
def finalize_deployment(_results, deployment_id: int):
    """
    Callback chord: tổng kết trạng thái deployment.

    Có thể bị gọi 2 lần cho cùng 1 deployment (chord callback + lưới an toàn
    `reconcile_stuck_deployments`) — guard bằng cách chỉ finalize khi deployment còn
    RUNNING, và ghi bằng update() có điều kiện để tránh race giữa hai lời gọi.
    """
    from apps.deployments.models import Deployment, DeploymentStatus

    try:
        deployment = Deployment.objects.get(pk=deployment_id)
    except Deployment.DoesNotExist:
        return

    if deployment.status != DeploymentStatus.RUNNING:
        logger.info(
            "finalize_deployment: deployment %s không còn RUNNING (%s) — bỏ qua (đã "
            "được tổng kết/hủy bởi lời gọi khác)",
            deployment_id, deployment.status,
        )
        return

    total = deployment.total_count
    failed = deployment.failed_count
    success = deployment.success_count

    if total == 0:
        new_status = DeploymentStatus.COMPLETED
    elif success == 0 and failed == 0:
        # Không thành công cũng không thất bại → mọi job đã bị hủy (reconcile sau khi
        # cancel terminate). Đánh CANCELLED thay vì COMPLETED cho đúng bản chất.
        new_status = DeploymentStatus.CANCELLED
    elif failed == 0:
        new_status = DeploymentStatus.COMPLETED
    elif success == 0:
        new_status = DeploymentStatus.FAILED
    else:
        new_status = DeploymentStatus.COMPLETED_WITH_ERRORS

    updated = Deployment.objects.filter(
        pk=deployment_id, status=DeploymentStatus.RUNNING
    ).update(status=new_status, finished_at=timezone.now())
    if not updated:
        logger.info(
            "finalize_deployment: deployment %s đã bị đổi trạng thái bởi lời gọi khác "
            "giữa lúc tính toán — bỏ qua ghi đè", deployment_id,
        )
        return

    # Giải phóng bộ đếm concurrency của deployment này.
    from apps.deployments.semaphore import clear_slots

    clear_slots(deployment_id)
    logger.info(
        "Deployment %s xong: %s thành công / %s thất bại", deployment_id, success, failed
    )


def _job_timeout() -> int:
    from django.conf import settings

    return settings.RYANDEPLOY.get("JOB_TIMEOUT", 1800)
