from rest_framework.throttling import ScopedRateThrottle


class AgentScopedRateThrottle(ScopedRateThrottle):
    """Throttle theo machine identity (agent token) — không theo user/IP như mặc định."""

    def get_cache_key(self, request, view):
        ident = getattr(request, "agent_machine", None)
        if ident is None:
            return None
        return self.cache_format % {"scope": self.scope, "ident": ident.pk}
