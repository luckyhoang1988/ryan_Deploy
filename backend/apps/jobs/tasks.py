"""
Celery tasks — nối Django Job <-> PushExecutor (engine agentless).

deploy_to_machine(job_id): thực thi đẩy tới 1 máy.
finalize_deployment(_, deployment_id): tổng kết trạng thái deployment sau khi tất cả job xong.
"""
import logging
import uuid
from datetime import timedelta

from celery import shared_task
from django.db.models import F
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

    # status="collecting" nghĩa là start() đã thành công và job đã được giao cho
    # collect_job_result theo dõi tiếp — slot PHẢI giữ nguyên (không release ở đây), vì máy
    # đích vẫn đang cài dở. Mọi status khác nghĩa là job đã kết thúc/fail/retry-transient
    # NGAY trong lần gọi này (không có collect_job_result nào giữ trách nhiệm release) nên
    # release ngay tại đây — giữ đúng contract return-value cũ (status/error) cho caller.
    handed_off = False
    try:
        result = _start_and_dispatch(self, job, deployment, machine, credential, pv)
        handed_off = result.get("status") == "collecting"
        return result
    finally:
        if not handed_off:
            release_slot(deployment.id)


def _write_job_result(job, **fields) -> bool:
    """
    Ghi kết quả cuối (SUCCESS/FAILED/QUEUED-retry) bằng UPDATE có điều kiện, loại trừ job
    đã CANCELLED — tránh lost update khi cancel_deployment() ghi CANCELLED đúng lúc
    executor.run() vừa xong (cửa sổ giữa refresh_from_db check và save() cũ).
    """
    updated = Job.objects.filter(pk=job.pk).exclude(status=JobStatus.CANCELLED).update(**fields)
    if updated:
        for k, v in fields.items():
            setattr(job, k, v)
    return bool(updated)


