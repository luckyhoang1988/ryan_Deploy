# Kế hoạch: Chế độ triển khai qua Agent (song song với SMB push hiện tại)

## Context

RyanDeploy hiện đẩy phần mềm tới máy Windows hoàn toàn "agentless" qua SMB (port 445) +
impacket RPC, khởi xướng TỪ server Linux (`backend/apps/executor/push_executor.py`). Vấn đề
đang gặp: nhiều máy client (ZP-*) chặn inbound port 445 vì GPO mở firewall chưa áp dụng đúng
(94/165 job lỗi "Không kết nối được SMB ... timed out"). Việc sửa GPO/firewall trên DC đang bị
chặn vì tài khoản vnadmin không đủ quyền elevated.

Giải pháp gốc rễ hơn: cài một **agent** nhẹ trên từng máy client, agent này chủ động kết nối
**outbound** ra server qua HTTPS (port 443) để nhận job, tải installer, chạy cài đặt, và báo
kết quả về — hoàn toàn không cần mở bất kỳ port inbound nào trên máy client. Đây là hướng đi
loại bỏ tận gốc phụ thuộc vào port 445/GPO firewall cho các máy dùng agent.

Yêu cầu bắt buộc: **không phá vỡ luồng SMB hiện có**. Agent là một chế độ kết nối MỚI, chọn
theo từng máy (`Machine.connection_mode`), cùng tồn tại với SMB. Toàn bộ logic nghiệp vụ
(build_action_plan, verify_integrity, success_exit_codes, hậu kiểm registry) phải được TÁI SỬ
DỤNG nguyên vẹn cho cả hai chế độ — chỉ tầng vận chuyển (transport) là khác nhau.

Quyết định đã chốt với user:
- **Bootstrap agent lần đầu**: GPO Computer Software Installation (assign MSI, chạy lúc boot
  dưới SYSTEM, không cần port 445 inbound) + GPO Startup Script để rải token riêng từng máy.
  Không loại trừ việc dùng SMB self-push (đẩy agent như 1 package bình thường) cho các máy mà
  port 445 đang thông sẵn, như một đường phụ nhanh hơn.
- **Agent client**: Python + PyInstaller, đóng gói thành 1 `.exe` độc lập, chạy như Windows
  Service qua `pywin32`. Tái dùng tư duy/pattern từ `push_executor.py` (silent-install commands,
  exit-code/stdout capture) nhưng không phụ thuộc Django/impacket.

---

## 1. Thay đổi model

### `backend/apps/machines/models.py` — thêm vào `Machine`
```python
class ConnectionMode(models.TextChoices):
    SMB = "smb", "SMB push (agentless)"
    AGENT = "agent", "Agent (outbound HTTPS)"

connection_mode = models.CharField(max_length=8, choices=ConnectionMode.choices,
                                    default=ConnectionMode.SMB, db_index=True)
agent_version = models.CharField(max_length=32, blank=True)
```
Tái dùng nguyên `is_online`/`last_seen` đã có sẵn cho heartbeat agent (không cần field mới,
không cần sửa UI phần "last seen"). Migration mới trong `backend/apps/machines/migrations/`.

### App mới `backend/apps/agents/` (thêm vào `INSTALLED_APPS` ở `backend/ryandeploy/settings/base.py`)

`models.py`:
```python
class AgentToken(TimeStampedModel):
    machine = models.OneToOneField("machines.Machine", on_delete=models.CASCADE, related_name="agent_token")
    token_hash = models.CharField(max_length=64, unique=True, db_index=True)  # sha256 hex — không thể đảo ngược
    token_prefix = models.CharField(max_length=8, blank=True)  # phần không bí mật, để admin nhận diện trong UI/audit
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL)
    revoked_at = models.DateTimeField(null=True, blank=True)
    last_used_at = models.DateTimeField(null=True, blank=True)
```
Cố tình **hash một chiều** (không dùng Fernet vault như `DeployCredential`/`ADConfig`) vì server
chỉ cần so khớp, không bao giờ cần giải mã lại để hiển thị.

---

## 2. Xác thực agent (tách biệt hoàn toàn khỏi RBAC người dùng)

