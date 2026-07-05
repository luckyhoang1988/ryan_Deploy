"""
Action planner — quy đổi một Deployment (theo `action`) thành kế hoạch chạy cụ thể
cho PushExecutor: command, payload cần đẩy, mã exit thành công, và hậu xử lý.

Đây là lớp Django-aware duy nhất biết về từng loại action; PushExecutor vẫn thuần
primitive (command + payload tuỳ chọn). `_run_job` chỉ gọi `build_action_plan` rồi
đưa kết quả vào `executor.run(...)`.
"""
import os
from dataclasses import dataclass, field
from typing import Callable, Optional

from apps.packages.models import InstallerType
from apps.packages.repository import DEFAULT_SUCCESS_EXIT_CODES

from .models import DeploymentAction

# Delay để exit.code (=0) kịp ghi & thu về TRƯỚC khi máy thật sự reboot/shutdown,
# tránh rớt SMB giữa lúc collect.
_ACTION_DELAY_SECONDS = 30
REBOOT_COMMAND = f'shutdown /r /t {_ACTION_DELAY_SECONDS} /c "RyanDeploy scheduled reboot"'
SHUTDOWN_COMMAND = f'shutdown /s /t {_ACTION_DELAY_SECONDS} /c "RyanDeploy scheduled shutdown"'

# Script hậu kiểm cài đặt (kiểm registry Uninstall) — dùng ở tasks._run_job sau khi
# install/uninstall báo thành công, để bắt "false success".
VERIFY_SCRIPT_PATH = os.path.join(os.path.dirname(__file__), "scripts", "verify_installed.ps1")


@dataclass
class ActionPlan:
    command: str
    payload_path: Optional[str] = None       # file đẩy tới máy đích; None = không cần file
    payload_filename: Optional[str] = None
    success_exit_codes: list = field(default_factory=lambda: list(DEFAULT_SUCCESS_EXIT_CODES))
    verify_installer: bool = False           # chạy verify_integrity trước khi đẩy (chống tamper)
    post_hook: Optional[Callable] = None     # callable(machine, ExecResult) sau khi chạy xong
    # Hậu kiểm sau khi chạy thành công: kiểm registry có/không có phần mềm (chống false-success).
    verify_name: Optional[str] = None        # None/"" = bỏ qua hậu kiểm
    verify_present: bool = True              # True = kỳ vọng CÓ (install); False = kỳ vọng MẤT (uninstall)
    extract_payload: bool = False            # payload là archive .zip -> giải nén trước khi chạy command


def _installer_ref(pv):
    """(đường dẫn local, tên file) của installer thuộc PackageVersion."""
    return pv.installer_file.path, pv.installer_file.name.split("/")[-1]


def build_action_plan(deployment, machine) -> ActionPlan:
    """Dựng ActionPlan cho 1 job (deployment + máy đích)."""
    action = deployment.action

    if action == DeploymentAction.INSTALL:
        pv = deployment.package_version
        path, name = _installer_ref(pv)
        return ActionPlan(
            command=pv.install_command,
            payload_path=path,
            payload_filename=name,
            success_exit_codes=pv.success_exit_codes or list(DEFAULT_SUCCESS_EXIT_CODES),
            verify_installer=True,
            verify_name=(pv.verify_name or "").strip() or None,
            verify_present=True,  # sau install: kỳ vọng phần mềm CÓ mặt
            extract_payload=pv.installer_type == InstallerType.ZIP,
        )

    if action == DeploymentAction.UNINSTALL:
        pv = deployment.package_version
        command = pv.uninstall_command
        # Nhiều uninstall dùng "msiexec /x {ProductCode}" — không cần installer file.
        # Chỉ đẩy file khi command tham chiếu {file} hoặc {dir} (archive giải nén).
        needs_file = "{file}" in command or "{dir}" in command
        path, name = _installer_ref(pv) if needs_file else (None, None)
        return ActionPlan(
            command=command,
            payload_path=path,
            payload_filename=name,
            success_exit_codes=pv.success_exit_codes or list(DEFAULT_SUCCESS_EXIT_CODES),
            verify_installer=needs_file,
            verify_name=(pv.verify_name or "").strip() or None,
            verify_present=False,  # sau uninstall: kỳ vọng phần mềm ĐÃ MẤT
            extract_payload=needs_file and pv.installer_type == InstallerType.ZIP,
        )

    if action == DeploymentAction.REBOOT:
        return ActionPlan(command=REBOOT_COMMAND, success_exit_codes=[0])

    if action == DeploymentAction.SHUTDOWN:
        return ActionPlan(command=SHUTDOWN_COMMAND, success_exit_codes=[0])

    if action == DeploymentAction.INVENTORY:
        from .inventory_action import build_inventory_plan

        return build_inventory_plan(deployment, machine)

    raise ValueError(f"Action không hỗ trợ: {action}")
