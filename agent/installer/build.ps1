#Requires -Version 5.1
<#
Build RyanDeployAgentSetup.msi từ Product.wxs bằng WiX Toolset v3 (candle.exe + light.exe).

Yêu cầu:
  - Đã cài WiX Toolset v3.11+ (https://wixtoolset.org/releases/) — biến môi trường WIX phải
    trỏ tới thư mục cài đặt (installer WiX tự set biến này), hoặc candle.exe/light.exe có
    sẵn trong PATH.
  - Đã build agent\dist\RyanDeployAgent.exe bằng PyInstaller trước:
        cd agent
        pyinstaller --clean --noconfirm pyinstaller.spec

Sử dụng:
  .\build.ps1                  # dùng version mặc định 1.0.0.0
  .\build.ps1 -Version 1.2.0.0 # tăng version mỗi lần rebuild để GPO nhận là upgrade
#>
param(
    [string]$Version = "1.0.0.0"
)

$ErrorActionPreference = "Stop"

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

& $candle -dProductVersion="$Version" -out "$objDir\" -arch x64 (Join-Path $scriptDir "Product.wxs")
if ($LASTEXITCODE -ne 0) { throw "candle.exe thất bại (exit $LASTEXITCODE)" }

$msiPath = Join-Path $scriptDir "RyanDeployAgentSetup.msi"
& $light -out $msiPath (Join-Path $objDir "Product.wixobj")
if ($LASTEXITCODE -ne 0) { throw "light.exe thất bại (exit $LASTEXITCODE)" }

Write-Host "Đã build xong: $msiPath"