`backend/apps/agents/services.py`: `generate_token()` (`secrets.token_urlsafe(32)`),
`hash_token(raw)` (sha256 hex), `issue_token(machine, user)` (revoke token cũ của máy, tạo mới,
trả raw token **đúng 1 lần**).

`backend/apps/agents/auth.py` — `AgentTokenAuthentication(BaseAuthentication)`: parse header
`Authorization: Bearer <token>`, hash, tra `AgentToken` còn hiệu lực (`revoked_at__isnull=True`)
và `machine.enabled=True`, cập nhật `last_used_at`, gắn `request.agent_machine = token.machine`.

`backend/apps/agents/permissions.py` — `IsAuthenticatedAgent(BasePermission)`: chỉ cho qua nếu
`request.agent_machine` tồn tại.

Quan trọng: mọi view dưới `/api/agent/` phải **override hoàn toàn**
`authentication_classes`/`permission_classes` (không kế thừa default `SessionAuthentication` +
`IsViewerOrAbove` từ `REST_FRAMEWORK` trong `backend/ryandeploy/settings/base.py:125-141`) — giữ
2 mặt phẳng tin cậy (human session vs machine token) tách biệt tuyệt đối.

Cấp token: **không có endpoint tự đăng ký** (tránh rủi ro enrollment không xác thực). Thêm
action admin-only vào `MachineViewSet` (`backend/apps/machines/views.py`):
```python
@action(detail=True, methods=["post"], permission_classes=[IsAdmin])
def provision_agent_token(self, request, pk=None):
    machine = self.get_object()
    raw = issue_token(machine, request.user)
    AuditLog.record(AuditLog.Action.AGENT_TOKEN_ISSUE, target=machine, machine_hostname=machine.hostname)
    return Response({"token": raw}, status=201)  # hiển thị 1 LẦN duy nhất, không lấy lại được
```
Tự động có route `/api/machines/<id>/provision_agent_token/` qua router đã đăng ký sẵn trong
`backend/apps/machines/urls.py`. Thêm thêm 1 action `revoke_agent_token` (cùng pattern).

Thêm bulk-provision cho rollout theo OU: `POST /api/machines/bulk-provision-agent-tokens/` nhận
danh sách machine id (hoặc filter theo OU), trả CSV `hostname,token` để đưa vào GPO startup
script.

---

## 3. API mới cho agent — `backend/apps/agents/`

File: `apps.py`, `models.py`, `services.py`, `auth.py`, `permissions.py`, `throttling.py`,
`serializers.py`, `views.py`, `urls.py`, `migrations/`. Gắn route ở
`backend/ryandeploy/urls.py`: `path("api/agent/", include("apps.agents.urls"))`.

`throttling.py` — throttle theo **machine identity**, không theo user/IP:
```python
class AgentScopedRateThrottle(ScopedRateThrottle):
    def get_cache_key(self, request, view):
        ident = getattr(request, "agent_machine", None)
        return None if ident is None else self.cache_format % {"scope": self.scope, "ident": ident.pk}
```
Thêm rate vào `REST_FRAMEWORK.DEFAULT_THROTTLE_RATES` (`backend/ryandeploy/settings/base.py:137`):
`agent_poll: 20/min`, `agent_heartbeat: 6/min`, `agent_report: 20/min`, `agent_download: 10/min`.

Endpoints trong `views.py`:

- **`POST /api/agent/jobs/poll/`** — Xin slot concurrency qua
  `apps.deployments.semaphore.acquire_slot(deployment.id, deployment.max_concurrency, ttl)`
  (đúng cơ chế Redis semaphore SMB đang dùng), rồi claim nguyên tử job `QUEUED` cũ nhất của
  `request.agent_machine` — dùng lại y hệt idiom trong
  `backend/apps/jobs/tasks.py:98-103` (`Job.objects.filter(pk=..., status=QUEUED).update(status=RUNNING, attempts=F("attempts")+1, ...)`).
  Trả payload dựng từ `apps.deployments.actions.build_action_plan(deployment, machine)`
  (hàm này ĐÃ Django-aware, agentless-agnostic — tái dùng nguyên) + URL tải + sha256 +
  `install_command`/`success_exit_codes`/`verify_name`/`verify_present`. Ghi
  `AuditLog.Action.JOB_START` như path SMB.
