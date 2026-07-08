# Bootstrap RyanDeploy Agent qua GPO

Đóng gói và triển khai agent lên máy client bằng GPO Computer Software Installation +
Startup Script — không cần mở port inbound nào trên máy đích (khác với SMB push hiện có,
xem `plan_agent.md` §6).

## 1. Build MSI

```powershell
cd agent
pip install -r requirements.txt
pyinstaller --clean --noconfirm pyinstaller.spec   # ra agent\dist\RyanDeployAgent.exe

cd installer
.\build.ps1 -Version 1.0.0.0                        # ra RyanDeployAgentSetup.msi
```

Yêu cầu cài sẵn [WiX Toolset v3.11+](https://wixtoolset.org/releases/). Mỗi lần build lại để
publish bản mới, **tăng `-Version`** (vd `1.0.1.0`) — Windows Installer/GPO chỉ coi là nâng cấp
khi version tăng; `UpgradeCode` trong `Product.wxs` giữ cố định, không sửa.

MSI cài `RyanDeployAgent.exe` vào `C:\Program Files\RyanDeployAgent\` và đăng ký làm Windows
Service (`RyanDeployAgent`, LocalSystem, tự khởi động cùng máy).

## 2. Publish MSI qua GPO Computer Software Installation

1. Copy `RyanDeployAgentSetup.msi` vào một share UNC mà máy tính (computer account) đọc được,
   vd `\\corp.local\SYSVOL\corp.local\dfs\RyanDeployAgent\RyanDeployAgentSetup.msi`.
2. Group Policy Management → tạo/sửa GPO link vào OU đích → **Computer Configuration → Policies
   → Software Settings → Software Installation** → New → Package → trỏ tới đường dẫn UNC ở
   trên → chọn **Assigned** (không phải Published — Published chỉ dùng cho user-targeted qua
   Add/Remove Programs).
3. Máy trong OU cần **reboot** để nhận cài đặt lần đầu (Computer Software Installation chỉ áp
   dụng lúc khởi động máy, không áp dụng lúc `gpupdate` thông thường).

## 3. Cấp quyền hàng loạt: Self-enrollment theo OU (khuyến nghị cho rollout ≥ 50-100 máy)

Thay vì cấp 1000 token riêng cho 1000 máy (Phương án B bên dưới), tạo **đúng 1 "enrollment
secret"** dùng chung cho cả OU (hoặc toàn domain), publish **cùng một script/tham số** cho mọi
máy đích — agent tự gọi `/api/agent/enroll/` lúc khởi động lần đầu để đổi secret lấy token thật
của riêng nó, ghi vào `agent.ini` cục bộ, rồi hoạt động như bình thường. Từ góc nhìn admin:
1000 máy → 1 thao tác tạo secret, 0 thao tác cấp/rải token thủ công.

1. Tạo enrollment secret (qua UI trang Machines → "Enrollment Secrets", hoặc API trực tiếp):
   ```
   POST /api/enrollment-secrets/
   Body: {"ad_ou": "OU=ZP,DC=corp,DC=local", "expires_in_hours": 48}
   ```
   Để trống `ad_ou` = secret **global** (mọi OU) — tiện cho rollout toàn công ty 1 lần, đổi lại
   rủi ro cao hơn nếu lộ (bất kỳ máy nào biết secret cũng enroll được). `expires_at`/
   `expires_in_hours` là bắt buộc — đặt sát với thời gian rollout thực tế thay vì để hạn dài.
   `max_uses` (optional) giới hạn thêm số lần dùng nếu biết trước số máy trong đợt.
   Response trả về secret dạng plaintext **đúng 1 lần duy nhất** — lưu lại ngay, không xem lại
   được sau đó (giống `provision_agent_token`).

2. Copy `gpo_startup_enroll.ps1` vào thư mục script Startup của GPO (Group Policy Management →
   GPO → Edit → **Computer Configuration → Policies → Windows Settings → Scripts → Startup** →
   PowerShell Scripts → Add), Script Parameters — **giống hệt cho mọi máy trong OU/domain**,
   không cần tra `%COMPUTERNAME%` hay build CSV:
   ```
   -ServerUrl "https://ryandeploy.corp.local" -EnrollmentSecret "<secret-vua-tao>"
   ```

3. Máy trong OU boot lên: script ghi `server_url` + `enrollment_secret` vào `agent.ini`, (re)start
   service `RyanDeployAgent` → service gọi `/api/agent/enroll/`, nhận token thật, tự ghi đè
   `agent.ini` (xóa `enrollment_secret`, thêm `token`) qua `ryandeploy_agent/enrollment.py`. Nếu
   máy chưa tồn tại trong hệ thống (chưa sync AD) hoặc server tạm unreachable, agent tự retry với
   backoff (tối đa 300s) tới khi thành công hoặc service bị dừng.

   ⚠️ **Guard bắt buộc đã có sẵn trong script**: nếu `agent.ini` ĐÃ có `token` thật (máy đã enroll
   từ lần boot trước), script bỏ qua hoàn toàn, KHÔNG ghi đè — vì Startup Script chạy MỌI lần
   boot, ghi đè sẽ xóa token thật, đẩy máy về pending-enrollment, và enroll lại sẽ bị server từ
   chối vĩnh viễn ("máy đã có token agent đang hoạt động") cho tới khi admin revoke thủ công.

4. Theo dõi rollout qua `use_count`/`last_used_at` của secret (trang "Enrollment Secrets") và
   `AgentToken.last_used_at` của từng máy (machine detail — xem thêm mục "4. Xác nhận rollout"
   bên dưới, áp dụng chung cho cả hai phương án). Khi các máy trong OU đã enroll và poll thành
   công, **thu hồi (revoke) secret** để đóng cửa sổ có thể enroll thêm bằng secret đó (secret
   cũng tự hết hạn theo `expires_at` nếu quên revoke).

### Phương án B: Token per-machine qua CSV (case cần siết chặt hơn, hoặc máy ngoài AD)

Dùng khi cần kiểm soát chặt từng máy (mỗi token gắn cứng 1 hostname, không có cửa sổ dùng chung),
hoặc re-enroll một máy đã bị revoke (secret dùng chung không áp dụng được cho máy đã có token).

1. Cấp token hàng loạt cho các máy trong OU (admin, qua UI hoặc API trực tiếp):
   ```
   POST /api/machines/bulk-provision-agent-tokens/
   Body: {"ad_ou": "OU=ZP,DC=corp,DC=local"}   # hoặc {"machine_ids": [1,2,3]}
   ```
   Trả về CSV `hostname,token` — tải về máy admin trạm.

2. **Bảo mật CSV token — bắt buộc trước khi publish lên SYSVOL:**
   CSV này chứa token của TOÀN BỘ máy trong đợt cấp. SYSVOL mặc định cho "Authenticated
   Users" quyền đọc toàn bộ cây thư mục Policies — nếu để CSV lẫn trong đó với ACL mặc định,
   BẤT KỲ user domain nào cũng đọc được token của mọi máy trong danh sách (token bị lộ =
   attacker giả làm agent của máy đó, poll/nhận job, xem payload deployment gán cho máy đó).

   Giảm thiểu bắt buộc:
   - Đặt CSV trong một thư mục con RIÊNG trong SYSVOL (không chung với Startup script nếu có
     thể đặt script trỏ ra ngoài), rồi **siết ACL riêng cho file/thư mục đó**: bỏ kế thừa từ
     SYSVOL, chỉ cấp Read cho nhóm "Domain Computers" + Full Control cho Domain Admins/SYSTEM,
     **deny hoặc bỏ hẳn "Authenticated Users"/"Everyone"**.
   - Chỉ cấp/publish CSV theo TỪNG OU một lúc rollout (đã hỗ trợ sẵn qua tham số `ad_ou` ở
     bước 1) — giới hạn phạm vi lộ nếu ACL bị cấu hình sai, thay vì một CSV chứa token của
     toàn bộ fleet.
   - Sau khi các máy trong OU đã boot và nhận token thành công (kiểm qua `last_used_at` của
     `AgentToken` trên machine detail), **xoá CSV khỏi SYSVOL** — CSV chỉ là artifact bootstrap
     một lần, không cần tồn tại lâu dài.
   - Nếu nghi ngờ CSV đã bị lộ: gọi lại `provision_agent_token`/`bulk-provision-agent-tokens`
     để xoay token (tự động thu hồi token cũ), publish CSV mới.

3. Copy `gpo_startup_provision_token.ps1` + CSV (`agent_tokens.csv`) vào cùng thư mục script
   Startup của GPO (Group Policy Management → GPO → Edit → **Computer Configuration → Policies
   → Windows Settings → Scripts → Startup** → PowerShell Scripts → Add), Script Parameters:
   ```
   -ServerUrl "https://ryandeploy.corp.local" -TokenCsvPath "agent_tokens.csv"
   ```
   (`TokenCsvPath` mặc định là cùng thư mục với script nên có thể bỏ qua nếu CSV đặt cùng chỗ.)

Script tự tạo `C:\ProgramData\RyanDeployAgent\agent.ini` đúng máy theo `%COMPUTERNAME%`, ghi
log vào `C:\ProgramData\RyanDeployAgent\logs\provision.log`, và tự (re)start service
`RyanDeployAgent` sau khi ghi token — xử lý đúng thứ tự GPO thật (Software Installation chạy
trước Startup Scripts, nên lần cài đầu service có thể khởi động trước khi có `agent.ini`).

## 4. Xác nhận rollout, rồi mới chuyển máy sang nhận job qua agent

- `Machine.agent_version` / `is_online` / `last_seen` cập nhật qua heartbeat — theo dõi trên
  trang Machines.
- `AgentToken.last_used_at` tăng khi agent poll thành công lần đầu. **Lưu ý:** có token hợp lệ
  và poll được KHÔNG có nghĩa máy đã nhận job — `AgentJobPollView` chỉ trả job cho máy đang ở
  `connection_mode=agent` (mặc định mọi máy là `smb`). Đây là chốt an toàn cố ý để tách "agent
  đã cài và liên lạc được" khỏi "máy này đã sẵn sàng nhận job qua agent".
- Sau khi xác nhận các máy trong OU đã poll thành công (`last_used_at` khác null), chuyển hàng
  loạt sang `connection_mode=agent`:
  ```
  POST /api/machines/bulk-set-connection-mode/
  Body: {"ad_ou": "OU=ZP,DC=corp,DC=local", "connection_mode": "agent"}
  ```
  (hoặc `{"machine_ids": [1,2,3], "connection_mode": "agent"}` cho danh sách cụ thể — dùng cho
  pilot trước khi mở rộng cả OU). Chỉ từ lúc này máy mới thực sự nhận job qua agent thay vì SMB.
- Rollback: gọi lại API trên với `connection_mode: "smb"` cho máy/OU cần rollback — không cần
  gỡ agent ngay (agent không tự nhận job nếu đang ở connection_mode=smb).

## Giới hạn đã biết

- MSI/candle/light chưa được build thử trong môi trường dev (không có WiX Toolset cài sẵn) —
  `Product.wxs` đã được kiểm tra well-formed XML, nhưng việc build MSI thật và cài/uninstall
  trên một máy Windows thật (kiểm tra ServiceInstall/ServiceControl hoạt động đúng) cần làm ở
  môi trường có WiX + quyền admin, chưa nằm trong phạm vi test tự động ở đây.
- `gpo_startup_provision_token.ps1` đã test thật bằng PowerShell (ghi đúng `agent.ini`, idempotent
  khi token không đổi, bỏ qua an toàn khi thiếu CSV/không khớp hostname, và file `agent.ini`
  sinh ra đã được xác nhận đọc đúng bằng `ryandeploy_agent.config.load_config` thật) — riêng
  nhánh (Re)start service chưa test được vì máy dev không có service `RyanDeployAgent` cài
  sẵn (nhánh "service chưa cài — bỏ qua" đã test; nhánh restart/start thật cần máy đã cài MSI).
- `gpo_startup_enroll.ps1` đã test thật bằng PowerShell: ghi đúng `[agent]` với `enrollment_secret`
  khi `agent.ini` chưa tồn tại, idempotent khi chạy lại với secret không đổi, và **guard quan
  trọng nhất** (agent.ini đã có `token` thật → bỏ qua hoàn toàn, không ghi đè) đã xác nhận hoạt
  động đúng. File `.ps1` phải lưu **UTF-8 có BOM** (giống file `_provision_token.ps1` cũ) — nếu
  không, Windows PowerShell 5.1 đọc sai codepage phần comment tiếng Việt và báo lỗi parse ("string
  missing terminator"). Nhánh (Re)start service có cùng giới hạn test như script cũ ở trên.