def _start_and_dispatch(self, job, deployment, machine, credential, pv) -> dict:
    """
    Chạy tới hết precheck/copy/execute (executor.start(), nhanh — vài giây) rồi giao job cho
    collect_job_result theo dõi tiếp KHÔNG ĐỒNG BỘ — worker được trả lại pool ngay, không
    còn phải ngủ chờ suốt thời gian cài (có thể tới 30 phút) như executor.run() cũ.

    Trả dict {"job_id":..., "status": "collecting"} nếu đã handoff thành công cho
    collect_job_result (deploy_to_machine KHÔNG được release slot — máy đích vẫn đang cài
    dở). Trả dict {"status": "cancelled"/"failed", ...} nếu job đã kết thúc/fail/retry-
    transient NGAY trong lần gọi này (không có collect_job_result nào giữ trách nhiệm release).
    """
    job_id = job.pk
    # Claim nguyên tử: chỉ chạy nếu job còn QUEUED — chặn trường hợp cancel_deployment()
    # đã đặt CANCELLED giữa lúc job chờ slot/hàng đợi và lúc worker thực sự bắt đầu chạy.
    claimed = Job.objects.filter(pk=job_id, status=JobStatus.QUEUED).update(
        status=JobStatus.RUNNING,
        attempts=F("attempts") + 1,
        started_at=job.started_at or timezone.now(),
        celery_task_id=self.request.id or "",
    )
    if not claimed:
        logger.info("Job %s không còn QUEUED — bỏ qua chạy (đã bị hủy?)", job_id)
        return {"job_id": job_id, "status": "cancelled"}
    job.refresh_from_db()

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
            _write_job_result(
                job,
                status=JobStatus.FAILED,
                error_output=f"Không đọc được file installer để xác minh toàn vẹn: {e}",
                current_step="precheck",
                finished_at=timezone.now(),
            )
            logger.error("Integrity check lỗi đọc file cho job %s (%s): %s", job_id, machine.hostname, e)
            return {"job_id": job_id, "status": "failed", "error": "integrity_file_missing"}
        if not ok:
            _write_job_result(
                job,
                status=JobStatus.FAILED,
                error_output=(
                    f"Toàn vẹn installer KHÔNG khớp — SHA-256 mong đợi {pv.sha256}, thực tế {actual}. "
                    "Nghi ngờ file bị sửa đổi. Hủy đẩy."
                ),
                current_step="precheck",
                finished_at=timezone.now(),
            )
            logger.error("Integrity FAIL cho job %s (%s)", job_id, machine.hostname)
            return {"job_id": job_id, "status": "failed", "error": "integrity_mismatch"}

    def progress(step, message):
        # Cập nhật step hiện tại (nhẹ, chỉ 1 field) — dùng update() nên KHÔNG kích hoạt
        # post_save signal (signals.py), phải broadcast tường minh ở đây. start() chỉ emit
        # tới "collect" (1 lần, ở cuối) nên không spam broadcast — poll_once() ở
        # collect_job_result không dùng progress_cb này.
        Job.objects.filter(pk=job.pk).update(current_step=step)
        broadcast_job_step(job.pk, deployment.id, step)

    def is_cancelled():
        # Poll trạng thái CANCELLED giữa các bước để dừng đẩy hợp tác — bổ sung cho
        # revoke(terminate) vốn không chắc dừng sạch.
        return Job.objects.filter(pk=job.pk, status=JobStatus.CANCELLED).exists()

    try:
        cred_password = credential.get_password()
    except Exception as e:
        # Sai/xoay VAULT_KEY hoặc ciphertext hỏng -> decrypt ném lỗi. Không bắt thì
        # exception thoát khỏi Celery task, job đã claim RUNNING sẽ kẹt vĩnh viễn vì không
        # còn chỗ nào ghi FAILED. Lỗi không tự khỏi khi retry.
        _write_job_result(
            job,
            status=JobStatus.FAILED,
            error_output=f"Không giải mã được credential '{credential.name}': {e}",
            current_step="precheck",
            finished_at=timezone.now(),
        )
        logger.error("Giải mã credential lỗi cho job %s (%s): %s", job_id, machine.hostname, e)
        return {"job_id": job_id, "status": "failed", "error": "credential_decrypt_failed"}

    def make_executor(progress_cb=None):
        return PushExecutor(
            host=machine.target_address,
            username=credential.username,
            password=cred_password,
            domain=credential.domain,
            timeout=_job_timeout(),
            progress_cb=progress_cb,
            cancel_check=is_cancelled,
        )

    # --- Đã tồn tại?: install mà phần mềm đã có sẵn trên máy đích -> bỏ qua, không cài lại ---
    from apps.deployments.models import DeploymentAction

    if deployment.action == DeploymentAction.INSTALL and plan.verify_name:
        already, detail = _probe_already_installed(make_executor, plan, job)
        if already:
            msg = f"Đã cài đặt sẵn trên máy — bỏ qua (đã tồn tại). {detail}".strip()
            if not _write_job_result(
                job,
                status=JobStatus.SKIPPED,
                output=msg,
                current_step="done",
                finished_at=timezone.now(),
            ):
                logger.info("Job %s bị hủy đúng lúc xét bỏ qua (đã tồn tại)", job_id)
                return {"job_id": job_id, "status": "cancelled"}
            AuditLog.record(
                AuditLog.Action.JOB_FINISH,
                target=job,
                machine_hostname=machine.hostname,
                status=job.status,
            )
            logger.info("Job %s (%s) bỏ qua: phần mềm đã tồn tại", job_id, machine.hostname)
            return {"job_id": job_id, "status": "skipped"}

    executor = make_executor(progress_cb=progress)

    try:
        executor.start(
            plan.command,
            local_payload_path=plan.payload_path,
            payload_filename=plan.payload_filename,
            job_token=f"job{job.pk}",
            extract_payload=plan.extract_payload,
        )
    except ExecutorError as e:
        return _handle_start_failure(self, job, deployment, machine, e)

    # start() thành công: service đã chạy trên máy đích. Lưu lại log start() + celery_task_id
    # TRƯỚC KHI dispatch (không phải sau) — dưới CELERY_TASK_ALWAYS_EAGER (test), apply_async()
    # chạy collect_job_result ĐỒNG BỘ TỚI HẾT (kể cả các lần self.retry() đệ quy) trước khi
    # trả về, nên nếu update() job nằm SAU dispatch, nó sẽ đè lên đúng lúc collect_job_result
    # đã ghi xong kết quả cuối, xóa mất log/step đã tích luỹ. Tự sinh task_id trước để tránh
    # phụ thuộc thứ tự thực thi giữa 2 môi trường (broker thật vs eager).
    task_id = uuid.uuid4().hex
    Job.objects.filter(pk=job.pk).update(
        output="\n".join(executor.log), celery_task_id=task_id
    )
    collect_job_result.apply_async(args=[job.pk], countdown=_collect_first_delay(), task_id=task_id)
    return {"job_id": job.pk, "status": "collecting"}


