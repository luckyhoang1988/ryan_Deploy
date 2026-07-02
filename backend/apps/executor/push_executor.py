"""
PushExecutor — engine đẩy phần mềm AGENTLESS kiểu PDQ Deploy.

Quy trình cho MỖI máy đích (không cần agent, không remote thủ công):
  1. precheck : resolve + kiểm tra SMB 445 mở.
  2. copy     : kết nối ADMIN$ (= C:\\Windows), tạo thư mục tạm, upload installer + wrapper .bat.
  3. execute  : tạo Windows Service tạm (MS-SCMR) chạy dưới LocalSystem -> thực thi silent install.
  4. collect  : đọc file exit-code + stdout về qua SMB.
  5. cleanup  : stop + delete service, xóa thư mục/file trên máy đích.

Thiết kế thuần: KHÔNG phụ thuộc Django. Nhận tham số nguyên thủy, trả ExecResult.
Lớp orchestrator/tasks sẽ nối Job (Django) <-> executor.
"""
from __future__ import annotations

import io
import logging
import socket
import time
import uuid
from dataclasses import dataclass, field
from typing import Callable, Optional

logger = logging.getLogger("apps.executor")

# Mã lỗi SCM khi start một "service" thực chất là cmd.exe — coi là bình thường.
_IGNORED_SCM_START_ERRORS = (1053, 1053 & 0xFFFF, 0x8007041D)

# Step names (khớp apps.jobs.models.JobStep)
STEP_PRECHECK = "precheck"
STEP_COPY = "copy"
STEP_EXECUTE = "execute"
STEP_COLLECT = "collect"
STEP_CLEANUP = "cleanup"
STEP_DONE = "done"


@dataclass
class ExecResult:
    success: bool = False
    exit_code: Optional[int] = None
    stdout: str = ""
    error: str = ""
    step_reached: str = STEP_PRECHECK
    needs_reboot: bool = False
    log: list[str] = field(default_factory=list)


ProgressCb = Callable[[str, str], None]  # (step, message) -> None


