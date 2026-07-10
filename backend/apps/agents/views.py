"""
API cho agent (chạy trên máy đích, kết nối outbound HTTPS) — mặt phẳng tin cậy tách biệt
hoàn toàn khỏi session người dùng (xem AgentTokenAuthentication). Tái dùng nguyên logic
nghiệp vụ đã có cho SMB (build_action_plan, verify_integrity, _write_job_result) — chỉ
tầng vận chuyển khác nhau.
"""
import logging
import os

from django.db.models import F
from django.http import FileResponse
from django.shortcuts import get_object_or_404
from django.urls import reverse
from django.utils import timezone
from rest_framework import status
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.throttling import ScopedRateThrottle
from rest_framework.views import APIView

from apps.audit.models import AuditLog
from apps.deployments.actions import VERIFY_SCRIPT_PATH, build_action_plan
from apps.deployments.inventory_action import SCRIPT_PATH as INVENTORY_SCRIPT_PATH
from apps.deployments.models import PACKAGE_ACTIONS, DeploymentAction
from apps.executor.push_executor import ExecResult
from apps.jobs.models import Job, JobStatus
from apps.jobs.tasks import _job_timeout, _write_job_result
from apps.machines.models import ConnectionMode, Machine
from apps.packages.models import PackageVersion
from apps.packages.repository import verify_integrity

from .auth import AgentTokenAuthentication
from .permissions import IsAuthenticatedAgent
from .services import EnrollmentError, enroll_machine
from .throttling import AgentScopedRateThrottle

logger = logging.getLogger("apps.agents")

# Script nội bộ (bundled cùng server, không phải PackageVersion do người dùng upload) mà
# agent được phép tải — verify_installed.ps1 dùng cho hậu kiểm, inventory.ps1 là payload
# của action INVENTORY. Không có sha256 kỳ vọng vì đây là script của chính server, tải qua
# kênh TLS đã xác thực bằng agent token — khác installer (nguồn gốc từ người dùng upload).
_SCRIPT_WHITELIST = {
    "verify_installed.ps1": VERIFY_SCRIPT_PATH,
    "inventory.ps1": INVENTORY_SCRIPT_PATH,
}


class _AgentAPIView(APIView):
    """Base: mọi view agent PHẢI dùng đúng bộ auth/permission này — không kế thừa
    SessionAuthentication/IsViewerOrAbove mặc định của REST_FRAMEWORK (2 mặt phẳng tin cậy
    tách biệt tuyệt đối)."""

    authentication_classes = [AgentTokenAuthentication]
    permission_classes = [IsAuthenticatedAgent]
    throttle_classes = [AgentScopedRateThrottle]


class AgentJobPollView(_AgentAPIView):
    throttle_scope = "agent_poll"

    def post(self, request):
        from apps.deployments.semaphore import acquire_slot, release_slot

        machine = request.agent_machine
        if machine.connection_mode != ConnectionMode.AGENT:
            # Máy có token hợp lệ nhưng đã bị chuyển (hoặc chưa từng ở) connection_mode=agent
            # — ví dụ admin rollback về SMB giữa lúc xử lý sự cố (xem plan_agent.md §8). Không
            # cho agent claim job của máy này, để tránh race với đường SMB (deploy_to_machine
            # dispatch ngay qua Celery) và tôn trọng đúng lựa chọn transport hiện tại của admin.
            return Response({"job": None})

        job = (
            Job.objects.select_related("deployment", "deployment__package_version")
            .filter(machine=machine, status=JobStatus.QUEUED)
            .order_by("created_at")
            .first()
        )
        if job is None:
            return Response({"job": None})

        deployment = job.deployment
        ttl = _job_timeout() + 300
        if not acquire_slot(deployment.id, deployment.max_concurrency, ttl):
            return Response({"job": None})  # đầy slot concurrency — agent tự poll lại sau

        # Claim nguyên tử: chỉ 1 lần poll trùng thời điểm (retry mạng của agent) thắng.
        claimed = Job.objects.filter(pk=job.pk, status=JobStatus.QUEUED).update(
            status=JobStatus.RUNNING,
            attempts=F("attempts") + 1,
            started_at=timezone.now(),
        )
        if not claimed:
            release_slot(deployment.id)
            return Response({"job": None})
        job.refresh_from_db()

        AuditLog.record(
            AuditLog.Action.JOB_START, target=job, machine_hostname=machine.hostname, attempt=job.attempts,
        )

        plan = build_action_plan(deployment, machine)
        pv = deployment.package_version

        if plan.extract_payload:
            # v1: package dạng .zip cần giải nén an toàn (validate_zip_archive) phía agent —
            # chưa triển khai, để phase sau (xem plan_agent.md mục 5, "Giới hạn phạm vi v1").
            _write_job_result(
                job, status=JobStatus.FAILED,
                error_output=(
                    "Package dạng archive .zip chưa được hỗ trợ qua agent (v1) — đổi máy này về "
                    "connection_mode='smb' để cài package này."
                ),
                current_step="precheck", finished_at=timezone.now(),
            )
            release_slot(deployment.id)
            AuditLog.record(
                AuditLog.Action.JOB_FINISH, target=job, machine_hostname=machine.hostname, status=job.status,
            )
            return Response({"job": None})

        payload = None
        if plan.payload_path:
            if deployment.action in PACKAGE_ACTIONS and pv is not None:
                download_url = request.build_absolute_uri(
                    reverse("agent-package-download", args=[pv.pk])
                )
                payload = {"download_url": download_url, "filename": plan.payload_filename, "sha256": pv.sha256}
            else:
                script_name = os.path.basename(plan.payload_path)
                download_url = request.build_absolute_uri(reverse("agent-script", args=[script_name]))
                payload = {"download_url": download_url, "filename": plan.payload_filename, "sha256": ""}

        verify = None
        if plan.verify_name:
            verify = {
                "script_url": request.build_absolute_uri(reverse("agent-script", args=["verify_installed.ps1"])),
                "name": plan.verify_name,
                "present": plan.verify_present,
            }

        precheck = None
        if deployment.action == DeploymentAction.INSTALL and plan.verify_name:
            # Tiền kiểm: đồng ngữ nghĩa với _probe_already_installed phía SMB (tasks.py) —
            # chỉ gửi cho action INSTALL, agent luôn kiểm -Present 1 (đã cài sẵn chưa).
            precheck = {
                "script_url": request.build_absolute_uri(reverse("agent-script", args=["verify_installed.ps1"])),
                "name": plan.verify_name,
            }

        return Response({
            "job": {
                "job_id": job.pk,
                "action": deployment.action,
                "command": plan.command,
                "success_exit_codes": plan.success_exit_codes,
                "payload": payload,
                "verify": verify,
                "precheck": precheck,
            }
        })


