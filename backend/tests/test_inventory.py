"""
Phase 3 — inventory scan (parse registry JSON → InstalledSoftware) và conditional
targeting (resolve_targets theo targeting_rule).
"""
import json
from dataclasses import dataclass

import pytest

from apps.credentials.models import DeployCredential
from apps.deployments.inventory_action import _parse_software, build_inventory_plan, record_inventory
from apps.deployments.models import Deployment, DeploymentAction
from apps.deployments.targeting import resolve_targets
from apps.machines.models import InstalledSoftware, Machine


@dataclass
class FakeResult:
    stdout: str


@pytest.fixture
def credential(db):
    return DeployCredential.objects.create(name="svc", username="svc_deploy")


# ---------------- parse ----------------


def test_parse_array():
    data = [{"name": "Chrome", "version": "120.0", "publisher": "Google"}]
    assert _parse_software(json.dumps(data))[0]["name"] == "Chrome"


def test_parse_single_object_wrapped_to_list():
    # ConvertTo-Json với 1 phần tử trả object, không phải array.
    out = _parse_software(json.dumps({"name": "7-Zip", "version": "23.01"}))
    assert len(out) == 1 and out[0]["name"] == "7-Zip"


def test_parse_empty_and_garbage():
    assert _parse_software("") == []
    assert _parse_software("   ") == []
    assert _parse_software("not json at all") == []


def test_parse_with_bom_prefix():
    text = "﻿" + json.dumps([{"name": "App", "version": "1"}])
    assert _parse_software(text)[0]["name"] == "App"


# ---------------- record_inventory (post_hook) ----------------


def test_record_inventory_replaces_rows(db):
    m = Machine.objects.create(hostname="PC-INV")
    InstalledSoftware.objects.create(machine=m, name="OldApp", version="1")

    payload = json.dumps(
        [
            {"name": "Google Chrome", "version": "120.0", "publisher": "Google"},
            {"name": "7-Zip", "version": "23.01", "publisher": "Igor"},
            {"name": "Google Chrome", "version": "120.0"},  # trùng → dedupe
            {"name": "", "version": "x"},  # thiếu tên → bỏ
        ]
    )
    record_inventory(m, FakeResult(stdout=payload))

    names = set(m.installed_software.values_list("name", flat=True))
    assert names == {"Google Chrome", "7-Zip"}  # OldApp bị thay, dòng trống bị loại
    assert m.installed_software.get(name="Google Chrome").scanned_at is not None


def test_build_inventory_plan_has_hook_and_payload():
    plan = build_inventory_plan(None, None)
    assert plan.post_hook is record_inventory
    assert plan.payload_path.endswith("inventory.ps1")
    assert plan.verify_installer is False


# ---------------- resolve_targets ----------------


def _dep_with_targets(credential, machines, rule=None):
    dep = Deployment.objects.create(
        name="D", action=DeploymentAction.INSTALL, credential=credential, targeting_rule=rule
    )
    dep.target_machines.add(*machines)
    return dep


def test_no_rule_returns_all_enabled(db, credential):
    m1 = Machine.objects.create(hostname="A")
    m2 = Machine.objects.create(hostname="B", enabled=False)
    dep = _dep_with_targets(credential, [m1, m2])
    result = resolve_targets(dep)
    assert result == [m1]  # máy disabled bị loại


def test_exclude_if_software_present(db, credential):
    has = Machine.objects.create(hostname="HAS")
    missing = Machine.objects.create(hostname="MISSING")
    InstalledSoftware.objects.create(machine=has, name="Google Chrome", version="120")
    dep = _dep_with_targets(credential, [has, missing], rule={"exclude_if_software": "Chrome"})
    result = resolve_targets(dep)
    assert result == [missing]  # máy đã có Chrome bị loại


def test_exclude_with_min_version_keeps_outdated(db, credential):
    old = Machine.objects.create(hostname="OLD")
    newm = Machine.objects.create(hostname="NEW")
    InstalledSoftware.objects.create(machine=old, name="Google Chrome", version="118.0")
    InstalledSoftware.objects.create(machine=newm, name="Google Chrome", version="121.0")
    dep = _dep_with_targets(
        credential, [old, newm], rule={"exclude_if_software": "Chrome", "min_version": "120"}
    )
    result = resolve_targets(dep)
    assert result == [old]  # bản 118 < 120 → vẫn cần nâng cấp; bản 121 bị loại
