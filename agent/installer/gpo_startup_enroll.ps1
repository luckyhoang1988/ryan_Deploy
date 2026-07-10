#Requires -Version 5.1
<#
GPO Startup Script — self-enrollment: ghi CÙNG MỘT enrollment secret cho MỌI máy trong OU/domain
vào C:\ProgramData\RyanDeployAgent\agent.ini. Agent tự đổi secret lấy token thật của riêng nó
lúc service khởi động (xem ryandeploy_agent/enrollment.py::ensure_enrolled).

Khác với gpo_startup_provision_token.ps1 (CSV token-per-hostname), script này KHÔNG cần tra cứu
%COMPUTERNAME% — cùng tham số cho toàn bộ máy đích, không cần build/publish CSV mỗi đợt rollout.

Cấu hình trong GPO: Computer Configuration > Policies > Windows Settings > Scripts (Startup) >
Startup > PowerShell Scripts, chạy dưới SYSTEM lúc boot, KHÔNG cần port inbound nào.

⚠️ BẢO MẬT: Enrollment secret truyền qua Script Parameters trong GPO — SYSVOL mặc định cho
"Authenticated Users" đọc GPT.ini/script parameters. Đây là rủi ro CHẤP NHẬN ĐƯỢC cho v1 (xem
plan_agent_enrollment.md): secret có hạn dùng (expires_at) và giới hạn OU/số lần dùng, không
vĩnh viễn như token per-machine. Vẫn nên: xoay secret định kỳ, đặt expires_in_hours sát với thời
gian rollout thực tế (không để hạn quá dài), và revoke ngay sau khi xác nhận cả OU đã enroll.

⚠️ GUARD BẮT BUỘC: script Startup chạy MỌI lần boot. Nếu agent.ini ĐÃ có `token` thật (máy đã
enroll thành công từ lần boot trước) thì PHẢI bỏ qua hoàn toàn, không ghi đè — ghi đè sẽ xóa
token thật, đẩy máy về trạng thái pending-enrollment, và lần enroll lại sẽ bị server từ chối
vĩnh viễn ("máy đã có token agent đang hoạt động") cho tới khi admin revoke thủ công.

Thứ tự xử lý GPO lúc boot: Computer Software Installation (cài MSI + start service ngay) chạy
TRƯỚC Startup Scripts. Nghĩa là lần đầu cài, service có thể khởi động trước khi agent.ini tồn
tại → service lỗi ConfigError và dừng (xem service.py::SvcDoRun). Script này vì vậy luôn chủ
động (Re)start service sau khi ghi xong agent.ini, để không phải đợi tới lần reboot kế tiếp.
#>
param(
    [Parameter(Mandatory = $true)]
    [string]$ServerUrl,

    [Parameter(Mandatory = $true)]
    [string]$EnrollmentSecret,

    # "true"/"false", hoặc đường dẫn tới file CA bundle (.pem) để verify chứng chỉ tự ký của
    # server — xem ryandeploy_agent/config.py::_parse_verify_tls.
    [string]$VerifyTls = "true",

    # Chỉ dùng khi test thủ công (trỏ ra thư mục tạm) — GPO thật KHÔNG truyền tham số này,
    # để dùng đúng đường dẫn DEFAULT_CONFIG_PATH mà ryandeploy_agent/config.py đọc.
    [string]$ProgramDataDir = "C:\ProgramData\RyanDeployAgent",

    # ⚠️ Bỏ qua CẢ HAI guard bên dưới (token thật đã có / nội dung đã khớp) và LUÔN ghi đè
    # agent.ini + restart service. Dùng cho remediation: build lại MSI với secret đúng rồi cài
    # lại lên các máy đang kẹt secret sai (chưa từng enroll thành công → không có token thật, an
    # toàn để ghi đè). KHÔNG bật cờ này cho rollout thường — nếu máy đã có token thật đang hoạt
    # động, ghi đè sẽ xóa secret khỏi agent.ini cục bộ trong khi server vẫn giữ token cũ, và máy
    # sẽ không tự enroll lại được (server từ chối "đã có token đang hoạt động") cho tới khi admin
    # revoke token cũ thủ công.
    [switch]$Force
)

$ErrorActionPreference = "Stop"

$LogDir = Join-Path $ProgramDataDir "logs"
$LogFile = Join-Path $LogDir "provision.log"
$IniPath = Join-Path $ProgramDataDir "agent.ini"

function Write-Log([string]$Message) {
    $line = "{0} {1}" -f (Get-Date -Format "yyyy-MM-dd HH:mm:ss"), $Message
    try {
        New-Item -ItemType Directory -Force -Path $LogDir | Out-Null
        Add-Content -Path $LogFile -Value $line -Encoding UTF8
    } catch {
        # Không để lỗi ghi log làm hỏng startup script — bỏ qua.
    }
}