class AgentJobReportView(_AgentAPIView):
    throttle_scope = "agent_report"

    def post(self, request, job_id):
        from apps.deployments.semaphore import release_slot

        machine = request.agent_machine
        if machine.connection_mode != ConnectionMode.AGENT:
            # Đồng bộ với poll: admin rollback về SMB giữa lúc agent đang chạy → không nhận
            # report (tránh ghi đè kết quả / race với đường SMB). Agent sẽ thấy 409 và dừng.
            return Response(
                {"detail": "Máy không còn ở connection_mode=agent — từ chối report."},
                status=status.HTTP_409_CONFLICT,
            )
        try:
            job = Job.objects.select_related("deployment", "deployment__package_version").get(
                pk=job_id, machine=machine,
            )
        except Job.DoesNotExist:
            return Response(
                {"detail": "Job không tồn tại hoặc không thuộc máy này."}, status=status.HTTP_404_NOT_FOUND,
            )
        if job.status != JobStatus.RUNNING:
            return Response({"detail": "Job không ở trạng thái RUNNING."}, status=status.HTTP_409_CONFLICT)

        exit_code = request.data.get("exit_code")
        if exit_code is not None:
            try:
                exit_code = int(exit_code)
            except (TypeError, ValueError):
                return Response(
                    {"detail": "exit_code phải là số nguyên hoặc null."}, status=status.HTTP_400_BAD_REQUEST,
                )
        stdout = request.data.get("stdout") or ""
        error = request.data.get("error") or ""
        needs_reboot = bool(request.data.get("needs_reboot", False))
        verify_passed = request.data.get("verify_passed")  # None = không hậu kiểm, True/False = có
        skipped = bool(request.data.get("skipped", False))

        deployment = job.deployment

        if skipped:
            # Agent tự tiền kiểm thấy đã cài sẵn -> không chạy command (xem executor.py
            # _run_precheck). Ghi SKIPPED thẳng, bỏ qua toàn bộ logic success/verify/post_hook
            # bên dưới — cùng ngữ nghĩa với _probe_already_installed phía SMB (tasks.py).
            release_slot(deployment.id)
            if not _write_job_result(
                job, status=JobStatus.SKIPPED, output=stdout, error_output="",
                current_step="done", finished_at=timezone.now(),
            ):
                return Response({"detail": "Job đã bị hủy trước khi report."}, status=status.HTTP_409_CONFLICT)
            AuditLog.record(
                AuditLog.Action.JOB_FINISH, target=job, machine_hostname=machine.hostname, status=job.status,
            )
            return Response({"status": job.status})

        plan = build_action_plan(deployment, machine)
        success = exit_code is not None and exit_code in (plan.success_exit_codes or [0])
        final_error = error

        if success and verify_passed is False:
            success = False
            final_error = error or (
                f"Hậu kiểm phía agent thất bại — không đúng như kỳ vọng cho '{plan.verify_name}'."
            )

        if success and plan.post_hook:
            # post_hook (vd inventory: parse stdout -> InstalledSoftware) nhận đúng shape
            # ExecResult như path SMB — không cần sửa gì ở post_hook.
            try:
                plan.post_hook(machine, ExecResult(success=True, exit_code=exit_code, stdout=stdout))
            except Exception as e:  # noqa: BLE001
                logger.warning("post_hook lỗi cho job %s (agent, %s): %s", job.pk, machine.hostname, e)

        # Release TRƯỚC _write_job_result (không phải sau) để luôn chạy đúng 1 lần ở mọi
        # nhánh terminal, kể cả khi job bị cancel đúng lúc agent report (_write_job_result
        # trả False) — cùng nguyên tắc với collect_job_result phía SMB.
        release_slot(deployment.id)

        final_status = (
            (JobStatus.SUCCESS_REBOOT if needs_reboot else JobStatus.SUCCESS) if success else JobStatus.FAILED
        )
        base_fields = {
            "exit_code": exit_code,
            "output": stdout,
            "error_output": final_error,
            "current_step": "done" if success else "execute",
            "finished_at": timezone.now(),
        }
        if not _write_job_result(job, status=final_status, **base_fields):
            return Response({"detail": "Job đã bị hủy trước khi report."}, status=status.HTTP_409_CONFLICT)

        AuditLog.record(
            AuditLog.Action.JOB_FINISH, target=job, machine_hostname=machine.hostname,
            status=job.status, exit_code=exit_code,
        )
        return Response({"status": job.status})


