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

## 3. Cấp token + rải qua GPO Startup Script

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

## 4. Xác nhận rollout

- `Machine.agent_version` / `is_online` / `last_seen` cập nhật qua heartbeat — theo dõi trên
  trang Machines.
- `AgentToken.last_used_at` tăng khi agent poll thành công lần đầu.
- Nếu cần rollback máy nào về SMB: đổi `connection_mode` của máy về `smb` — không cần gỡ agent
  ngay (agent không tự nhận job nếu deployment không nhắm connection_mode=agent).

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
