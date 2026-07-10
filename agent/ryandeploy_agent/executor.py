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
# Thời gian chờ thêm sau khi đã taskkill /T /F — dọn cả cây tiến trình thường xong gần như
# ngay, số này chỉ là lưới an toàn cuối cùng để _run_command KHÔNG BAO GIỜ treo vô hạn dù
# taskkill tự nó có trục trặc (xem _kill_process_tree).
_KILL_GRACE_SECONDS = 10


@dataclasses.dataclass
class JobOutcome:
    exit_code: Optional[int]
    stdout: str
    error: str
    needs_reboot: bool
    verify_passed: Optional[bool]  # None = không hậu kiểm / không kết luận được
    skipped: bool = False  # True = tiền kiểm thấy đã cài sẵn -> không chạy command


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
    precheck = job.get("precheck")
    if precheck:
        # Tiền kiểm registry TRƯỚC KHI tải payload — đã có sẵn thì bỏ qua cài đặt, không tốn
        # băng thông tải installer (cùng mục đích với _probe_already_installed phía SMB, xem
        # backend/apps/jobs/tasks.py). already=None (không kết luận được) -> cứ tiến hành cài
        # bình thường, không suy diễn từ 1 lần kiểm thất bại.
        already = _run_precheck(client, precheck, workdir, timeout)
        if already:
            return JobOutcome(
                exit_code=0, stdout="Đã cài đặt sẵn trên máy — bỏ qua (đã tồn tại).",
                error="", needs_reboot=False, verify_passed=None, skipped=True,
            )

    command = job["command"]

    payload = job.get("payload")
    if payload:
        # os.path.basename: filename tới từ server (job payload) — nếu là đường dẫn tuyệt đối
        # (vd "C:\\Windows\\evil.exe"), os.path.join(workdir, ...) sẽ BỎ QUA workdir và trả về
        # thẳng đường dẫn đó (hành vi chuẩn của os.path.join khi tham số sau là tuyệt đối), khiến
        # agent ghi file ra ngoài thư mục tạm. Django storage đã sanitize tên khi lưu server-side,
        # nhưng agent không nên phụ thuộc hoàn toàn vào đó — phòng thủ chiều sâu ở phía nhận.
        local_path = os.path.join(workdir, os.path.basename(payload["filename"]))
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
    exit_code=None nghĩa là lệnh không chạy tới nơi (timeout/OSError).

    Dùng Popen (không subprocess.run) để khi timeout có thể tự kill CẢ CÂY tiến trình —
    trên Windows, Popen.kill()/subprocess.run(timeout=) mặc định chỉ diệt đúng tiến trình
    con trực tiếp (cmd.exe), để lại tiến trình cháu mà installer tự tách/relaunch (rất phổ
    biến: MSI wrapper, installer tự nâng quyền rồi respawn) sống, vẫn giữ handle
    stdout/stderr — communicate() nội bộ mà subprocess.run gọi lại NGAY SAU kill() sẽ treo
    vĩnh viễn chờ EOF không bao giờ tới, kéo theo cả agent (heartbeat+poll+execute dùng
    chung 1 thread) chết cứng vô thời hạn dù đã cấu hình job_timeout (xem LESSONS.md
    2026-07-10)."""
    try:
        proc = subprocess.Popen(
            command, shell=True, cwd=cwd,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, errors="ignore",
        )
    except OSError as e:
        return None, "", f"Không chạy được lệnh: {e}"

    try:
        stdout, stderr = proc.communicate(timeout=timeout)
        return proc.returncode, (stdout or "") + (stderr or ""), ""
    except subprocess.TimeoutExpired:
        _kill_process_tree(proc.pid)
        try:
            stdout, stderr = proc.communicate(timeout=_KILL_GRACE_SECONDS)
        except subprocess.TimeoutExpired:
            stdout, stderr = "", ""
        return None, (stdout or "") + (stderr or ""), f"Timeout sau {timeout}s — lệnh chưa hoàn tất (đã dọn cả cây tiến trình)"


def _kill_process_tree(pid: int) -> None:
    """taskkill /T diệt cả tiến trình cháu bên dưới `pid` (không chỉ chính `pid`) — xem
    docstring `_run_command` để biết lý do không dùng Popen.kill()."""
    try:
        subprocess.run(
            ["taskkill", "/F", "/T", "/PID", str(pid)],
            capture_output=True, timeout=_KILL_GRACE_SECONDS,
        )
    except (OSError, subprocess.TimeoutExpired) as e:
        logger.warning("taskkill /T /F /PID %s lỗi: %s", pid, e)


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


def _run_precheck(client: AgentClient, precheck: dict, workdir: str, timeout: int) -> Optional[bool]:
    """Tiền kiểm registry trước khi cài — có sẵn rồi thì trả True để caller bỏ qua, không cài
    chồng lên bản đã có. Luôn kiểm `-Present 1` (tìm "đã tồn tại"), không phụ thuộc tham số
    `present` trong payload — cùng ngữ nghĩa `_probe_already_installed` phía SMB (server chỉ
    gửi precheck cho action INSTALL).

    Trả None nếu không tải/chạy được script (không kết luận) — caller phải cứ tiến hành cài,
    không suy diễn từ một lần kiểm thất bại."""
    script_path = os.path.join(workdir, "ryandeploy_precheck.ps1")
    try:
        client.download_to(precheck["script_url"], script_path)
    except ApiError as e:
        logger.warning("Không tải được script tiền kiểm: %s", e)
        return None

    name = (precheck.get("name") or "").replace('"', "")  # tránh vỡ tham số PowerShell
    command = (
        f'powershell -NoProfile -ExecutionPolicy Bypass -File "{script_path}" '
        f'-Name "{name}" -Present 1'
    )
    exit_code, _, run_error = _run_command(command, workdir, timeout)
    if exit_code is None:
        logger.warning("Tiền kiểm không hoàn tất (%s) — cứ tiến hành cài", run_error)
        return None
    return exit_code == 0
