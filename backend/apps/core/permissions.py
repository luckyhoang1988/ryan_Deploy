"""
RBAC đơn giản dựa trên Django Groups: admin / operator / viewer.
- viewer   : chỉ đọc (SAFE_METHODS).
- operator : đọc + tạo/kích hoạt deployment.
- admin    : toàn quyền (gồm quản lý credential/package/machine).
superuser luôn được coi là admin.
"""
from rest_framework.permissions import SAFE_METHODS, BasePermission

ROLE_ADMIN = "admin"
ROLE_OPERATOR = "operator"
ROLE_VIEWER = "viewer"


def user_roles(user) -> set[str]:
    if not user or not user.is_authenticated:
        return set()
    roles = set(user.groups.values_list("name", flat=True))
    if user.is_superuser:
        roles.add(ROLE_ADMIN)
    return roles


def has_role(user, *allowed: str) -> bool:
    return bool(user_roles(user).intersection(allowed))


class IsViewerOrAbove(BasePermission):
    """Đọc: mọi user đã đăng nhập. Ghi: operator hoặc admin."""

    def has_permission(self, request, view):
        if not (request.user and request.user.is_authenticated):
            return False
        if request.method in SAFE_METHODS:
            return True
        return has_role(request.user, ROLE_OPERATOR, ROLE_ADMIN)


class IsOperatorOrAbove(BasePermission):
    def has_permission(self, request, view):
        if request.method in SAFE_METHODS:
            return bool(request.user and request.user.is_authenticated)
        return has_role(request.user, ROLE_OPERATOR, ROLE_ADMIN)


class IsAdmin(BasePermission):
    """Toàn bộ thao tác yêu cầu quyền admin (dùng cho credential)."""

    def has_permission(self, request, view):
        if request.method in SAFE_METHODS:
            return bool(request.user and request.user.is_authenticated)
        return has_role(request.user, ROLE_ADMIN)


class IsAdminStrict(BasePermission):
    """Admin cho MỌI method (kể cả đọc). Dùng cho quản lý người dùng — không lộ danh sách."""

    def has_permission(self, request, view):
        return has_role(request.user, ROLE_ADMIN)
