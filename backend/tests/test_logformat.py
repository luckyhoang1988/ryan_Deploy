import json
import logging

from pydeploy.logformat import JsonFormatter


def test_json_formatter_basic():
    rec = logging.makeLogRecord(
        {"name": "apps.test", "levelname": "INFO", "msg": "hello %s", "args": ("world",)}
    )
    data = json.loads(JsonFormatter().format(rec))
    assert data["logger"] == "apps.test"
    assert data["level"] == "INFO"
    assert data["msg"] == "hello world"  # %-args đã được nội suy
    assert "ts" in data


def test_json_formatter_includes_extra():
    rec = logging.makeLogRecord({"name": "x", "msg": "m", "job_id": 5})
    data = json.loads(JsonFormatter().format(rec))
    assert data["job_id"] == 5


def test_json_formatter_is_valid_json_line():
    rec = logging.makeLogRecord({"name": "x", "msg": "có dấu tiếng Việt"})
    out = JsonFormatter().format(rec)
    assert "\n" not in out  # mỗi log là 1 dòng
    assert json.loads(out)["msg"] == "có dấu tiếng Việt"
