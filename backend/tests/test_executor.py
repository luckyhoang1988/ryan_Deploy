import pytest

from apps.executor.push_executor import CancelledError, ExecutorError, PushExecutor


def _ex(**kw):
    return PushExecutor(host="PC-01", username="svc", password="x", domain="CORP", **kw)


def test_share_and_disk_paths():
    ex = _ex()
    assert ex._share_path("jobX", "7z.msi") == r"RyanDeploy\Runner\jobX\exec\7z.msi"
    assert ex._disk_path("jobX", "7z.msi") == r"C:\Windows\RyanDeploy\Runner\jobX\exec\7z.msi"
    assert ex._share_path("jobX") == r"RyanDeploy\Runner\jobX\exec"


def test_file_placeholder_substitution():
    ex = _ex()
    installer_disk = ex._disk_path("jobX", "7z.msi")
    built = "msiexec /i {file} /qn".replace("{file}", f'"{installer_disk}"')
    assert built == r'msiexec /i "C:\Windows\RyanDeploy\Runner\jobX\exec\7z.msi" /qn'


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


def test_precheck_dns_failure(monkeypatch):
    # DNS không resolve → lỗi rõ ràng nhắc DNS, tách khỏi lỗi cổng đóng.
    import socket

    def boom(*a, **k):
        raise socket.gaierror("Name or service not known")

    monkeypatch.setattr(socket, "getaddrinfo", boom)
    with pytest.raises(ExecutorError, match="DNS"):
        _ex()._precheck()


class _FakeConn:
    """SMBConnection giả: ghi lại putFile/createDirectory thay vì gọi SMB thật."""

    def __init__(self):
        self.files = {}
        self.dirs = []

    def createDirectory(self, share, path):
        self.dirs.append(path)

    def putFile(self, share, path, read_cb):
        buf = b""
        while True:
            chunk = read_cb(65536)
            if not chunk:
                break
            buf += chunk
        self.files[path] = buf


def test_copy_payload_extract_zip_generates_tar_and_dir_token(tmp_path):
    ex = _ex()
    ex._conn = _FakeConn()
    payload = tmp_path / "src.zip"
    payload.write_bytes(b"PK\x03\x04fakezip")
    template = '"{dir}\\setup.exe" /S'

    ex._copy_payload("jobZ", template, str(payload), "src.zip", True)

    bat = ex._conn.files[ex._share_path("jobZ", "run.bat")].decode()
    payload_disk = ex._disk_path("jobZ", "src.zip")
    extract_disk = ex._disk_path("jobZ", "extracted")
    expected_command = template.replace("{dir}", f'"{extract_disk}"')

    assert ex._share_path("jobZ", "extracted") in ex._conn.dirs
    assert f'tar -xf "{payload_disk}" -C "{extract_disk}"' in bat
    assert f"{expected_command} >>" in bat  # append vì đứng sau lệnh giải nén
    # Lệnh giải nén phải đứng TRƯỚC lệnh chính trong bat.
    assert bat.index("tar -xf") < bat.index(expected_command)


class _FakeEntry:
    def __init__(self, name, is_dir=False):
        self._name = name
        self._is_dir = is_dir

    def get_longname(self):
        return self._name

    def is_directory(self):
        return self._is_dir


class _FakeCleanupConn:
    """SMBConnection giả mô phỏng cây thư mục lồng nhau (VD "extracted" của archive
    .zip) để test xóa đệ quy."""

    def __init__(self, tree):
        self.tree = tree  # path (không có "\*") -> list[_FakeEntry]
        self.deleted_files = []
        self.deleted_dirs = []

    def listPath(self, share, pattern):
        path = pattern[:-2]  # bỏ hậu tố "\*"
        return self.tree.get(path, [])

    def deleteFile(self, share, path):
        self.deleted_files.append(path)

    def deleteDirectory(self, share, path):
        self.deleted_dirs.append(path)


def test_delete_exec_dir_recurses_into_nested_extracted_subdir():
    # Trước fix: chỉ xóa file ở cấp trên cùng — thư mục con "extracted" (giải nén .zip)
    # bị bỏ lại vĩnh viễn trên máy đích vì deleteFile/deleteDirectory fail âm thầm.
    ex = _ex()
    exec_dir = ex._share_path("jobR")
    extracted = exec_dir + "\\extracted"
    nested = extracted + "\\sub"

    tree = {
        exec_dir: [_FakeEntry("run.bat"), _FakeEntry("extracted", is_dir=True)],
        extracted: [_FakeEntry("readme.txt"), _FakeEntry("sub", is_dir=True)],
        nested: [_FakeEntry("deep.txt")],
    }
    ex._conn = _FakeCleanupConn(tree)

    ex._delete_exec_dir("jobR")

    conn = ex._conn
    assert exec_dir + "\\run.bat" in conn.deleted_files
    assert extracted + "\\readme.txt" in conn.deleted_files
    assert nested + "\\deep.txt" in conn.deleted_files
    # Thư mục con phải được xóa TRƯỚC thư mục cha (nested < extracted < exec_dir).
    assert conn.deleted_dirs.index(nested) < conn.deleted_dirs.index(extracted)
    assert conn.deleted_dirs.index(extracted) < conn.deleted_dirs.index(exec_dir)
    assert f"{ex.target_dir}\\jobR" in conn.deleted_dirs


def test_copy_payload_no_extract_keeps_single_file_redirect(tmp_path):
    ex = _ex()
    ex._conn = _FakeConn()
    payload = tmp_path / "app.exe"
    payload.write_bytes(b"MZfake")
    template = '"{file}" /S'

    ex._copy_payload("jobY", template, str(payload), "app.exe", False)

    bat = ex._conn.files[ex._share_path("jobY", "run.bat")].decode()
    payload_disk = ex._disk_path("jobY", "app.exe")
    expected_command = template.replace("{file}", f'"{payload_disk}"')

    assert "tar -xf" not in bat
    assert ex._share_path("jobY", "extracted") not in ex._conn.dirs
    assert f"{expected_command} > " in bat
    assert f"{expected_command} >> " not in bat