def _handle_start_failure(self, job, deployment, machine, e: ExecutorError) -> dict:
    """Lỗi ở precheck/copy/execute (executor.start()) — quyết định retry-transient hay FAILED
    chung cuộc, y hệt logic quyết định retry cũ (dựa vào step/retryable thay vì ExecResult vì
    start() raise exception chứ không trả kết quả). Trả dict (đã xử lý xong tại đây, không
    handoff) hoặc raise self.retry() để Celery tự gọi lại task sau backoff."""
    from apps.audit.models import AuditLog

    job_id = job.pk
    base_fields = {
        "error_output": str(e),
        "current_step": e.step,
        "finished_at": timezone.now(),
    }
    # Đếm số lần thử THẬT qua job.attempts (không dùng self.request.retries vì retries còn
    # tính cả những lần chờ slot concurrency, không phải lỗi thật). e.retryable=False cho lỗi
    # chắc chắn không tự khỏi (vd sai credential) → không retry.
    transient = e.step in _TRANSIENT_STEPS and e.retryable
    if transient and job.attempts <= deployment.retry_limit:
        if not _write_job_result(job, status=JobStatus.QUEUED, **base_fields):
            logger.info("Job %s bị hủy đúng lúc xét retry — bỏ qua", job_id)
            return {"job_id": job_id, "status": "cancelled"}
        countdown = 30 * (2 ** (job.attempts - 1))  # backoff 30s, 60s, 120s...
        logger.info("Retry job %s sau %ss (transient: %s)", job_id, countdown, e)
        raise self.retry(countdown=countdown, exc=e)

    if not _write_job_result(job, status=JobStatus.FAILED, **base_fields):
        logger.info("Job %s bị hủy đúng lúc ghi thất bại — bỏ qua", job_id)
        return {"job_id": job_id, "status": "cancelled"}
    AuditLog.record(
        AuditLog.Action.JOB_FINISH,
        target=job,
        machine_hostname=machine.hostname,
        status=job.status,
        error=str(e)[:500],
    )
    return {"job_id": job_id, "status": "failed", "error": str(e)}


