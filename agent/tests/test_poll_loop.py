import threading
from unittest.mock import Mock

from ryandeploy_agent.client import ApiError
from ryandeploy_agent.config import AgentConfig
from ryandeploy_agent.poll_loop import PollLoop


def _config(**overrides):
    base = dict(server_url="https://x", token="t", poll_interval=0, heartbeat_interval=0, job_timeout=30)
    base.update(overrides)
    return AgentConfig(**base)


def test_heartbeat_called_first_iteration():
    stop_event = threading.Event()
    client = Mock()

    def fake_poll():
        stop_event.set()
        return None

    client.poll_job.side_effect = fake_poll
    loop = PollLoop(_config(), stop_event, client=client)
    loop.run_forever()
    client.heartbeat.assert_called_once()


def test_job_is_executed_and_reported():
    stop_event = threading.Event()
    client = Mock()
    job = {"job_id": 7, "command": "cmd /c exit 0", "success_exit_codes": [0]}

    calls = {"n": 0}

    def fake_poll():
        calls["n"] += 1
        if calls["n"] == 1:
            return job
        stop_event.set()
        return None

    client.poll_job.side_effect = fake_poll
    loop = PollLoop(_config(), stop_event, client=client)
    loop.run_forever()

    client.report_job.assert_called_once()
    args, kwargs = client.report_job.call_args
    assert args[0] == 7
    assert kwargs["exit_code"] == 0
    assert kwargs["verify_passed"] is None


def test_backoff_on_poll_error_then_recovers():
    stop_event = threading.Event()
    client = Mock()
    calls = {"n": 0}

    def fake_poll():
        calls["n"] += 1
        if calls["n"] < 3:
            raise ApiError("network down")
        stop_event.set()
        return None

    client.poll_job.side_effect = fake_poll
    loop = PollLoop(_config(), stop_event, client=client)
    loop.run_forever()
    assert calls["n"] == 3


def test_report_error_does_not_crash_loop():
    stop_event = threading.Event()
    client = Mock()
    job = {"job_id": 1, "command": "cmd /c exit 0", "success_exit_codes": [0]}
    calls = {"n": 0}

    def fake_poll():
        calls["n"] += 1
        if calls["n"] == 1:
            return job
        stop_event.set()
        return None

    client.poll_job.side_effect = fake_poll
    client.report_job.side_effect = ApiError("409 conflict")

    loop = PollLoop(_config(), stop_event, client=client)
    loop.run_forever()  # không được ném lỗi ra ngoài
    assert calls["n"] == 2
