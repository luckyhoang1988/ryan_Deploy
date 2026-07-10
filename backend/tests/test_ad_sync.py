"""
purge=True trong sync_computers_from_ad không được xoá máy ngoài phạm vi search_ou hiện
tại — chỉ máy thực sự thuộc scope search_ou (hoặc toàn domain, nếu search_ou không giới
hạn OU nào) mới bị coi là "đã mất khỏi AD" khi vắng mặt trong kết quả sync.
"""
from unittest.mock import MagicMock

import pytest

from apps.machines import ad_sync
from apps.machines.models import Machine


@pytest.fixture(autouse=True)
def _fake_connect(monkeypatch):
    fake_conn = MagicMock()
    monkeypatch.setattr(ad_sync, "_connect", lambda cfg: (fake_conn, ""))
    monkeypatch.setattr(
        ad_sync, "resolve_ad_config", lambda: {"SERVER": "dc1", "BIND_USER": "svc", "BASE_DN": "DC=corp,DC=local"}
    )


def _entry(name, ou_parts):
    dn = f"CN={name}," + ",".join(ou_parts) + ",DC=corp,DC=local"
    return {
        "type": "searchResEntry",
        "dn": dn,
        "attributes": {"name": name, "dNSHostName": f"{name}.corp.local", "operatingSystem": "", "operatingSystemVersion": ""},
    }


def test_scoped_purge_only_deletes_machines_in_search_scope(db, monkeypatch):
    Machine.objects.create(hostname="pc-laptop1", ad_ou="OU=Laptops,OU=IT")
    Machine.objects.create(hostname="pc-laptop2", ad_ou="OU=Laptops,OU=IT")  # đã bị xoá khỏi AD
    Machine.objects.create(hostname="pc-server1", ad_ou="OU=Servers,OU=IT")  # OU khác, ngoài scope

    # AD chỉ trả pc-laptop1 (còn tồn tại), search hẹp vào OU=Laptops,OU=IT
    monkeypatch.setattr(
        ad_sync, "_paged_computer_search",
        lambda conn, base, attrs: [_entry("pc-laptop1", ["OU=Laptops", "OU=IT"])],
    )

    result = ad_sync.sync_computers_from_ad(
        search_ou="OU=Laptops,OU=IT,DC=corp,DC=local", purge=True
    )

    assert Machine.objects.filter(hostname="pc-laptop1").exists()  # còn trong AD -> giữ
    assert not Machine.objects.filter(hostname="pc-laptop2").exists()  # trong scope, mất khỏi AD -> xoá
    assert Machine.objects.filter(hostname="pc-server1").exists()  # ngoài scope -> KHÔNG được xoá
    assert result.deleted == 1


def test_full_domain_purge_still_deletes_everything_not_returned(db, monkeypatch):
    Machine.objects.create(hostname="pc-laptop1", ad_ou="OU=Laptops,OU=IT")
    Machine.objects.create(hostname="pc-server1", ad_ou="OU=Servers,OU=IT")

    monkeypatch.setattr(
        ad_sync, "_paged_computer_search",
        lambda conn, base, attrs: [_entry("pc-laptop1", ["OU=Laptops", "OU=IT"])],
    )

    # search_ou = gốc domain (không có OU=) -> purge toàn domain như hành vi cũ.
    result = ad_sync.sync_computers_from_ad(search_ou="DC=corp,DC=local", purge=True)

    assert Machine.objects.filter(hostname="pc-laptop1").exists()
    assert not Machine.objects.filter(hostname="pc-server1").exists()
    assert result.deleted == 1