@shared_task(bind=True, max_retries=None, acks_late=True)
def collect_job_result(self, job_id: int):
    """
    Đọc thử kết quả cài đặt (đã được _start_and_dispatch khởi chạy từ trước) MỘT LẦN qua
    `PushExecutor.poll_once()`; nếu chưa xong thì `self.retry(countdown=...)` để nhường worker
    lại cho job khác giữa các lần poll — không sleep-block cả worker như collect loop cũ.
    Đây là task tự lặp lại (giống cách deploy_to_machine tự retry khi chờ slot).
    """
    from apps.deployments.semaphore import release_slot

    try:
        job = Job.objects.select_related(
            "machine", "deployment__credential", "deployment__package_version"
        ).get(pk=job_id)
    except Job.DoesNotExist:
        logger.warning("Job %s không tồn tại (collect)", job_id)
        return {"job_id": job_id, "status": "missing"}

    deployment = job.deployment
    machine = job.machine
    credential = deployment.credential
    pv = deployment.package_version
    job_token = f"job{job.pk}"

    def is_cancelled():
        return Job.objects.filter(pk=job.pk, status=JobStatus.CANCELLED).exists()

    if is_cancelled():
        # Máy đích vẫn còn service/file tạm từ start() (chưa từng đọc được exit.code nên
        # chưa ai cleanup) — phải dọn ngay vì sẽ không còn lần poll nào nữa cho job_token này.
        _cleanup_cancelled_target(job, machine, credential, job_token)
        release_slot(deployment.id)
        logger.info("Job %s bị hủy trong lúc collect — dừng, đã dọn máy đích", job_id)
        return {"job_id": job_id, "status": "cancelled"}

    from apps.deployments.actions import build_action_plan

    plan = build_action_plan(deployment, machine)

    try:
        cred_password = credential.get_password()
    except Exception as e:
        _write_job_result(
            job,
            status=JobStatus.FAILED,
            error_output=f"Không giải mã được credential '{credential.name}': {e}",
            current_step="collect",
            finished_at=timezone.now(),
        )
        release_slot(deployment.id)
        logger.error("Giải mã credential lỗi khi collect job %s (%s): %s", job_id, machine.hostname, e)
        return {"job_id": job_id, "status": "failed", "error": "credential_decrypt_failed"}

    def make_executor(progress_cb=None):
        return PushExecutor(
            host=machine.target_address,
            username=credential.username,
            password=cred_password,
            domain=credential.domain,
            timeout=_job_timeout(),
            progress_cb=progress_cb,
            cancel_check=is_cancelled,
        )

    result = make_executor().poll_once(job_token, success_exit_codes=plan.success_exit_codes)

    if result is None:
        deadline = job.started_at + timedelta(seconds=_job_timeout())
        if timezone.now() >= deadline:
            _write_job_result(
                job,
                status=JobStatus.FAILED,
                error_output=f"Timeout sau {_job_timeout()}s — installer chưa hoàn tất",
                current_step="collect",
                finished_at=timezone.now(),
            )
            release_slot(deployment.id)
            logger.warning("Job %s timeout ở bước collect", job_id)
            return {"job_id": job_id, "status": "failed", "error": "collect_timeout"}
        raise self.retry(countdown=_collect_poll_interval())

    from apps.audit.models import AuditLog

    prior_output = job.output or ""
    base_fields = {
        "exit_code": result.exit_code,
        "output": prior_output + "\n\n--- COLLECT ---\n" + "\n".join(result.log)
        + ("\n\n--- STDOUT ---\n" + result.stdout if result.stdout else ""),
        "error_output": result.error,
        "current_step": result.step_reached,
        "finished_at": timezone.now(),
    }

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
        # Release TRƯỚC _write_job_result (không phải sau) để đảm bảo luôn chạy đúng 1 lần
        # ở mọi nhánh terminal, kể cả khi _write_job_result trả False do bị cancel đúng lúc.
        release_slot(deployment.id)
        if verify_err:
            fields = {**base_fields, "status": JobStatus.FAILED, "error_output": verify_err, "current_step": "verify"}
            if not _write_job_result(job, **fields):
                logger.info("Job %s bị hủy đúng lúc hậu kiểm — bỏ qua ghi FAILED", job_id)
                return {"job_id": job_id, "status": "cancelled"}
            AuditLog.record(
                AuditLog.Action.JOB_FINISH,
                target=job,
                machine_hostname=machine.hostname,
                status=job.status,
                error=verify_err[:500],
            )
            logger.warning("Hậu kiểm FAIL job %s (%s): %s", job_id, machine.hostname, verify_err)
            return {"job_id": job_id, "status": "failed", "error": "verify_failed"}

        success_status = JobStatus.SUCCESS_REBOOT if result.needs_reboot else JobStatus.SUCCESS
        if not _write_job_result(job, status=success_status, **base_fields):
            logger.info("Job %s bị hủy đúng lúc chạy xong — bỏ qua ghi thành công", job_id)
            return {"job_id": job_id, "status": "cancelled"}
        AuditLog.record(
            AuditLog.Action.JOB_FINISH,
            target=job,
            machine_hostname=machine.hostname,
            status=job.status,
            exit_code=result.exit_code,
        )
        return {"job_id": job_id, "status": job.status, "exit_code": result.exit_code}

    # --- Thất bại: "collect" không nằm trong _TRANSIENT_STEPS → luôn FAILED chung cuộc,
    # không retry (installer tự trả exit code xấu, thử lại cũng vô ích) ---
    release_slot(deployment.id)
    if not _write_job_result(job, status=JobStatus.FAILED, **base_fields):
        logger.info("Job %s bị hủy đúng lúc ghi thất bại — bỏ qua", job_id)
        return {"job_id": job_id, "status": "cancelled"}
    AuditLog.record(
        AuditLog.Action.JOB_FINISH,
        target=job,
        machine_hostname=machine.hostname,
        status=job.status,
        error=result.error[:500],
    )
    return {"job_id": job_id, "status": "failed", "error": result.error}


