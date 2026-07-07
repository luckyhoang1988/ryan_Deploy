# Đóng gói RyanDeploy Agent thành 1 .exe độc lập (không cần Python trên máy đích).
# Build: pyinstaller --clean pyinstaller.spec
# Cài đặt trên máy đích: RyanDeployAgent.exe install && net start RyanDeployAgent
# Gỡ:                    net stop RyanDeployAgent && RyanDeployAgent.exe remove
a = Analysis(
    ["run_service.py"],
    pathex=[],
    binaries=[],
    datas=[],
    # win32timezone: pywin32 service framework nạp lười lúc runtime, PyInstaller không tự
    # phát hiện qua import tĩnh -> phải khai báo tay, thiếu sẽ lỗi lúc SvcDoRun trên máy đích.
    hiddenimports=["win32timezone"],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="RyanDeployAgent",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=True,
    onefile=True,
)
