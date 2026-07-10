#Requires -Version 5.1
<#
Build RyanDeployAgentSetup.msi từ Product.wxs bằng WiX Toolset v3 (candle.exe + light.exe).

Yêu cầu:
  - Đã cài WiX Toolset v3.11+ (https://wixtoolset.org/releases/) — biến môi trường WIX phải
    trỏ tới thư mục cài đặt (installer WiX tự set biến này), hoặc candle.exe/light.exe có
    sẵn trong PATH. Extension WixUtilExtension (dùng cho CustomAction CAQuietExec) đi kèm sẵn
    trong bộ cài WiX chuẩn, không cần cài thêm.
  - Đã build agent\dist\RyanDeployAgent.exe bằng PyInstaller trước:
        cd agent
        pyinstaller --clean --noconfirm pyinstaller.spec

Sử dụng:
  .\build.ps1                  # không truyền -Version: tự đọc VERSION.txt và +1 revision cuối,
                                # tránh lỗi "downgrade" khi máy đích đã cài bản cao hơn
  .\build.ps1 -Version 1.2.0.0 # ép version cụ thể (vd: máy đích đang cài bản cao hơn VERSION.txt
                                # do từng build tay ở máy khác không cập nhật VERSION.txt)

  VERSION.txt lưu ProductVersion build gần nhất — build xong thành công mới ghi đè file này,
  nên nếu bạn build tay với -Version ở máy khác nhớ đồng bộ VERSION.txt lại (hoặc luôn build từ
  một chỗ duy nhất) để lần "không truyền -Version" tiếp theo không bị lệch so với máy đích.

  # Phương án A — MSI "cài là chạy": đóng cứng server + 1 secret KHÔNG HẾT HẠN (tạo trong UI
  # Machines > Enrollment Secrets > tick "Không hết hạn"). ⚠️ Secret sẽ nằm PLAINTEXT trong file
  # .msi build ra — chỉ phân phối MSI qua kênh nội bộ tin cậy, và revoke + build lại ngay nếu lộ.
  .\build.ps1 -EnrollSecret "<secret-vua-tao>"
  .\build.ps1 -EnrollSecret "<secret>" -ServerUrl "https://10.0.193.231"

  # -ForceOverwrite: dùng khi cài LẠI MSI này lên các máy đã có agent.ini SAI (vd: secret build
  # nhầm trước đó) để remediation — MSI sẽ luôn ghi đè agent.ini bằng ServerUrl/EnrollSecret mới,
  # bất kể agent.ini hiện tại đang có gì. ⚠️ CHỈ dùng khi chắc chắn các máy đích CHƯA enroll thành
  # công (chưa có token thật) — nếu máy đã có token thật đang hoạt động, ghi đè sẽ không giúp máy
  # tự enroll lại được (server vẫn từ chối vì còn token cũ) cho tới khi admin revoke token đó.
  .\build.ps1 -EnrollSecret "<secret-vua-tao>" -ForceOverwrite
#>
param(
    [string]$Version = "",
    [string]$ServerUrl = "https://10.0.193.231",
    [string]$EnrollSecret = "",
    [switch]$ForceOverwrite
)

$ErrorActionPreference = "Stop"

$versionFile = Join-Path $PSScriptRoot "VERSION.txt"
if (-not $Version) {
    $lastVersion = "1.0.0.0"
    if (Test-Path $versionFile) {
        $lastVersion = (Get-Content $versionFile -Raw).Trim()
    }
    $parts = $lastVersion.Split(".")
    if ($parts.Count -ne 4) { $parts = @("1", "0", "0", "0") }
    $parts[3] = [string]([int]$parts[3] + 1)
    $Version = $parts -join "."
    Write-Host "Không truyền -Version — tự tăng từ $lastVersion thành $Version (xem VERSION.txt)"
}

function Find-WixTool([string]$Name) {
    $cmd = Get-Command $Name -ErrorAction SilentlyContinue
    if ($cmd) { return $cmd.Source }
    if ($env:WIX) {
        $candidate = Join-Path $env:WIX "bin\$Name"
        if (Test-Path $candidate) { return $candidate }
    }
    throw "Không tìm thấy $Name. Cài WiX Toolset v3.11+ (https://wixtoolset.org/releases/) rồi thử lại."
}

$scriptDir = $PSScriptRoot
$exePath = Join-Path $scriptDir "..\dist\RyanDeployAgent.exe"
if (-not (Test-Path $exePath)) {
    throw "Không tìm thấy $exePath — chạy PyInstaller build trước (xem hướng dẫn trong README.md)."
}

$candle = Find-WixTool "candle.exe"
$light = Find-WixTool "light.exe"

$objDir = Join-Path $scriptDir "obj"
New-Item -ItemType Directory -Force -Path $objDir | Out-Null

Write-Host "candle.exe: $candle"
Write-Host "light.exe : $light"
Write-Host "Version   : $Version"
Write-Host "ServerUrl : $ServerUrl"
if ($EnrollSecret) {
    Write-Host "EnrollSecret: (đã truyền — Phương án A, MSI sẽ tự enroll lúc cài)"
    Write-Warning "Secret sẽ nằm PLAINTEXT trong $((Join-Path $scriptDir 'RyanDeployAgentSetup.msi')). Chỉ phân phối MSI này qua kênh nội bộ tin cậy."
} else {
    Write-Host "EnrollSecret: (rỗng — giữ hành vi cũ, agent.ini phải rải bằng cách khác)"
}
$forceVar = if ($ForceOverwrite) { "1" } else { "" }
if ($ForceOverwrite) {
    Write-Warning "ForceOverwrite BẬT: MSI sẽ LUÔN ghi đè agent.ini kể cả khi máy đích đã có token thật. Chỉ dùng cho remediation trên các máy CHƯA enroll thành công."
}

& $candle -dProductVersion="$Version" -dServerUrl="$ServerUrl" -dEnrollSecret="$EnrollSecret" -dForceOverwrite="$forceVar" `
    -ext WixUtilExtension -out "$objDir\" -arch x64 (Join-Path $scriptDir "Product.wxs")
if ($LASTEXITCODE -ne 0) { throw "candle.exe thất bại (exit $LASTEXITCODE)" }

$msiPath = Join-Path $scriptDir "RyanDeployAgentSetup.msi"
& $light -ext WixUtilExtension -out $msiPath (Join-Path $objDir "Product.wixobj")
if ($LASTEXITCODE -ne 0) { throw "light.exe thất bại (exit $LASTEXITCODE)" }

Set-Content -Path $versionFile -Value $Version -NoNewline
Write-Host "Đã build xong: $msiPath"