class AgentPackageDownloadView(_AgentAPIView):
    throttle_scope = "agent_download"

    def get(self, request, version_id):
        machine = request.agent_machine
        pv = get_object_or_404(PackageVersion, pk=version_id)

        has_running_job = Job.objects.filter(
            machine=machine, status=JobStatus.RUNNING, deployment__package_version_id=version_id,
        ).exists()
        if not has_running_job:
            return Response(
                {"detail": "Máy này không có job RUNNING nào tham chiếu tới package version này."},
                status=status.HTTP_403_FORBIDDEN,
            )

        try:
            ok, actual = verify_integrity(pv)
        except OSError as e:
            logger.error("Không đọc được installer để verify (agent download, version %s): %s", version_id, e)
            return Response({"detail": "Không đọc được file installer trên server."}, status=500)
        if not ok:
            logger.error(
                "Integrity FAIL khi agent tải version %s — mong đợi %s, thực tế %s", version_id, pv.sha256, actual,
            )
            return Response({"detail": "Toàn vẹn installer trên server KHÔNG khớp."}, status=500)

        response = FileResponse(
            pv.installer_file.open("rb"), as_attachment=True, filename=pv.installer_file.name.split("/")[-1],
        )
        response["X-Ryandeploy-Sha256"] = pv.sha256
        return response


class AgentScriptView(_AgentAPIView):
    throttle_scope = "agent_download"

    def get(self, request, name):
        path = _SCRIPT_WHITELIST.get(name)
        if path is None:
            return Response({"detail": "Script không tồn tại."}, status=status.HTTP_404_NOT_FOUND)
        return FileResponse(open(path, "rb"), as_attachment=True, filename=name)


class AgentHeartbeatView(_AgentAPIView):
    throttle_scope = "agent_heartbeat"

    def post(self, request):
        machine = request.agent_machine
        agent_version = (request.data.get("agent_version") or "").strip()[:32]
        fields = {"is_online": True, "last_seen": timezone.now()}
        if agent_version:
            fields["agent_version"] = agent_version
        Machine.objects.filter(pk=machine.pk).update(**fields)
        return Response({"detail": "ok"})


class AgentEnrollView(APIView):
    """
    Điểm untrusted DUY NHẤT của mặt phẳng agent (máy chưa có token) — cố tình KHÔNG kế thừa
    _AgentAPIView (gắn cứng AgentTokenAuthentication). Throttle theo IP nguồn (ScopedRateThrottle
    mặc định), không theo machine vì machine chưa xác thực được.
    """

    authentication_classes = []
    permission_classes = [AllowAny]
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "agent_enroll"

    def post(self, request):
        secret = (request.data.get("secret") or "").strip()
        hostname = (request.data.get("hostname") or "").strip()
        if not secret or not hostname:
            return Response({"detail": "Thiếu secret hoặc hostname."}, status=status.HTTP_400_BAD_REQUEST)

        source_ip = request.META.get("REMOTE_ADDR", "")
        try:
            raw_token, machine = enroll_machine(secret, hostname, source_ip=source_ip)
        except EnrollmentError as e:
            logger.warning("Enroll thất bại (hostname=%s, ip=%s): %s", hostname, source_ip, e)
            return Response({"detail": str(e)}, status=status.HTTP_403_FORBIDDEN)

        AuditLog.record(
            AuditLog.Action.AGENT_ENROLL, target=machine, machine_hostname=machine.hostname,
            connection_mode=machine.connection_mode,
        )
        return Response({"token": raw_token}, status=status.HTTP_201_CREATED)
