"""
Kiểm thử action-planner (build_action_plan) và validate của DeploymentSerializer
cho các loại action: install / uninstall / reboot / shutdown.
(inventory được kiểm ở test_inventory.py)
"""
import pytest
from django.contrib.auth.models import Group, User
from django.test import Client

from apps.credentials.models import DeployCredential
from apps.deployments.actions import REBOOT_COMMAND, SHUTDOWN_COMMAND, build_action_plan
from apps.deployments.models import Deployment, DeploymentAction
from apps.deployments.serializers import DeploymentSerializer
from apps.machines.models import Machine
from apps.packages.models import InstallerType, Package, PackageVersion


@pytest.fixture
def credential(db):
    return DeployCredential.objects.create(name="svc", username="svc_deploy")


@pytest.fixture
def machine(db):
    return Machine.objects.create(hostname="PC-1")


def _pv(**kw):
    pkg = Package.objects.create(name=kw.pop("pkg_name", "Office"))
    defaults = dict(
        package=pkg,
        version="1",
        installer_file="repository/x/1/s.exe",
        installer_type=InstallerType.EXE,
        install_command='"{file}" /S',
    )
    defaults.update(kw)
    return PackageVersion.objects.create(**defaults)


def _dep(credential, action, pv=None):
    return Deployment.objects.create(name="D", action=action, package_version=pv, credential=credential)


# ---------------- build_action_plan ----------------


def test_install_plan_uploads_installer(credential, machine):
    dep = _dep(credential, DeploymentAction.INSTALL, _pv())
    plan = build_action_plan(dep, machine)
    assert plan.command == '"{file}" /S'
    assert plan.payload_filename == "s.exe"
    assert plan.payload_path  # có đường dẫn installer
    assert plan.verify_installer is True


def test_uninstall_by_productcode_skips_payload(credential, machine):
    # msiexec /x {ProductCode}: không tham chiếu {file} → không đẩy installer, không verify.
    dep = _dep(credential, DeploymentAction.UNINSTALL, _pv(uninstall_command="msiexec /x {12345} /qn"))
    plan = build_action_plan(dep, machine)
    assert plan.payload_path is None
    assert plan.payload_filename is None
    assert plan.verify_installer is False
    assert plan.command == "msiexec /x {12345} /qn"


def test_uninstall_with_file_uploads_installer(credential, machine):
    dep = _dep(credential, DeploymentAction.UNINSTALL, _pv(uninstall_command='"{file}" /uninstall /S'))
    plan = build_action_plan(dep, machine)
    assert plan.payload_filename == "s.exe"
    assert plan.verify_installer is True


def test_reboot_plan_is_payloadless(credential, machine):
    plan = build_action_plan(_dep(credential, DeploymentAction.REBOOT), machine)
    assert plan.command == REBOOT_COMMAND
    assert plan.payload_path is None
    assert plan.success_exit_codes == [0]


def test_shutdown_plan_is_payloadless(credential, machine):
    plan = build_action_plan(_dep(credential, DeploymentAction.SHUTDOWN), machine)
    assert plan.command == SHUTDOWN_COMMAND
    assert plan.payload_path is None


# ---------------- serializer.validate ----------------


def _serializer(credential, machine, **data):
    base = {"name": "D", "credential": credential.id, "target_machines": [machine.id]}
    base.update(data)
    return DeploymentSerializer(data=base)


def test_install_requires_package_version(credential, machine):
    s = _serializer(credential, machine, action="install")
    assert not s.is_valid()
    assert "package_version" in s.errors


def test_reboot_rejects_package_version(credential, machine):
    s = _serializer(credential, machine, action="reboot", package_version=_pv().id)
    assert not s.is_valid()
    assert "package_version" in s.errors


def test_reboot_valid_without_package_version(credential, machine):
    s = _serializer(credential, machine, action="reboot")
    assert s.is_valid(), s.errors


def test_uninstall_requires_uninstall_command(credential, machine):
    # PackageVersion chưa có uninstall_command → phải bị từ chối.
    s = _serializer(credential, machine, action="uninstall", package_version=_pv().id)
    assert not s.is_valid()
    assert "package_version" in s.errors


def test_uninstall_valid_with_uninstall_command(credential, machine):
    pv = _pv(uninstall_command="msiexec /x {12345} /qn")
    s = _serializer(credential, machine, action="uninstall", package_version=pv.id)
    assert s.is_valid(), s.errors


# ---------------- RBAC: reboot/shutdown chỉ admin được trigger ----------------


def _client(username, password, role=None, superuser=False):
    for name in ("admin", "operator", "viewer"):
        Group.objects.get_or_create(name=name)
    if superuser:
        User.objects.create_superuser(username, f"{username}@x.com", password)
    else:
        u = User.objects.create_user(username, f"{username}@x.com", password)
        if role:
            u.groups.add(Group.objects.get(name=role))
    c = Client()
    c.post(
        "/api/auth/login/",
        {"username": username, "password": password},
        content_type="application/json",
    )
    return c


def _create_reboot_dep(client, credential, machine):
    r = client.post(
        "/api/deployments/",
        {"name": "R", "action": "reboot", "credential": credential.id, "target_machines": [machine.id]},
        content_type="application/json",
    )
    assert r.status_code == 201, r.content
    return r.json()["id"]


def test_operator_cannot_trigger_reboot(credential, machine):
    op = _client("op", "pass12345", role="operator")
    dep_id = _create_reboot_dep(op, credential, machine)
    t = op.post(f"/api/deployments/{dep_id}/trigger/", {}, content_type="application/json")
    assert t.status_code == 403


def test_admin_can_trigger_reboot(credential, machine, monkeypatch):
    # Không thực sự fan-out (celery eager sẽ gọi executor/SMB thật) → chặn ở launch.
    from apps.deployments import views as dep_views

    monkeypatch.setattr(dep_views, "launch_deployment", lambda d: 1)
    admin = _client("root", "pass12345", superuser=True)
    dep_id = _create_reboot_dep(admin, credential, machine)
    t = admin.post(f"/api/deployments/{dep_id}/trigger/", {}, content_type="application/json")
    assert t.status_code == 202