function Protect-AgentIni([string]$Path) {
    # Siết ACL agent.ini chỉ cho SYSTEM + Administrators + user đang chạy script này — mặc định
    # ProgramData cho "Users" quyền Read, nghĩa là bất kỳ user cục bộ không-admin nào cũng đọc
    # được token/enrollment_secret trong file này (chiếm quyền agent trên server chỉ bằng cách
    # đọc file cục bộ). Dùng SID chuẩn (*S-1-5-18 = SYSTEM, *S-1-5-32-544 = Administrators) để
    # không phụ thuộc ngôn ngữ hệ điều hành. Luôn thêm SID của chính tiến trình đang ghi (SYSTEM
    # khi chạy qua GPO Startup thật — trùng SID đã có sẵn, không đổi gì; user thường khi test thủ
    # công — để Get-ExistingToken ở lần chạy kế tiếp không tự bị Access Denied). Gọi lại mỗi lần
    # script chạy (kể cả nhánh bỏ qua ghi vì đã có token thật) để backfill ACL cho máy đã rollout
    # trước khi có bản vá này.
    $grants = @("*S-1-5-18:F", "*S-1-5-32-544:F")
    try {
        $currentSid = ([Security.Principal.WindowsIdentity]::GetCurrent()).User.Value
        $grants += "*$($currentSid):F"
    } catch {
        # Không lấy được SID hiện tại — vẫn tiếp tục siết ACL với SYSTEM + Administrators.
    }
    try {
        & icacls $Path /inheritance:r /grant:r @grants | Out-Null
        Write-Log "Đã siết ACL trên '$Path' (chỉ SYSTEM + Administrators + user hiện tại)."
    } catch {
        Write-Log "Lỗi khi siết ACL trên '$Path': $($_.Exception.Message)"
    }
}

function Get-ExistingToken([string]$Path) {
    if (-not (Test-Path $Path)) {
        return $null
    }
    $line = Get-Content -Path $Path -ErrorAction SilentlyContinue |
        Where-Object { $_ -match '^\s*token\s*=\s*(\S.*)$' } |
        Select-Object -First 1
    if ($null -eq $line) {
        return $null
    }
    return ($line -replace '^\s*token\s*=\s*', '').Trim()
}

function Main {
    New-Item -ItemType Directory -Force -Path $ProgramDataDir | Out-Null

    $existingToken = Get-ExistingToken -Path $IniPath
    if ($existingToken -and -not $Force) {
        Write-Log "agent.ini đã có token thật (đã enroll trước đó) — bỏ qua, KHÔNG ghi đè."
        Protect-AgentIni -Path $IniPath
        return
    }
    if ($existingToken -and $Force) {
        Write-Log "⚠️ -Force: agent.ini có token thật nhưng vẫn ghi đè theo yêu cầu — token cũ (prefix ẩn) sẽ mất tác dụng cục bộ, cần revoke phía server nếu máy không tự enroll lại được."
    }

    $newContent = @(
        "[agent]"
        "server_url = $ServerUrl"
        "enrollment_secret = $EnrollmentSecret"
        "verify_tls = $VerifyTls"
    ) -join "`r`n"

    $existing = if (Test-Path $IniPath) { Get-Content -Path $IniPath -Raw -ErrorAction SilentlyContinue } else { $null }
    if ((-not $Force) -and $existing -and ($existing.Trim() -eq $newContent.Trim())) {
        Write-Log "agent.ini đã đúng enrollment_secret hiện tại — không ghi lại nội dung, chỉ đảm bảo ACL."
        Protect-AgentIni -Path $IniPath
        return
    }

    Set-Content -Path $IniPath -Value $newContent -Encoding ASCII
    Protect-AgentIni -Path $IniPath
    $forceNote = if ($Force) { " [Force]" } else { "" }
    Write-Log "Đã ghi agent.ini với enrollment_secret cho '$($env:COMPUTERNAME)' (server_url=$ServerUrl)$forceNote."

    try {
        $svc = Get-Service -Name "RyanDeployAgent" -ErrorAction SilentlyContinue
        if ($null -eq $svc) {
            Write-Log "Service RyanDeployAgent chưa được cài (MSI chưa tới lượt áp dụng) — bỏ qua khởi động."
            return
        }
        if ($svc.Status -eq "Running") {
            Restart-Service -Name "RyanDeployAgent" -Force
            Write-Log "Đã restart service RyanDeployAgent để agent tự enroll."
        } else {
            Start-Service -Name "RyanDeployAgent"
            Write-Log "Đã start service RyanDeployAgent."
        }
    } catch {
        Write-Log "Lỗi khi (re)start service RyanDeployAgent: $($_.Exception.Message)"
    }
}

try {
    Main
} catch {
    Write-Log "Lỗi không mong đợi: $($_.Exception.Message)"
}

# Luôn exit 0 — startup script không được làm chậm/chặn quá trình boot của máy.
exit 0