- **`POST /api/agent/jobs/<id>/report/`** — Kiểm job thuộc đúng `request.agent_machine` và đang
  `RUNNING`, ghi kết quả cuối bằng cách gọi lại `apps.jobs.tasks._write_job_result` (tái dùng
  logic UPDATE có điều kiện loại trừ CANCELLED, tránh trùng lặp race-safety), release slot,
  ghi `AuditLog.Action.JOB_FINISH`. Body: `{exit_code, stdout, error, needs_reboot, verify_passed}`
  — hậu kiểm registry chạy PHÍA agent (local), không qua SMB như `_verify_install` hiện tại.
- **`GET /api/agent/packages/<version_id>/download/`** — stream `PackageVersion.installer_file`,
  chỉ cho phép nếu `request.agent_machine` đang có `Job` `RUNNING` tham chiếu đúng
  `package_version` đó (chặn dùng token để tải installer ngoài phạm vi job được giao). Header
  `X-Ryandeploy-Sha256` từ `PackageVersion.sha256` để agent tự verify trước khi chạy — tương
  đương `apps.packages.repository.verify_integrity` (`backend/apps/packages/repository.py:133`)
  phía server cho SMB.
- **`GET /api/agent/scripts/<name>/`** — serve whitelist `verify_installed.ps1`
  (`VERIFY_SCRIPT_PATH` trong `apps/deployments/actions.py:26`) để agent không cần đóng gói lại
  script hậu kiểm — server vẫn là nguồn chân lý duy nhất khi logic verify thay đổi.
- **`POST /api/agent/heartbeat/`** — update `Machine.is_online=True`, `last_seen=now()`,
  `agent_version` qua `.update()`.

---

## 4. Sửa Orchestrator/Celery để hỗ trợ song song 2 chế độ

**`backend/apps/deployments/orchestrator.py::launch_deployment()`** (dòng 23-70) — tạo Job cho
MỌI máy như cũ (không đổi), nhưng tách `job_ids` theo `machine.connection_mode` trước khi tạo
chord:
```python
smb_job_ids = [jid for jid, machine in zip(job_ids, machines) if machine.connection_mode == ConnectionMode.SMB]
if smb_job_ids:
    chord([deploy_to_machine.s(jid) for jid in smb_job_ids])(finalize_deployment.s(deployment.id))
# Job của máy connection_mode=agent giữ nguyên QUEUED — AgentPollView sẽ claim khi agent gọi vào.
```
Phải tránh gọi `chord([])(...)` khi deployment 100% agent-mode (fire callback ngay lập tức với 0
job SMB thật). Nếu `smb_job_ids` rỗng, không tạo chord — để `reconcile_stuck_deployments`
(watchdog định kỳ, xem bên dưới) đảm nhiệm việc finalize khi tất cả job agent xong.

**`backend/apps/jobs/tasks.py::finalize_deployment()`** (dòng 536-596) — Đã xác minh: hàm này
tính `new_status` trực tiếp từ `total_count`/`success_count`/`failed_count`/`skipped_count`
(properties tính "sống" từ `deployment.jobs`, xem `backend/apps/deployments/models.py:95-117`),
giả định MỌI job đã terminal khi được gọi (đúng với SMB-only vì chord chỉ fire sau khi tất cả
task SMB xong). Với deployment lai (mix SMB+agent), chord có thể fire khi job SMB xong nhưng
job agent vẫn `QUEUED`/`RUNNING` → tính sai status. Cần thêm guard TRƯỚC khi tính `new_status`:
```python
terminal = [JobStatus.SUCCESS, JobStatus.SUCCESS_REBOOT, JobStatus.FAILED, JobStatus.SKIPPED, JobStatus.CANCELLED]
if deployment.jobs.exclude(status__in=terminal).exists():
    logger.info("finalize_deployment: %s còn job chưa kết thúc (agent chưa report) — bỏ qua", deployment_id)
    return
```
Cơ chế watchdog `reconcile_stuck_deployments` (đã có sẵn, chạy định kỳ theo beat) sẽ gọi lại
`finalize_deployment` sau khi mọi job (kể cả agent) đã terminal — không cần task mới.

