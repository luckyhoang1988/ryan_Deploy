"""Thực thi 1 job trên máy đích: tải payload (nếu có) -> verify sha256 -> chạy command ->
hậu kiểm (nếu có) -> trả kết quả để poll_loop report về server.

Không phụ thuộc Django/impacket. Cú pháp `{file}` trong command khớp đúng
`backend/apps/executor/push_executor.py` (đường SMB) — chỉ khác là file đã nằm sẵn cục bộ
(tải qua HTTPS) thay vì copy qua SMB.
"""
import dataclasses
import hashlib
import logging
import os
import shutil
import subprocess
import tempfile
from typing import Optional

from .client import AgentClient, ApiError

logger = logging.getLogger("ryandeploy_agent.executor")

_HASH_CHUNK_SIZE = 1024 * 256


@dataclasses.dataclass
class JobOutcome:
    exit_code: Optional[int]
    stdout: str
    error: str
    needs_reboot: bool
    verify_passed: Optional[bool]  # None = không hậu kiểm / không kết luận được


def run_job(client: AgentClient, job: dict, job_timeout: int) -> JobOutcome:
    """Chạy 1 job (dict trả từ AgentClient.poll_job) trong thư mục tạm riêng, luôn dọn dẹp
    thư mục tạm khi xong bất kể thành công hay lỗi. `job_timeout` (giây) đến từ AgentConfig
    — server không gửi kèm timeout trong payload job."""
    workdir = tempfile.mkdtemp(prefix="ryandeploy_job_")
    try:
        return _run_job_in(client, job, workdir, job_timeout)
    finally:
        shutil.rmtree(workdir, ignore_errors=True)


def _run_job_in(client: AgentClient, job: dict, workdir: str, timeout: int) -> JobOutcome:
    command = job["command"]

    payload = job.get("payload")
    if payload:
        local_path = os.path.join(workdir, payload["filename"])
        try:
            header_sha256 = client.download_to(payload["download_url"], local_path)
        except ApiError as e:
            return JobOutcome(
                exit_code=None, stdout="", error=f"Tải payload thất bại: {e}",
                needs_reboot=False, verify_passed=None,
            )

        expected_sha256 = payload.get("sha256") or header_sha256
        if expected_sha256:
            actual = _sha256_file(local_path)
            if actual.lower() != expected_sha256.lower():
                return JobOutcome(
                    exit_code=None, stdout="",
                    error=(
                        f"Toàn vẹn payload KHÔNG khớp (kỳ vọng {expected_sha256}, thực tế {actual}) "
                        "— từ chối chạy."
                    ),
                    needs_reboot=False, verify_passed=None,
                )
        command = command.replace("{file}", f'"{local_path}"')

    exit_code, stdout, run_error = _run_command(command, workdir, timeout)

    success_codes = job.get("success_exit_codes") or [0]
    verify_passed = None
    verify = job.get("verify")
    if verify and exit_code in success_codes:
        verify_passed = _run_verify(client, verify, workdir, timeout)

    return JobOutcome(
        exit_code=exit_code,
        stdout=stdout,
        error=run_error,
        needs_reboot=(exit_code == 3010),
        verify_passed=verify_passed,
    )


def _sha256_file(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(_HASH_CHUNK_SIZE), b""):
            h.update(chunk)
    return h.hexdigest()


def _run_command(command: str, cwd: str, timeout: int):
    """Chạy 1 lệnh shell, trả (exit_code hoặc None, stdout gộp stderr, error).
    exit_code=None nghĩa là lệnh không chạy tới nơi (timeout/OSError)."""
    try:
        proc = subprocess.run(
            command, shell=True, cwd=cwd, timeout=timeout,
            capture_output=True, text=True, errors="ignore",
        )
        stdout = (proc.stdout or "") + (proc.stderr or "")
        return proc.returncode, stdout, ""
    except subprocess.TimeoutExpired:
        return None, "", f"Timeout sau {timeout}s — lệnh chưa hoàn tất"
    except OSError as e:
        return None, "", f"Không chạy được lệnh: {e}"


def _run_verify(client: AgentClient, verify: dict, workdir: str, timeout: int) -> Optional[bool]:
    """Tải verify_installed.ps1 và chạy hậu kiểm registry — cùng script + tham số server
    dùng cho đường SMB (xem backend/apps/jobs/tasks.py::_verify_install).

    Trả None nếu không tải/chạy được script (không kết luận, KHÔNG đánh fail — tránh biến
    một install/uninstall thật thành công thành thất bại chỉ vì trục trặc hậu kiểm)."""
    script_path = os.path.join(workdir, "verify_installed.ps1")
    try:
        client.download_to(verify["script_url"], script_path)
    except ApiError as e:
        logger.warning("Không tải được script hậu kiểm: %s", e)
        return None

    name = (verify.get("name") or "").replace('"', "")  # tránh vỡ tham số PowerShell
    present = "1" if verify.get("present", True) else "0"
    command = (
        f'powershell -NoProfile -ExecutionPolicy Bypass -File "{script_path}" '
        f'-Name "{name}" -Present {present}'
    )
    exit_code, _, run_error = _run_command(command, workdir, timeout)
    if exit_code is None:
        logger.warning("Hậu kiểm không hoàn tất (%s) — giữ nguyên kết quả cài đặt", run_error)
        return None
    return exit_code == 0
