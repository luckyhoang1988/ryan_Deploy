from apps.executor.push_executor import PushExecutor


def _ex():
    return PushExecutor(host="PC-01", username="svc", password="x", domain="CORP")


def test_share_and_disk_paths():
    ex = _ex()
    assert ex._share_path("jobX", "7z.msi") == r"PyDeploy\Runner\jobX\exec\7z.msi"
    assert ex._disk_path("jobX", "7z.msi") == r"C:\Windows\PyDeploy\Runner\jobX\exec\7z.msi"
    assert ex._share_path("jobX") == r"PyDeploy\Runner\jobX\exec"


def test_file_placeholder_substitution():
    ex = _ex()
    installer_disk = ex._disk_path("jobX", "7z.msi")
    built = "msiexec /i {file} /qn".replace("{file}", f'"{installer_disk}"')
    assert built == r'msiexec /i "C:\Windows\PyDeploy\Runner\jobX\exec\7z.msi" /qn'


def test_ignorable_start_error():
    ex = _ex()
    assert ex._is_ignorable_start_error(Exception("error 1053: service did not respond"))
    assert not ex._is_ignorable_start_error(Exception("access denied 5"))