class PushExecutor:
    """
    Đẩy 1 installer tới 1 máy đích. Tạo instance mới cho mỗi job.
    """

    ADMIN_SHARE = "ADMIN$"  # ánh xạ tới C:\Windows

    def __init__(
        self,
        host: str,
        username: str,
        password: str,
        domain: str = "",
        *,
        target_dir: str = r"PyDeploy\Runner",
        service_prefix: str = "PyDeployRunner",
        timeout: int = 1800,
        smb_port: int = 445,
        progress_cb: Optional[ProgressCb] = None,
    ):
        self.host = host
        self.username = username
        self.password = password
        self.domain = domain
        self.target_dir = target_dir.strip("\\")
        self.service_prefix = service_prefix
        self.timeout = timeout
        self.smb_port = smb_port
        self._progress_cb = progress_cb

        self._conn = None  # SMBConnection
        self._log: list[str] = []

    # ------------------------------------------------------------------ utils
    def _emit(self, step: str, message: str):
        line = f"[{step}] {message}"
        self._log.append(line)
        logger.info("%s %s: %s", self.host, step, message)
        if self._progress_cb:
            try:
                self._progress_cb(step, message)
            except Exception:  # progress không được làm hỏng deploy
                logger.exception("progress_cb lỗi")

    def _share_path(self, job_token: str, *parts: str) -> str:
        """Đường dẫn TƯƠNG ĐỐI trong ADMIN$ share."""
        base = f"{self.target_dir}\\{job_token}\\exec"
        return "\\".join([base, *parts]) if parts else base

    def _disk_path(self, job_token: str, *parts: str) -> str:
        """Đường dẫn tuyệt đối trên đĩa máy đích (ADMIN$ = C:\\Windows)."""
        return "C:\\Windows\\" + self._share_path(job_token, *parts)

    # -------------------------------------------------------------- main flow
    def run(
        self,
        local_installer_path: str,
        installer_filename: str,
        install_command: str,
        *,
        success_exit_codes: Optional[list[int]] = None,
        job_token: Optional[str] = None,
    ) -> ExecResult:
        success_exit_codes = success_exit_codes or [0, 3010]
        job_token = job_token or uuid.uuid4().hex[:12]
        result = ExecResult()

        try:
            # 1) PRECHECK ----------------------------------------------------
            self._emit(STEP_PRECHECK, f"Kiểm tra SMB {self.smb_port}...")
            result.step_reached = STEP_PRECHECK
            self._precheck()

            # 2) CONNECT + COPY ---------------------------------------------
            self._emit(STEP_COPY, "Kết nối SMB và copy file...")
            result.step_reached = STEP_COPY
            self._connect()
            self._copy_payload(job_token, local_installer_path, installer_filename, install_command)

            # 3) EXECUTE -----------------------------------------------------
            self._emit(STEP_EXECUTE, "Tạo service tạm và chạy silent install...")
            result.step_reached = STEP_EXECUTE
            self._execute_via_service(job_token)

            # 4) COLLECT -----------------------------------------------------
            self._emit(STEP_COLLECT, "Chờ kết quả...")
            result.step_reached = STEP_COLLECT
            exit_code, stdout = self._collect_result(job_token)
            result.exit_code = exit_code
            result.stdout = stdout
            result.success = exit_code in success_exit_codes
            result.needs_reboot = exit_code == 3010
            if not result.success:
                result.error = f"Installer trả exit code {exit_code}"

        except ExecutorError as e:
            result.error = str(e)
            self._emit(result.step_reached, f"LỖI: {e}")
        except Exception as e:  # noqa: BLE001
            result.error = f"Lỗi không mong đợi: {e}"
            logger.exception("PushExecutor lỗi trên %s", self.host)
            self._emit(result.step_reached, f"LỖI: {e}")
        finally:
            # 5) CLEANUP (luôn chạy) ----------------------------------------
            try:
                self._emit(STEP_CLEANUP, "Dọn dẹp service + file trên máy đích...")
                self._cleanup(job_token)
            except Exception as e:  # noqa: BLE001
                logger.warning("Cleanup lỗi trên %s: %s", self.host, e)
                self._log.append(f"[cleanup] cảnh báo: {e}")
            self._disconnect()

        result.step_reached = STEP_DONE if result.success else result.step_reached
        result.log = list(self._log)
        return result

    # ------------------------------------------------------------- step impls
    def _precheck(self):
        try:
            with socket.create_connection((self.host, self.smb_port), timeout=10):
                pass
        except OSError as e:
            raise ExecutorError(f"Không kết nối được SMB {self.host}:{self.smb_port} ({e})")

    def _connect(self):
        from impacket.smbconnection import SMBConnection

        try:
            conn = SMBConnection(self.host, self.host, sess_port=self.smb_port, timeout=30)
            conn.login(self.username, self.password, self.domain)
            self._conn = conn
        except Exception as e:  # noqa: BLE001
            raise ExecutorError(f"Xác thực/kết nối SMB thất bại: {e}")

    def _ensure_dirs(self, job_token: str):
        """Tạo cây thư mục tạm trong ADMIN$ (từng cấp)."""
        conn = self._conn
        parts = f"{self.target_dir}\\{job_token}\\exec".split("\\")
        cur = ""
        for p in parts:
            cur = f"{cur}\\{p}" if cur else p
            try:
                conn.createDirectory(self.ADMIN_SHARE, cur)
            except Exception:
                # đã tồn tại -> bỏ qua
                pass

    def _copy_payload(self, job_token, local_installer_path, installer_filename, install_command):
        conn = self._conn
        self._ensure_dirs(job_token)

        # Upload installer
        with open(local_installer_path, "rb") as fh:
            conn.putFile(self.ADMIN_SHARE, self._share_path(job_token, installer_filename), fh.read)

        # Sinh wrapper .bat: chạy install, ghi stdout + exit code ra file
        installer_disk = self._disk_path(job_token, installer_filename)
        stdout_disk = self._disk_path(job_token, "stdout.log")
        exit_disk = self._disk_path(job_token, "exit.code")
        command = install_command.replace("{file}", f'"{installer_disk}"')

        bat = (
            "@echo off\r\n"
            f'{command} > "{stdout_disk}" 2>&1\r\n'
            f'echo %ERRORLEVEL% > "{exit_disk}"\r\n'
        )
        conn.putFile(
            self.ADMIN_SHARE,
            self._share_path(job_token, "run.bat"),
            io.BytesIO(bat.encode("utf-8")).read,
        )

    def _execute_via_service(self, job_token: str):
        """
        Tạo service tạm với binPath = cmd chạy run.bat. Service không phải service
        thật nên SCM start sẽ báo timeout (1053) — ta bỏ qua, lệnh vẫn chạy.
        """
        from impacket.dcerpc.v5 import scmr

        bat_disk = self._disk_path(job_token, "run.bat")
        bin_path = f'%COMSPEC% /Q /C "{bat_disk}"'
        service_name = f"{self.service_prefix}_{job_token}"

        dce = self._open_scmr()
        try:
            sc_handle = scmr.hROpenSCManagerW(dce)["lpScHandle"]
            resp = scmr.hRCreateServiceW(
                dce,
                sc_handle,
                service_name + "\x00",
                service_name + "\x00",
                lpBinaryPathName=bin_path + "\x00",
                dwStartType=scmr.SERVICE_DEMAND_START,
            )
            svc_handle = resp["lpServiceHandle"]
            try:
                scmr.hRStartServiceW(dce, svc_handle)
            except Exception as e:  # noqa: BLE001
                # Service cmd -> SCM báo lỗi start là bình thường
                if not self._is_ignorable_start_error(e):
                    logger.debug("Start service báo lỗi (bỏ qua): %s", e)
            finally:
                scmr.hRCloseServiceHandle(dce, svc_handle)
            scmr.hRCloseServiceHandle(dce, sc_handle)
        finally:
            dce.disconnect()

    def _collect_result(self, job_token: str) -> tuple[int, str]:
        """Poll đọc exit.code + stdout.log về qua SMB đến khi có hoặc timeout."""
        exit_share = self._share_path(job_token, "exit.code")
        stdout_share = self._share_path(job_token, "stdout.log")

        deadline = time.time() + self.timeout
        interval = 3
        while time.time() < deadline:
            content = self._try_read(exit_share)
            if content is not None:
                try:
                    exit_code = int(content.decode("utf-8", "ignore").strip().split()[0])
                except (ValueError, IndexError):
                    exit_code = -1
                stdout_raw = self._try_read(stdout_share) or b""
                stdout = stdout_raw.decode("utf-8", "ignore")
                return exit_code, stdout
            time.sleep(interval)

        raise ExecutorError(f"Timeout sau {self.timeout}s — installer chưa hoàn tất")

    def _cleanup(self, job_token: str):
        # Xóa service (nếu còn)
        try:
            from impacket.dcerpc.v5 import scmr

            service_name = f"{self.service_prefix}_{job_token}"
            dce = self._open_scmr()
            try:
                sc_handle = scmr.hROpenSCManagerW(dce)["lpScHandle"]
                try:
                    svc = scmr.hROpenServiceW(dce, sc_handle, service_name + "\x00")["lpServiceHandle"]
                    try:
                        scmr.hRControlService(dce, svc, scmr.SERVICE_CONTROL_STOP)
                    except Exception:
                        pass
                    scmr.hRDeleteService(dce, svc)
                    scmr.hRCloseServiceHandle(dce, svc)
                except Exception:
                    pass
                scmr.hRCloseServiceHandle(dce, sc_handle)
            finally:
                dce.disconnect()
        except Exception as e:  # noqa: BLE001
            logger.debug("Xóa service lỗi (bỏ qua): %s", e)

        # Xóa file + thư mục tạm
        if self._conn is not None:
            for name in ("run.bat", "stdout.log", "exit.code"):
                self._safe_delete_file(self._share_path(job_token, name))
            # xóa cả installer: liệt kê + xóa toàn bộ file còn lại trong exec
            self._delete_exec_dir(job_token)

    # ------------------------------------------------------------- SMB/SCMR helpers
    def _open_scmr(self):
        from impacket.dcerpc.v5 import scmr, transport

        rpc = transport.SMBTransport(
            self.host, self.smb_port, r"\svcctl", smb_connection=self._conn
        )
        dce = rpc.get_dce_rpc()
        dce.connect()
        dce.bind(scmr.MSRPC_UUID_SCMR)
        return dce

    def _try_read(self, share_path: str) -> Optional[bytes]:
        buf = io.BytesIO()
        try:
            self._conn.getFile(self.ADMIN_SHARE, share_path, buf.write)
            return buf.getvalue()
        except Exception:
            return None

    def _safe_delete_file(self, share_path: str):
        try:
            self._conn.deleteFile(self.ADMIN_SHARE, share_path)
        except Exception:
            pass

    def _delete_exec_dir(self, job_token: str):
        conn = self._conn
        exec_dir = self._share_path(job_token)
        # Xóa mọi file còn lại (VD installer) rồi xóa thư mục các cấp
        try:
            for f in conn.listPath(self.ADMIN_SHARE, exec_dir + "\\*"):
                fname = f.get_longname()
                if fname in (".", ".."):
                    continue
                self._safe_delete_file(exec_dir + "\\" + fname)
        except Exception:
            pass
        for d in (
            f"{self.target_dir}\\{job_token}\\exec",
            f"{self.target_dir}\\{job_token}",
        ):
            try:
                conn.deleteDirectory(self.ADMIN_SHARE, d)
            except Exception:
                pass

    def _disconnect(self):
        if self._conn is not None:
            try:
                self._conn.close()
            except Exception:
                pass
            self._conn = None

    @staticmethod
    def _is_ignorable_start_error(exc) -> bool:
        text = str(exc)
        return any(str(code) in text for code in _IGNORED_SCM_START_ERRORS) or "1053" in text


class ExecutorError(Exception):
    """Lỗi có kiểm soát trong quá trình đẩy."""
