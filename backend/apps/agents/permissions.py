from rest_framework.permissions import BasePermission


class IsAuthenticatedAgent(BasePermission):
    """Chỉ cho qua nếu AgentTokenAuthentication đã gắn được request.agent_machine."""

    def has_permission(self, request, view):
        return getattr(request, "agent_machine", None) is not None