def _cleanup_cancelled_target(job, machine, credential, job_token):
    """Job bị hủy giữa lúc đang collect — máy đích vẫn còn service/file tạm từ start(), dọn
    ngay vì sẽ không còn ai poll job_token này nữa. Lỗi cleanup chỉ log, không chặn việc trả
    'cancelled' (giống mọi lỗi cleanup khác trong PushExecutor)."""
    try:
        cred_password = credential.get_password()
    except Exception as e:  # noqa: BLE001
        logger.warning("Không dọn được máy đích cho job %s (giải mã credential lỗi): %s", job.pk, e)
        return
    executor = PushExecutor(
        host=machine.target_address,
        username=credential.username,
        password=cred_password,
        domain=credential.domain,
        timeout=_job_timeout(),
    )
    try:
        executor.cleanup_now(job_token)
    except Exception as e:  # noqa: BLE001
        logger.warning("cleanup_now lỗi cho job %s (%s): %s", job.pk, machine.hostname, e)


def _probe_already_installed(make_executor, plan, job):
    """
    Trước khi install: kiểm registry Uninstall xem phần mềm đã có mặt trên máy đích chưa —
    có thì báo "đã tồn tại" để caller bỏ qua, không cài chồng lên bản đã có.

    Trả (found, detail): found=True/False khi kết luận được; found=None khi KHÔNG kết luận
    được (lỗi SMB/kết nối lúc kiểm) — caller phải cứ tiến hành cài bình thường, không suy
    diễn từ một lần kiểm thất bại.
    """
    from apps.deployments.actions import VERIFY_SCRIPT_PATH

    name = plan.verify_name.replace('"', "")  # tránh vỡ tham số PowerShell
    command = (
        f'powershell -NoProfile -ExecutionPolicy Bypass -File "{{file}}" '
        f'-Name "{name}" -Present 1'
    )
    prober = make_executor(progress_cb=None)
    pres = prober.run(
        command,
        local_payload_path=VERIFY_SCRIPT_PATH,
        payload_filename="ryandeploy_verify.ps1",
        success_exit_codes=[0],
        job_token=f"job{job.pk}c",
    )
    if pres.exit_code is None:
        logger.debug(
            "Precheck 'đã tồn tại' cho job %s không kết luận được (%s) — cứ tiến hành cài",
            job.pk, pres.error,
        )
        return None, pres.error
    return (pres.exit_code == 0), (pres.stdout.strip() or pres.error)


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

    # Deployment lai (mix SMB+agent): chord chỉ chờ job SMB nên có thể fire khi job agent
    # vẫn còn QUEUED/RUNNING (agent chưa poll/chưa report xong). Không được tính status lúc
    # này — reconcile_stuck_deployments (watchdog định kỳ) sẽ gọi lại khi mọi job đã terminal.
    terminal = [
        JobStatus.SUCCESS, JobStatus.SUCCESS_REBOOT, JobStatus.FAILED, JobStatus.SKIPPED, JobStatus.CANCELLED,
    ]
    if deployment.jobs.exclude(status__in=terminal).exists():
        logger.info(
            "finalize_deployment: %s còn job chưa kết thúc (agent chưa report) — bỏ qua", deployment_id,
        )
        return

    total = deployment.total_count
    failed = deployment.failed_count
    success = deployment.success_count
    skipped = deployment.skipped_count
    # skipped (đã tồn tại, bỏ qua cài) tính như "đã đạt mục tiêu" cùng success — không phải
    # lỗi, không phải hủy — để không lẫn với nhánh CANCELLED/FAILED bên dưới.
    ok = success + skipped

    if total == 0:
        new_status = DeploymentStatus.COMPLETED
    elif ok == 0 and failed == 0:
        # Không thành công cũng không thất bại → mọi job đã bị hủy (reconcile sau khi
        # cancel terminate). Đánh CANCELLED thay vì COMPLETED cho đúng bản chất.
        new_status = DeploymentStatus.CANCELLED
    elif failed == 0:
        new_status = DeploymentStatus.COMPLETED
    elif ok == 0:
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


def _collect_poll_interval() -> int:
    from django.conf import settings

    return settings.RYANDEPLOY.get("COLLECT_POLL_INTERVAL", 12)


def _collect_first_delay() -> int:
    from django.conf import settings

    return settings.RYANDEPLOY.get("COLLECT_FIRST_POLL_DELAY", 5)
