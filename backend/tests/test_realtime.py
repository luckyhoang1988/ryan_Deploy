"""
WebSocket real-time: Job.save() (post_save signal, xem apps/jobs/signals.py) phải đẩy
message "job.update" lên group "realtime" mà RealtimeConsumer đang lắng nghe.

KHÔNG dùng `channels.testing.WebsocketCommunicator` — `channels/testing/__init__.py`
import cứng `daphne.testing`, mà project cố tình KHÔNG cài daphne (requirements.txt:
daphne ghim twisted[tls]->pyopenssl>=25.2.0, xung đột impacket 0.12.0 ghim
pyOpenSSL==24.0.0). Tự dựng communicator tối giản trên `asgiref.testing.ApplicationCommunicator`
(chính là lớp nền mà WebsocketCommunicator kế thừa) — đủ cho việc test connect/receive/disconnect.
"""
import json
from unittest import mock

import pytest
from asgiref.sync import async_to_sync
from asgiref.testing import ApplicationCommunicator
from channels.db import database_sync_to_async
from django.contrib.auth.models import User

from apps.core.realtime.consumers import RealtimeConsumer
from apps.credentials.models import DeployCredential
from apps.deployments.models import Deployment
from apps.jobs.models import Job, JobStatus
from apps.machines.models import Machine
from apps.packages.models import InstallerType, Package, PackageVersion

WS_SCOPE = {"type": "websocket", "path": "/ws/updates/", "query_string": b"", "headers": []}


class _WSCommunicator(ApplicationCommunicator):
    """Bản rút gọn của channels.testing.WebsocketCommunicator (xem docstring module)."""

    async def send_input(self, message):
        with mock.patch("channels.db.close_old_connections", lambda: None):
            return await super().send_input(message)

    async def receive_output(self, timeout=1):
        with mock.patch("channels.db.close_old_connections", lambda: None):
            return await super().receive_output(timeout)

    async def connect(self, timeout=1):
        await self.send_input({"type": "websocket.connect"})
        response = await self.receive_output(timeout)
        if response["type"] == "websocket.close":
            return False, response.get("code", 1000)
        assert response["type"] == "websocket.accept"
        return True, response.get("subprotocol")

    async def receive_json_from(self, timeout=1):
        response = await self.receive_output(timeout)
        assert response["type"] == "websocket.send"
        return json.loads(response["text"])

    async def disconnect(self, code=1000, timeout=1):
        await self.send_input({"type": "websocket.disconnect", "code": code})
        await self.wait(timeout)


@pytest.fixture
def deployment(db):
    pkg = Package.objects.create(name="Office")
    pv = PackageVersion.objects.create(
        package=pkg, version="2024", installer_file="repository/x/2024/setup.exe",
        installer_type=InstallerType.EXE,
    )
    cred = DeployCredential.objects.create(name="svc", username="svc_deploy")
    return Deployment.objects.create(name="Rollout", package_version=pv, credential=cred)


def test_anonymous_connect_is_rejected(db):
    async def scenario():
        communicator = _WSCommunicator(RealtimeConsumer.as_asgi(), dict(WS_SCOPE))
        connected, _ = await communicator.connect()
        assert connected is False

    async_to_sync(scenario)()


def test_job_status_change_broadcasts_to_websocket(db, deployment):
    machine = Machine.objects.create(hostname="PC-1")
    user = User.objects.create_user("tester", password="x")

    async def scenario():
        scope = dict(WS_SCOPE, user=user)
        communicator = _WSCommunicator(RealtimeConsumer.as_asgi(), scope)
        connected, _ = await communicator.connect()
        assert connected

        job = await database_sync_to_async(Job.objects.create)(
            deployment=deployment, machine=machine, status=JobStatus.PENDING
        )
        created_msg = await communicator.receive_json_from(timeout=2)
        assert created_msg["type"] == "job.update"
        assert created_msg["data"]["id"] == job.id
        assert created_msg["data"]["status"] == JobStatus.PENDING

        await database_sync_to_async(_mark_running)(job)
        updated_msg = await communicator.receive_json_from(timeout=2)
        assert updated_msg["data"]["status"] == JobStatus.RUNNING

        await communicator.disconnect()

    async_to_sync(scenario)()


def _mark_running(job):
    job.status = JobStatus.RUNNING
    job.save(update_fields=["status"])
