"""
Đẩy cập nhật Job/Deployment qua WebSocket (group "realtime") — gọi từ signal post_save
(apps/jobs/signals.py, apps/deployments/signals.py) hoặc trực tiếp từ apps/jobs/tasks.py
(đường Job.objects.filter(...).update() bỏ qua post_save signal).

Payload dựng tay (không qua DRF serializer cần request context) — chỉ đủ field để
frontend patch state cục bộ, không phải bản đầy đủ như REST API.
"""
import logging

from asgiref.sync import async_to_sync
from channels.layers import get_channel_layer

from .consumers import GROUP

logger = logging.getLogger("apps.core.realtime")


def _send(message_type: str, data: dict):
    layer = get_channel_layer()
    if layer is None:
        return
    try:
        async_to_sync(layer.group_send)(GROUP, {"type": message_type, "data": data})
    except Exception:  # noqa: BLE001
        # Không để lỗi channel layer (vd Redis tạm gián đoạn) làm hỏng luồng chính
        # (save job/deployment) — real-time chỉ là tiện ích thêm, có polling fallback.
        logger.warning("Broadcast %s thất bại", message_type, exc_info=True)


def broadcast_deployment(deployment):
    _send(
        "deployment.update",
        {
            "id": deployment.pk,
            "status": deployment.status,
            "total_count": deployment.total_count,
            "success_count": deployment.success_count,
            "failed_count": deployment.failed_count,
            "pending_count": deployment.pending_count,
        },
    )


def broadcast_job(job):
    _send(
        "job.update",
        {
            "id": job.pk,
            "deployment_id": job.deployment_id,
            "status": job.status,
            "current_step": job.current_step,
            "exit_code": job.exit_code,
            "attempts": job.attempts,
        },
    )


def broadcast_job_step(job_id: int, deployment_id: int, step: str):
    """Cho đường Job.objects.filter(...).update(current_step=step) trong tasks.py —
    không có instance đầy đủ trong tay nên chỉ gửi step, không gửi lại status."""
    _send("job.update", {"id": job_id, "deployment_id": deployment_id, "current_step": step})