**`backend/apps/deployments/tasks.py::reconcile_stuck_deployments()`** — thêm 1 nhánh mới bên
cạnh nhánh stale-RUNNING đã có (nhánh đó tái dùng được nguyên vẹn cho job agent bị treo ở RUNNING
vì không check connection_mode): xử lý job agent `QUEUED` quá lâu mà agent chưa từng poll tới
(agent offline/chưa cài):
```python
_STUCK_AGENT_QUEUED_SECONDS = settings.RYANDEPLOY.get("AGENT_JOB_QUEUE_TIMEOUT", 3600)
queued_cutoff = now - timedelta(seconds=_STUCK_AGENT_QUEUED_SECONDS)
for job in jobs.filter(status=JobStatus.QUEUED, machine__connection_mode=ConnectionMode.AGENT,
                        created_at__lt=queued_cutoff):
    Job.objects.filter(pk=job.pk, status=JobStatus.QUEUED).update(
        status=JobStatus.FAILED,
        error_output="Agent chưa từng poll job này quá hạn — nghi agent offline/chưa cài đặt.",
        finished_at=now,
    )
```
Không cần `release_slot` ở đây vì job `QUEUED` (agent chưa claim) chưa từng xin slot — chỉ
`AgentPollView` xin slot khi claim thành công, đối xứng với path SMB (chỉ job `RUNNING` giữ slot).

Thêm setting `RYANDEPLOY["AGENT_JOB_QUEUE_TIMEOUT"]` vào `backend/ryandeploy/settings/base.py`.

---

## 5. Agent client (`agent/` — thư mục/repo riêng, KHÔNG phụ thuộc Django/Celery/impacket)

```
agent/
  ryandeploy_agent/
    service.py      # Windows service entrypoint (pywin32 ServiceFramework)
    client.py        # HTTP client mỏng cho /api/agent/*
    executor.py       # tải -> verify sha256 -> chạy install/uninstall command -> bắt stdout/exit code
    config.py         # đọc token + server URL từ C:\ProgramData\RyanDeployAgent\agent.ini
    poll_loop.py       # vòng poll -> execute -> report, backoff khi lỗi
  installer/          # WiX/MSI project cho GPO Software Installation
  pyinstaller.spec    # đóng gói thành 1 .exe độc lập (không cần Python trên máy đích)
```

Chu trình:
1. Đọc bearer token + server URL từ config cục bộ (ghi lúc GPO startup script chạy).
2. `POST /api/agent/heartbeat/` định kỳ (vd 5 phút), độc lập với vòng poll job.
3. `POST /api/agent/jobs/poll/` mỗi 15-30s (cấu hình được). Có job → tải qua
   `AgentDownloadView`, verify sha256 theo header `X-Ryandeploy-Sha256` TRƯỚC khi chạy (không
   bao giờ chạy file chưa verify), thay `{file}`/`{dir}` vào command trả về, chạy, bắt
   stdout+exit code, chạy `verify_installed.ps1` (tải qua `AgentScriptView`) nếu có
   `verify_name`, rồi `POST .../report/`.
4. Field trả về cố tình khớp shape `ExecResult` hiện tại (`exit_code`, `stdout`, `success`,
   `needs_reboot`, `error`) để `Job.exit_code`/`output`/`error_output` giống hệt dù chạy qua
   SMB hay agent — không cần sửa `JobSerializer`/frontend để hiển thị.

**Giới hạn phạm vi v1**: bỏ qua `extract_payload` (installer dạng .zip, vd Office ODT) ở lần
đầu — cần trùng lặp logic giải nén an toàn (`validate_zip_archive` trong
`backend/apps/packages/repository.py:89-130`) phía agent, để lại cho phase sau. V1 hỗ trợ
msi/exe/msu/msp + reboot/shutdown/inventory qua agent; package dạng zip tiếp tục dùng SMB.

---

## 6. Bootstrap agent lên máy client

