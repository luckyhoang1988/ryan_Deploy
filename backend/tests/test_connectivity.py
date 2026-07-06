"""
Test trực tiếp connectivity.py: OR 3 tín hiệu (ping/TCP135/TCP445), short-circuit,
và xử lý exception riêng cho từng loại (icmplib vs socket).
"""
from types import SimpleNamespace

from icmplib.exceptions import ICMPSocketError, NameLookupError

from apps.machines import connectivity


def _fake_host(is_alive: bool):
    return SimpleNamespace(is_alive=is_alive)


# ---------------- _ping_ok ----------------

def test_ping_ok_true_when_icmplib_reports_alive(monkeypatch):
    monkeypatch.setattr(connectivity, "icmp_ping", lambda *a, **k: _fake_host(True))
    assert connectivity._ping_ok("host1") is True


def test_ping_ok_false_when_icmplib_reports_dead(monkeypatch):
    monkeypatch.setattr(connectivity, "icmp_ping", lambda *a, **k: _fake_host(False))
    assert connectivity._ping_ok("host1") is False


def test_ping_ok_false_on_name_lookup_error(monkeypatch):
    def boom(*a, **k):
        raise NameLookupError("no such host")

    monkeypatch.setattr(connectivity, "icmp_ping", boom)
    assert connectivity._ping_ok("bad-host") is False


def test_ping_ok_false_on_icmp_socket_error(monkeypatch):
    def boom(*a, **k):
        raise ICMPSocketError("permission denied")

    monkeypatch.setattr(connectivity, "icmp_ping", boom)
    assert connectivity._ping_ok("host1") is False  # không raise, chỉ log


# ---------------- _port_open ----------------

def test_port_open_true_on_successful_connect(monkeypatch):
    class FakeConn:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    monkeypatch.setattr(connectivity.socket, "create_connection", lambda *a, **k: FakeConn())
    assert connectivity._port_open("host1", 445) is True


def test_port_open_false_on_oserror(monkeypatch):
    def boom(*a, **k):
        raise OSError("refused")

    monkeypatch.setattr(connectivity.socket, "create_connection", boom)
    assert connectivity._port_open("host1", 445) is False


# ---------------- is_online: OR + short-circuit ----------------

def test_is_online_false_for_empty_host():
    assert connectivity.is_online("") is False


def test_is_online_true_when_ping_succeeds_short_circuits_port_checks(monkeypatch):
    calls = []
    monkeypatch.setattr(connectivity, "_ping_ok", lambda h: True)
    monkeypatch.setattr(connectivity, "_port_open", lambda h, p: calls.append(p) or True)
    assert connectivity.is_online("host1") is True
    assert calls == []  # không gọi _port_open vì ping đã OR=True


def test_is_online_true_when_only_port_135_open(monkeypatch):
    monkeypatch.setattr(connectivity, "_ping_ok", lambda h: False)
    monkeypatch.setattr(connectivity, "_port_open", lambda h, p: p == 135)
    assert connectivity.is_online("host1") is True


def test_is_online_true_when_only_port_445_open(monkeypatch):
    monkeypatch.setattr(connectivity, "_ping_ok", lambda h: False)
    monkeypatch.setattr(connectivity, "_port_open", lambda h, p: p == 445)
    assert connectivity.is_online("host1") is True


def test_is_online_false_when_all_three_fail(monkeypatch):
    monkeypatch.setattr(connectivity, "_ping_ok", lambda h: False)
    monkeypatch.setattr(connectivity, "_port_open", lambda h, p: False)
    assert connectivity.is_online("host1") is False


# ---------------- refresh_machine_status vẫn tương thích ----------------

def test_refresh_machine_status_unchanged_contract(db, monkeypatch):
    from apps.machines.models import Machine

    m = Machine.objects.create(hostname="PC-CONN-1", enabled=True)
    monkeypatch.setattr(connectivity, "is_online", lambda host: True)
    assert connectivity.refresh_machine_status(m) is True
    m.refresh_from_db()
    assert m.is_online is True
    assert m.last_seen is not None
