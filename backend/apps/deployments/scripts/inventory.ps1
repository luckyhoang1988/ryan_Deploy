# RyanDeploy inventory scan — đọc phần mềm đã cài từ registry Uninstall keys
# (cả 64-bit lẫn 32-bit/Wow6432Node), xuất JSON ra stdout để backend parse.
$ErrorActionPreference = 'SilentlyContinue'
$paths = @(
    'HKLM:\Software\Microsoft\Windows\CurrentVersion\Uninstall\*',
    'HKLM:\Software\Wow6432Node\Microsoft\Windows\CurrentVersion\Uninstall\*'
)
$items = Get-ItemProperty $paths -ErrorAction SilentlyContinue |
    Where-Object { $_.DisplayName } |
    Select-Object `
        @{ N = 'name';      E = { $_.DisplayName } }, `
        @{ N = 'version';   E = { $_.DisplayVersion } }, `
        @{ N = 'publisher'; E = { $_.Publisher } }
# ConvertTo-Json: 1 phần tử -> object, nhiều -> array; backend xử lý cả hai.
$items | ConvertTo-Json -Compress