**Chính**: GPO Computer Software Installation — đóng gói agent MSI (WiX), publish lên SYSVOL,
assign qua Computer Configuration → Policies → Software Settings → Software Installation trên
OU đích. Chạy lúc boot dưới SYSTEM, không cần port 445 inbound, không phụ thuộc GPO firewall
đang bị kẹt.

Token riêng từng máy: MSI không mang token nhúng sẵn (Software Installation không hỗ trợ tốt
per-machine property). Dùng **GPO Startup Script** (Computer Configuration → Scripts →
Startup, cũng chạy SYSTEM, cũng không cần port inbound) để ghi `agent.ini` chứa token — script
tra token theo `%COMPUTERNAME%` từ CSV do `bulk-provision-agent-tokens` (mục 2) sinh ra.

**Phụ (nhanh hơn cho máy đang thông port 445)**: đóng gói agent MSI như 1 `PackageVersion` bình
thường trong RyanDeploy, tạo `Deployment` cài đặt như mọi package khác — không cần code mới,
chỉ dùng lại toàn bộ pipeline SMB hiện có cho những máy port 445 vẫn hoạt động.

---

## 7. Bảo mật

- Bắt buộc TLS cho toàn bộ `/api/agent/` (đã có TLS qua nginx host theo ghi chú triển khai
  prod hiện tại).
- Verify sha256 phía agent trước khi thực thi file tải về (không tin file chưa verify).
- Token: hash một chiều, xoay được (`provision_agent_token` revoke-rồi-cấp-lại), thêm
  `revoke_agent_token`; hiển thị `last_used_at`/`revoked_at` trên machine detail cho admin
  theo dõi token "chết".
- Throttle theo machine identity (`AgentScopedRateThrottle`), không theo IP/user.
- Audit: thêm `AGENT_TOKEN_ISSUE`, `AGENT_TOKEN_REVOKE` vào `AuditLog.Action`
  (`backend/apps/audit/models.py`) — dùng `AuditLog.record(action, user=None, target=machine, machine_hostname=...)`
  (đã hỗ trợ `user=None` sẵn, phù hợp caller không phải người). Heartbeat KHÔNG audit mỗi lần
  (quá ồn) — chỉ log lần đầu thấy/lỗi.

---

## 8. Rollout

1. Pilot: bật `connection_mode=agent` cho đúng các máy ZP-* đang lỗi, cấp token, bootstrap qua
   SMB self-push nếu port 445 tình cờ thông, không thì qua GPO Software Installation + startup
   script.
2. Mở rộng theo OU sau khi pilot ổn định (theo dõi qua `agent_version`/`last_seen` đã có sẵn
   trên `Machine`).
3. Fallback: gặp sự cố ở máy/OU nào, đổi `connection_mode` về `smb` — không cần migrate dữ
   liệu vì `Job`/`Deployment` không phân biệt mode.
4. Toàn bộ fleet hiện tại giữ nguyên `connection_mode=smb` mặc định — tính năng này CỘNG THÊM,
   không rủi ro gì tới hành vi hiện có cho tới khi admin chủ động bật agent cho từng máy.

## 9. Frontend (thay đổi tối thiểu)

- `frontend/src/pages/Machines.jsx`: thêm cột/filter "Chế độ kết nối" (smb/agent), cột "Agent
  version"; tái dùng nguyên cột online/last-seen hiện có.
- Form sửa máy: thêm chọn `connection_mode` + nút "Cấp token agent" (admin-only), hiện token
  raw đúng 1 lần kèm cảnh báo không lấy lại được.
- `frontend/src/components/MachinePicker.jsx`: badge nhỏ phân biệt agent/SMB khi chọn máy đích
  (tuỳ chọn, giúp operator hiểu vì sao tiến trình job hiển thị khác — job agent không có các
  bước precheck/copy như SMB).
- Không cần sửa gì cho luồng realtime websocket — đã xác minh `finalize`/`_write_job_result`
  hiện tại đã dùng `.update()` (bypass `post_save` signal), tức UI hiện tại vốn đã dựa vào
  cơ chế broadcast tường minh (`broadcast_job_step`) + polling fallback, không phải signal —
  job chạy qua agent đi đúng con đường ghi dữ liệu (`Job.objects.filter().update()`) y hệt, nên
  không có gì cần thay đổi thêm ở tầng này.

