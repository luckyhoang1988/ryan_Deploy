"""Celery tasks cấp deployment (khác apps/jobs/tasks.py là cấp từng job)."""
import logging

from celery import shared_task
from django.db import transaction
from django.utils import timezone

from .models import Deployment, DeploymentSchedule, DeploymentStatus
from .orchestrator import launch_deployment

logger = logging.getLogger("apps.deployments")

# Deployment RUNNING mà quá lâu vẫn CHƯA có job nào (launch chết giữa chừng, hoặc process
# bị kill sau khi claim SCHEDULED→RUNNING nhưng trước khi tạo job) → coi là kẹt, đánh FAILED.
# launch tạo job trong vài giây nên ngưỡng này chỉ chạm khi thực sự có sự cố.
_STUCK_NO_JOB_SECONDS = 600  # 10 phút


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
        # Claim nguyên tử: chỉ đúng 1 tiến trình đổi được SCHEDULED→RUNNING. Đặt luôn
        # started_at làm mốc "RUNNING từ lúc" tin cậy để reconcile phát hiện kẹt (claim
        # bằng .update() không kích hoạt auto_now nên không dựa được vào updated_at).
        with transaction.atomic():
            claimed = (
                Deployment.objects.filter(id=dep_id, status=DeploymentStatus.SCHEDULED)
                .update(status=DeploymentStatus.RUNNING, started_at=now)
            )
        if not claimed:
            continue
        deployment = Deployment.objects.get(id=dep_id)
        # launch_deployment có thể ném lỗi (DB, broker Celery…) giữa lúc đã RUNNING → phải
        # revert về FAILED, nếu không deployment kẹt RUNNING vĩnh viễn (reconcile bỏ qua
        # case chưa có job trong thời gian gia hạn).
        try:
            count = launch_deployment(deployment)
        except Exception:
            logger.exception("launch_deployment lỗi cho %s → đánh FAILED", dep_id)
            deployment.status = DeploymentStatus.FAILED
            deployment.finished_at = timezone.now()
            deployment.save(update_fields=["status", "finished_at"])
            continue
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
    now = timezone.now()
    reconciled = 0
    failed = 0
    for dep_id, started_at in Deployment.objects.filter(
        status=DeploymentStatus.RUNNING
    ).values_list("id", "started_at"):
        jobs = Job.objects.filter(deployment_id=dep_id)
        if not jobs.exists():
            # Bình thường job xuất hiện trong vài giây. Nếu đã RUNNING quá lâu mà vẫn
            # chưa có job → launch chết giữa chừng / process bị kill sau khi claim →
            # đánh FAILED để không kẹt vĩnh viễn. Trong thời gian gia hạn thì để yên.
            age = (now - started_at).total_seconds() if started_at else None
            if age is not None and age > _STUCK_NO_JOB_SECONDS:
                Deployment.objects.filter(id=dep_id).update(
                    status=DeploymentStatus.FAILED, finished_at=now
                )
                failed += 1
                logger.warning(
                    "Reconcile: deployment %s RUNNING %.0fs mà chưa có job → FAILED", dep_id, age
                )
            continue
        if jobs.exclude(status__in=terminal).exists():
            continue  # còn job đang chạy → chưa xong, không đụng
        finalize_deployment(None, dep_id)
        reconciled += 1
        logger.info("Reconcile: tổng kết lại deployment kẹt RUNNING %s", dep_id)

    return {"reconciled": reconciled, "failed": failed}


@shared_task
def trigger_due_schedules():
    """
    Beat task (mỗi phút): kích hoạt các DeploymentSchedule (lịch lặp interval/weekly) đã
    tới giờ. Khác với `trigger_scheduled_deployments` (chạy đúng 1 lần cho CHÍNH deployment
    đó), ở đây mỗi lần tới giờ sẽ CLONE thành 1 Deployment MỚI (spawn_deployment) rồi launch
    — giữ đầy đủ lịch sử job/audit từng lần chạy.
    """
    now = timezone.now()
    triggered = 0

    for sched in DeploymentSchedule.objects.filter(enabled=True):
        # select_for_update + re-check is_due TRONG lock: nếu lần chạy trước của beat task
        # (vd worker chậm) còn chồng lấn lần này, chỉ 1 trong 2 thấy is_due()==True sau khi
        # lock (last_triggered_at đã được lần kia cập nhật) → tránh kích hoạt trùng.
        with transaction.atomic():
            locked = (
                DeploymentSchedule.objects.select_for_update()
                .filter(pk=sched.pk, enabled=True)
                .first()
            )
            if locked is None or not locked.is_due(now):
                continue
            previous_triggered_at = locked.last_triggered_at
            locked.last_triggered_at = now
            locked.save(update_fields=["last_triggered_at", "updated_at"])

        deployment = locked.spawn_deployment(now)
        try:
            job_count = launch_deployment(deployment)
        except Exception:
            logger.exception(
                "launch_deployment lỗi cho schedule %s → đánh FAILED", locked.pk
            )
            deployment.status = DeploymentStatus.FAILED
            deployment.finished_at = timezone.now()
            deployment.save(update_fields=["status", "finished_at"])
            # Launch thất bại → coi như CHƯA kích hoạt: trả lại last_triggered_at để lịch
            # được thử lại ở tick kế tiếp thay vì mất hẳn 1 chu kỳ. An toàn với double-trigger
            # vì lúc này transaction claim ở trên đã commit xong (mọi lần chạy chồng lấn bị
            # khóa chờ đều đã đọc last_triggered_at MỚI trước khi ta revert nó ở đây).
            DeploymentSchedule.objects.filter(pk=locked.pk).update(
                last_triggered_at=previous_triggered_at
            )
            continue

        if job_count == 0:
            # Không có máy đích enabled → không có gì để chạy, đóng lại tránh kẹt RUNNING.
            deployment.status = DeploymentStatus.COMPLETED
            deployment.finished_at = timezone.now()
            deployment.save(update_fields=["status", "finished_at"])

        triggered += 1
        logger.info(
            "Schedule %s (%s) kích hoạt deployment %s (%s job)",
            locked.pk, locked.recurrence_type, deployment.pk, job_count,
        )

    return {"triggered": triggered}
