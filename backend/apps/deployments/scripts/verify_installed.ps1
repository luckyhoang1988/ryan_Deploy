# RyanDeploy hậu kiểm cài đặt — kiểm registry Uninstall xem phần mềm có mặt hay không.
# -Name:    chuỗi con so khớp DisplayName (không phân biệt hoa/thường).
# -Present: 1 = kỳ vọng CÓ (sau install); 0 = kỳ vọng KHÔNG có (sau uninstall).
# Exit 0 = đúng kỳ vọng; Exit 1 = sai (dùng để đánh false-success).
param([string]$Name, [int]$Present = 1)
$ErrorActionPreference = 'SilentlyContinue'
$paths = @(
    'HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall\*',
    'HKLM:\SOFTWARE\Wow6432Node\Microsoft\Windows\CurrentVersion\Uninstall\*'
)
$found = Get-ItemProperty $paths -ErrorAction SilentlyContinue |
    Where-Object { $_.DisplayName -like "*$Name*" } |
    Select-Object -First 1
$exists = [bool]$found
if ($exists) { Write-Output "FOUND: $($found.DisplayName) $($found.DisplayVersion)" }
else { Write-Output "NOT FOUND: *$Name*" }
if ($Present -eq 1) { if ($exists) { exit 0 } else { exit 1 } }
else { if ($exists) { exit 1 } else { exit 0 } }