---

## 10. Hợp nhất với Monitor System — giám sát HyperV qua cùng 1 agent

### Bối cảnh (đã xác minh trực tiếp trên server `10.0.193.234`, source `/home/monitorsys/monitor_system`)

Monitor System là 1 Django app **riêng biệt** (không liên quan RyanDeploy), đang giám sát
switch/firewall/HyperV/WLAN agentless: Celery Beat (`apps/collectors/tasks.py::poll_all_hyperv`,
chu kỳ `POLL_HYPERV_INTERVAL_SECS=120s`) gọi `HyperVCollector` (`apps/collectors/hyperv.py`) mở
**WinRM/NTLM outbound** từ server monitor tới 2 host Hyperv-01/Hyperv-02, chạy PowerShell từ xa
để lấy CPU/mem/disk/network counters + danh sách VM + per-volume stats, rồi `save_metrics()`
(`apps/metrics/writer.py`) ghi DB/Redis-cache, `publish_device_event()`
(`apps/realtime/publisher.py`) bắn SSE, `check_device_alerts()` (`apps/alerts/engine.py`) đánh
giá cảnh báo → Telegram/Email.

Khác với vấn đề port 445 trên máy client (do GPO firewall chặn INBOUND tới client), luồng
HyperV hiện tại không bị chặn — WinRM là outbound TỪ monitor server. Lý do hợp nhất agent không
phải "sửa lỗi kết nối" mà là: (a) tránh cài 2 agent riêng trên cùng 1 máy Windows nếu Hyperv-01/02
sau này cũng nằm trong fleet RyanDeploy, (b) loại bỏ toàn bộ độ phức tạp/rủi ro do giới hạn
**~8191 ký tự dòng lệnh khi WinRM base64-encode PowerShell qua cmd.exe** mà source Monitor
System ghi nhận là nguồn gốc nhiều bug thật (phải nén script, bỏ comment, đổi tên biến 1-2 ký
tự, từng dính bug hàm `R` bị PowerShell resolve nhầm thành alias `Invoke-History`, phải TÁCH
riêng `PS_SCRIPT`/`PS_SCRIPT_VOLUME` vì gộp chung vượt giới hạn) — chạy **local** trên chính host
loại bỏ hoàn toàn giới hạn này (dòng lệnh local `powershell.exe -File` giới hạn ~32767 ký tự, và
có thể đọc script từ file thay vì base64 qua cmd.exe).

### Thiết kế: agent RyanDeploy đảm nhiệm thêm vai trò "HyperV reporter", đẩy dữ liệu sang Monitor System

Vẫn 1 Windows Service, 1 file `.exe` duy nhất (mục 5) — nhưng agent chạy **2 vòng lặp độc lập**,
mỗi vòng bật/tắt qua config cục bộ, không phụ thuộc lẫn nhau:
- `poll_loop` (đã thiết kế ở mục 5): nhận job từ RyanDeploy `/api/agent/jobs/poll/`.
- `hyperv_report_loop` (mới): chỉ chạy trên máy có `enable_hyperv_monitor=true` trong
  `agent.ini` (chỉ Hyperv-01/02 ở v1) — thu thập metrics HyperV **local** rồi đẩy sang Monitor
  System, cấu hình bằng **server URL + token riêng, khác hoàn toàn** token RyanDeploy (2 hệ
  thống, 2 mặt phẳng tin cậy độc lập; 1 máy có thể chỉ bật 1 trong 2 vai trò, hoặc cả 2).

```
agent/ryandeploy_agent/
  hyperv_reporter.py     # thu thập local (subprocess PowerShell) -> build payload -> POST
  hyperv_script.ps1      # HỢP NHẤT lại PS_SCRIPT + PS_SCRIPT_VOLUME thành 1 script bình
                          # thường (có comment, tên biến rõ nghĩa) vì không còn giới hạn base64
```

