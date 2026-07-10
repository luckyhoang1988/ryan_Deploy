"""
Formatter log JSON gọn — để tích hợp ELK/Datadog/Loki (mỗi dòng 1 object JSON).

Không phụ thuộc thư viện ngoài. Bật bằng env DJANGO_LOG_JSON=true; mặc định dev vẫn
dùng format người-đọc (xem settings.base.LOGGING).
"""
import datetime as dt
import json
import logging

# Các field chuẩn của LogRecord — để lọc ra `extra` do người dùng truyền thêm.
_RESERVED = set(
    logging.makeLogRecord({}).__dict__.keys()
) | {"message", "asctime", "taskName"}


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "ts": dt.datetime.fromtimestamp(record.created, dt.timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
        }
        # Gộp mọi field extra (vd logger.info(..., extra={"job_id": 5})) vào JSON.
        for key, value in record.__dict__.items():
            if key not in _RESERVED and not key.startswith("_"):
                payload[key] = value
        if record.exc_info:
            payload["exc"] = self.formatException(record.exc_info)
        return json.dumps(payload, ensure_ascii=False, default=str)
