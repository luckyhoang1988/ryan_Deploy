import pytest

from apps.executor.push_executor import CancelledError, ExecutorError, PushExecutor


def _ex(**kw):
    return PushExecutor(host="PC-01", username="svc", password="x", domain="CORP", **kw)


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


def test_is_auth_failure():
    ex = _ex()
    # Sai credential → không nên retry
    assert ex._is_auth_failure(Exception("SMB SessionError: STATUS_LOGON_FAILURE(...)"))
    assert ex._is_auth_failure(Exception("STATUS_ACCOUNT_LOCKED_OUT"))
    # Lỗi mạng/tạm thời → vẫn retry
    assert not ex._is_auth_failure(Exception("Connection timed out"))
    assert not ex._is_auth_failure(Exception("STATUS_BAD_NETWORK_NAME"))


def test_executor_error_retryable_default():
    assert ExecutorError("x").retryable is True
    assert ExecutorError("x", retryable=False).retryable is False
    # Hủy là loại ExecutorError không retry
    assert CancelledError().retryable is False


def test_abort_if_cancelled():
    # cancel_check=True → raise CancelledError; None hoặc False → không raise
    with pytest.raises(CancelledError):
        _ex(cancel_check=lambda: True)._abort_if_cancelled()
    _ex(cancel_check=lambda: False)._abort_if_cancelled()  # không ném
    _ex()._abort_if_cancelled()  # không có cancel_check → no-op


def test_abort_if_cancelled_swallows_check_error():
    # Lỗi trong cancel_check không được làm hỏng deploy (chỉ log, coi như chưa hủy)
    def boom():
        raise RuntimeError("db lỗi")

    _ex(cancel_check=boom)._abort_if_cancelled()  # không ném ra ngoài