`hyperv_reporter.py` mỗi `POLL_HYPERV_INTERVAL_SECS` (mặc định 120s, đọc từ config):
1. `subprocess.run(["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", script_path], capture_output=True, timeout=60)` — chạy local, không NTLM, không WinRM, không giới
   hạn 8191 ký tự → gộp lại thành 1 script duy nhất, dùng lại logic PowerShell gốc trong
   `hyperv.py` (Get-VM/Get-VMReplication/Get-Counter host+volume) gần như nguyên văn nhưng viết
   lại rõ ràng, có comment (an toàn vì không phải base64 qua cmd.exe nữa).
2. Parse JSON stdout thành payload khớp đúng field `NormalizedData` phía Monitor System
   (`apps/collectors/base.py`): `cpu_percent, mem_percent, uptime_secs, cpu_hv_percent,
   mem_available_mb, disk_read_iops, disk_write_iops, disk_read_latency_ms,
   disk_write_latency_ms, disk_read_throughput_mbps, disk_write_throughput_mbps,
   disk_queue_length, avg_io_size_kb, net_mbps_total, extra: {vms, volumes}` — agent tự làm luôn
   phần mà `HyperVCollector.adapt()` đang làm (fallback cpu/mem, parse boot time → uptime,
   chuẩn hoá field volume `cql/tps/sio/idt`), để Monitor System phía server chỉ cần nhận JSON đã
   chuẩn hoá, không cần biết gì về PowerShell/WinRM nữa.
3. `POST https://<monitor-server>/api/agent/hyperv/report/` với `Authorization: Bearer <token>`
   (token riêng Monitor System, xem bên dưới) + JSON payload.

### Phía Monitor System (`10.0.193.234:/home/monitorsys/monitor_system`) — thay đổi cần làm

Đây là **repo/deploy riêng** (Docker Compose, `git pull && docker compose build app worker`) —
không nằm trong `ryan_deploy`, cần thao tác trực tiếp trên repo đó (qua SSH, hoặc user đồng bộ
code về máy local trước). Chưa thực hiện, chỉ thiết kế:

1. **Model**: thêm vào `apps/devices/models.py::Device`:
   ```python
   agent_push_enabled = models.BooleanField(default=False, verbose_name="Nhận dữ liệu qua Agent (push)")
   ```
   Khi `True`: `apps/collectors/tasks.py::poll_all_hyperv()` **bỏ qua** device đó (thêm
   `.exclude(agent_push_enabled=True)` vào queryset) — tránh WinRM pull song song lãng phí/ghi
   đè dữ liệu agent vừa push. `Device.is_online`/`is_online_for_alert` giữ NGUYÊN (đã tính từ
   `last_seen`/`last_ok_seen` theo thời gian — agent chỉ cần update 2 field này giống hệt path
   pull, không cần sửa gì thêm ở property).

2. **App/token mới** (mirror pattern `AgentToken` bên RyanDeploy mục 1, nhưng **độc lập, không
   dùng chung DB/token** vì 2 Django project khác nhau): model `DeviceAgentToken` 1-1 với
   `Device`, hash một chiều (sha256), cấp qua action admin-only trên `Device` (UI đã có RBAC
   Admin/Review ở `apps/accounts`).

3. **Endpoint mới** `POST /api/agent/hyperv/report/`, auth riêng bằng bearer token ở trên
   (KHÔNG dùng session/CSRF như các view Django hiện tại), view làm đúng những gì
   `_poll_device_once` làm nhưng lấy dữ liệu từ payload thay vì gọi `collector.collect()`:
   ```python
   device = request.agent_device  # gắn bởi middleware/auth từ token
   data = NormalizedData(device_name=device.name, ip_address=device.ip_address,
                          timestamp=now(), os_family="hyperv_agent", **payload)
   save_metrics(device, data)                      # apps/metrics/writer.py — TÁI DÙNG NGUYÊN
   device.last_seen = device.last_ok_seen = now()
   device.save(update_fields=["last_seen", "last_ok_seen"])
   publish_device_event(device, True, data)         # apps/realtime/publisher.py — TÁI DÙNG NGUYÊN
   check_device_alerts(device, since)                # apps/alerts/engine.py — TÁI DÙNG NGUYÊN
   ```
   Toàn bộ pipeline ghi DB/cache, SSE realtime, alert Telegram/Email **không đổi 1 dòng** — chỉ
   thay nguồn dữ liệu đầu vào từ "pull qua WinRM" sang "push từ agent". Đây là điểm mạnh nhất
   của thiết kế: rủi ro thay đổi tối thiểu cho 1 hệ thống production đang chạy ổn định.

