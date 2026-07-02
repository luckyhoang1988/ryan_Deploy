import pytest
from django.contrib.auth.models import Group, User

from apps.core import permissions


@pytest.mark.django_db
def test_user_roles_from_groups():
    u = User.objects.create_user("op", password="x")
    g, _ = Group.objects.get_or_create(name=permissions.ROLE_OPERATOR)
    u.groups.add(g)
    assert permissions.user_roles(u) == {permissions.ROLE_OPERATOR}
    assert permissions.has_role(u, permissions.ROLE_OPERATOR, permissions.ROLE_ADMIN)
    assert not permissions.has_role(u, permissions.ROLE_ADMIN)


@pytest.mark.django_db
def test_superuser_is_admin():
    su = User.objects.create_superuser("root", "r@r.com", "x")
    assert permissions.ROLE_ADMIN in permissions.user_roles(su)


def test_anonymous_has_no_roles():
    class Anon:
        is_authenticated = False

    assert permissions.user_roles(Anon()) == set()
