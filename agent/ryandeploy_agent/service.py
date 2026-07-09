"""Windows Service wrapper cho agent — cài bằng `RyanDeployAgent.exe install` (sau khi đóng
gói qua PyInstaller, xem agent/pyinstaller.spec) rồi `net start RyanDeployAgent`, hoặc qua GPO
Computer Software Installation (chạy dưới SYSTEM lúc boot, không cần port inbound nào).

Chỉ import pywin32 ở đây (không phải config/client/executor/poll_loop) — các module đó thuần
Python, test được trên mọi hệ điều hành mà không cần cài pywin32.
"""
import logging
import logging.handlers
import os
import sys
import threading

import servicemanager
import win32event
import win32service
import win32serviceutil

from .config import DEFAULT_CONFIG_PATH, wait_for_config
from .enrollment import ensure_enrolled
from .poll_loop import PollLoop

_LOG_DIR = r"C:\ProgramData\RyanDeployAgent\logs"


def _configure_logging():
    os.makedirs(_LOG_DIR, exist_ok=True)
    handler = logging.handlers.RotatingFileHandler(
        os.path.join(_LOG_DIR, "agent.log"), maxBytes=10 * 1024 * 1024, backupCount=5, encoding="utf-8",
    )
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
    root = logging.getLogger()
    root.setLevel(logging.INFO)
    root.addHandler(handler)


class RyanDeployAgentService(win32serviceutil.ServiceFramework):
    _svc_name_ = "RyanDeployAgent"
    _svc_display_name_ = "RyanDeploy Agent"
    _svc_description_ = "Nhận job triển khai phần mềm từ RyanDeploy server qua HTTPS outbound."

    def __init__(self, args):
        super().__init__(args)
        self._stop_event_win = win32event.CreateEvent(None, 0, 0, None)
        self._stop_event = threading.Event()

    def SvcDoRun(self):
        try:
            _configure_logging()
            logger = logging.getLogger("ryandeploy_agent.service")
            logger.info("RyanDeployAgent: đang khởi động...")
            servicemanager.LogInfoMsg("RyanDeployAgent: đang khởi động...")
            config = wait_for_config(DEFAULT_CONFIG_PATH, self._stop_event)
            if config is None:
                logger.info("RyanDeployAgent: dừng khi service stop trong lúc chờ cấu hình.")
                servicemanager.LogInfoMsg("RyanDeployAgent: dừng khi service stop trong lúc chờ cấu hình.")
                self.ReportServiceStatus(win32service.SERVICE_STOPPED)
                return

            config = ensure_enrolled(config, DEFAULT_CONFIG_PATH, self._stop_event)
            if config.needs_enrollment:
                logger.info("RyanDeployAgent: dừng khi service stop trong lúc chờ enroll.")
                servicemanager.LogInfoMsg("RyanDeployAgent: dừng khi service stop trong lúc chờ enroll.")
                self.ReportServiceStatus(win32service.SERVICE_STOPPED)
                return

            loop = PollLoop(config, self._stop_event, config_path=DEFAULT_CONFIG_PATH)
            thread = threading.Thread(target=loop.run_forever, name="ryandeploy-poll-loop", daemon=True)
            thread.start()
            logger.info("RyanDeployAgent: đã khởi động.")
            servicemanager.LogInfoMsg("RyanDeployAgent: đã khởi động.")
            win32event.WaitForSingleObject(self._stop_event_win, win32event.INFINITE)
        except Exception as e:  # noqa: BLE001
            logger = logging.getLogger("ryandeploy_agent.service")
            logger.error(f"RyanDeployAgent: exception không xác định, dừng service: {e}", exc_info=True)
            servicemanager.LogErrorMsg(f"RyanDeployAgent: exception không xác định: {e}")
            raise

    def SvcStop(self):
        self.ReportServiceStatus(win32service.SERVICE_STOP_PENDING)
        self._stop_event.set()
        win32event.SetEvent(self._stop_event_win)


def main():
    if len(sys.argv) == 1:
        servicemanager.Initialize()
        servicemanager.PrepareToHostSingle(RyanDeployAgentService)
        servicemanager.StartServiceCtrlDispatcher()
    else:
        win32serviceutil.HandleCommandLine(RyanDeployAgentService)


if __name__ == "__main__":
    main()