4. **Không cần watchdog mới** để phát hiện agent ngừng gửi: `is_online`/`is_online_for_alert` đã
   tự tính "hết hạn" theo `last_seen`/`last_ok_seen` + grace sẵn có — agent ngừng push thì 2
   field này ngừng cập nhật, property tự trả `False` sau grace, dashboard/alert hoạt động y hệt
   như khi WinRM pull thất bại liên tục.

### Rollout riêng cho phần HyperV (tách khỏi rollout RyanDeploy ở mục 8)

1. Cài agent (build từ `ryan_deploy/agent/`) thủ công lên Hyperv-01/02 (chỉ 2 máy, không cần GPO
   theo OU) — bật `enable_hyperv_monitor=true`, tắt/bật `enable_deploy_agent` tuỳ có muốn
   Hyperv-01/02 cũng nhận job RyanDeploy hay không (độc lập với vai trò monitor).
2. Chạy song song 1 thời gian: `agent_push_enabled=False` (Monitor System vẫn WinRM pull như cũ)
   + agent cũng push, đối chiếu số liệu 2 nguồn qua dashboard chi tiết HyperV để xác nhận khớp
   trước khi cắt hẳn.
3. Xác nhận khớp → bật `agent_push_enabled=True` cho Hyperv-01/02 → `poll_all_hyperv` ngừng
   WinRM tới 2 host này → có thể thu hồi tài khoản NTLM cục bộ đang lưu ở
   `Device.ssh_username/ssh_password` (đóng thêm 1 bề mặt tấn công: credential WinRM lưu trên
   server monitor không còn cần thiết nữa).
4. Fallback: đổi `agent_push_enabled=False` bất kỳ lúc nào → quay lại WinRM pull ngay (dữ liệu
   không mất, cùng schema `NormalizedData`).

### Việc còn chưa chốt / cần user xác nhận trước khi triển khai

- Thao tác sửa code Monitor System phải làm **trực tiếp trên server qua SSH** (repo chỉ tồn tại
  ở `10.0.193.234`, không có local clone) hay user muốn đồng bộ code đó về máy local trước để
  làm qua Claude Code như phần RyanDeploy? Ảnh hưởng cách thao tác (sửa file qua SSH + git
  commit trên server, vs sửa local rồi push/scp).
- Hyperv-01/02 có nằm trong fleet `Machine` của RyanDeploy chưa (để biết có cần cấp thêm
  `AgentToken` phía RyanDeploy cho 2 máy này hay chỉ cần vai trò `hyperv_monitor`)?

---

## Kiểm thử / xác nhận

- Unit test mới: `backend/apps/agents/tests/` — test claim job nguyên tử (2 poll đồng thời chỉ
  1 người thắng), test auth reject token revoked/sai, test download chặn khi job không
  `RUNNING`/không đúng machine, test `finalize_deployment` guard (mix SMB+agent không finalize
  sớm).
- Test thủ công end-to-end: 1 máy pilot (vd ZP-WH015) — cấp token, cài agent qua MSI thủ công
  trước (test nhanh, chưa cần GPO), chạy 1 Deployment install, xác nhận: job chuyển
  QUEUED→RUNNING→SUCCESS đúng qua agent, `Job.output`/`exit_code` giống format SMB, dashboard
  hiển thị đúng qua websocket.
- Chạy `python manage.py test apps.agents apps.jobs apps.deployments` sau khi implement.
- Riêng phần HyperV (mục 10): chạy song song WinRM pull + agent push trên Hyperv-01/02, đối
  chiếu số liệu CPU/mem/disk/VM giữa 2 nguồn trước khi bật `agent_push_enabled=True`; test phía
  Monitor System (`tests/collectors/`) cho endpoint `/api/agent/hyperv/report/`: reject token
  sai/thu hồi, ghi đúng `NormalizedData` qua `save_metrics`, không bị `poll_all_hyperv` pull đè
  khi `agent_push_enabled=True`.
