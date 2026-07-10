#Requires -Version 5.1
<#
GPO Startup Script — rải token agent riêng từng máy vào C:\ProgramData\RyanDeployAgent\agent.ini.

Cấu hình trong GPO: Computer Configuration > Policies > Windows Settings > Scripts (Startup) >
Startup > PowerShell Scripts, chạy dưới SYSTEM lúc boot, KHÔNG cần port inbound nào.

Đặt file CSV agent_tokens.csv (cột: hostname,token — xuất từ
POST /api/machines/bulk-provision-agent-tokens/) CÙNG THƯ MỤC SYSVOL với script này, hoặc
truyền -TokenCsvPath trỏ tới đường dẫn UNC khác qua "Script Parameters" trong GPO.

⚠️ BẢO MẬT: SYSVOL mặc định cho phép "Authenticated Users" đọc — file CSV chứa token của
TOÀN BỘ máy trong danh sách. Trước khi publish, PHẢI siết ACL trên riêng file CSV này (không
phải cả thư mục Startup) chỉ cho "Domain Computers" + admin đọc, xem README.md mục "Bảo mật
CSV token". Không để CSV tồn tại lâu dài — xoá khỏi SYSVOL sau khi rollout OU đó xong.

Thứ tự xử lý GPO lúc boot: Computer Software Installation (cài MSI + start service ngay) chạy
TRƯỚC Startup Scripts. Nghĩa là lần đầu cài, service có thể khởi động trước khi agent.ini tồn
tại → service lỗi ConfigError và dừng (xem service.py::SvcDoRun). Script này vì vậy luôn chủ
động (Re)start service sau khi ghi xong agent.ini, để không phải đợi tới lần reboot kế tiếp.
#>
param(
    [Parameter(Mandatory = $true)]
    [string]$ServerUrl,

    [string]$TokenCsvPath = (Join-Path $PSScriptRoot "agent_tokens.csv"),

    # "true"/"false", hoặc đường dẫn tới file CA bundle (.pem) để verify chứng chỉ tự ký của
    # server — xem ryandeploy_agent/config.py::_parse_verify_tls.
    [string]$VerifyTls = "true",

    # Chỉ dùng khi test thủ công (trỏ ra thư mục tạm) — GPO thật KHÔNG truyền tham số này,
    # để dùng đúng đường dẫn DEFAULT_CONFIG_PATH mà ryandeploy_agent/config.py đọc.
    [string]$ProgramDataDir = "C:\ProgramData\RyanDeployAgent"
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

function Main {
    New-Item -ItemType Directory -Force -Path $ProgramDataDir | Out-Null

    if (-not (Test-Path $TokenCsvPath)) {
        Write-Log "Không tìm thấy CSV token: $TokenCsvPath — bỏ qua, giữ nguyên agent.ini hiện có (nếu có)."
        return
    }

    $computerName = $env:COMPUTERNAME
    $rows = Import-Csv -Path $TokenCsvPath
    $match = $rows | Where-Object { $_.hostname -and ($_.hostname.Split('.')[0] -ieq $computerName) } | Select-Object -First 1

    if (-not $match) {
        Write-Log "Không thấy token cho máy '$computerName' trong $TokenCsvPath — bỏ qua."
        return
    }

    $newContent = @(
        "[agent]"
        "server_url = $ServerUrl"
        "token = $($match.token)"
        "verify_tls = $VerifyTls"
    ) -join "`r`n"

    $existing = if (Test-Path $IniPath) { Get-Content -Path $IniPath -Raw -ErrorAction SilentlyContinue } else { $null }
    if ($existing -and ($existing.Trim() -eq $newContent.Trim())) {
        Write-Log "agent.ini cho '$computerName' đã đúng token hiện tại — không ghi lại."
        return
    }

    Set-Content -Path $IniPath -Value $newContent -Encoding ASCII
    Write-Log "Đã ghi agent.ini cho '$computerName' (server_url=$ServerUrl)."

    try {
        $svc = Get-Service -Name "RyanDeployAgent" -ErrorAction SilentlyContinue
        if ($null -eq $svc) {
            Write-Log "Service RyanDeployAgent chưa được cài (MSI chưa tới lượt áp dụng) — bỏ qua khởi động."
            return
        }
        if ($svc.Status -eq "Running") {
            Restart-Service -Name "RyanDeployAgent" -Force
            Write-Log "Đã restart service RyanDeployAgent để nhận token mới."
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
