from channels.generic.websocket import AsyncJsonWebsocketConsumer

# Group toàn cục — tool nội bộ, số deployment/user đồng thời nhỏ nên không tách phòng
# theo từng deployment; frontend tự lọc theo deployment_id trong payload.
GROUP = "realtime"


class RealtimeConsumer(AsyncJsonWebsocketConsumer):
    """Đẩy cập nhật Deployment/Job real-time cho mọi client đã đăng nhập.

    Message nhận từ group qua broadcast.py có type "deployment.update"/"job.update"
    (Channels tự đổi "." thành "_" để gọi handler tương ứng bên dưới).
    """

    async def connect(self):
        user = self.scope.get("user")
        if not user or not user.is_authenticated:
            await self.close()
            return
        await self.channel_layer.group_add(GROUP, self.channel_name)
        await self.accept()

    async def disconnect(self, close_code):
        await self.channel_layer.group_discard(GROUP, self.channel_name)

    async def deployment_update(self, event):
        await self.send_json({"type": "deployment.update", "data": event["data"]})

    async def job_update(self, event):
        await self.send_json({"type": "job.update", "data": event["data"]})
