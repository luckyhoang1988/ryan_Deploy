from django.contrib.auth.models import AnonymousUser
from django.utils import timezone
from rest_framework import exceptions
from rest_framework.authentication import BaseAuthentication, get_authorization_header

from .models import AgentToken
from .services import hash_token


class AgentTokenAuthentication(BaseAuthentication):
    """
    Xác thực máy (không phải người dùng) qua header `Authorization: Bearer <token>`.
    Mặt phẳng tin cậy hoàn toàn tách biệt khỏi session/RBAC người dùng — view dùng
    scheme này phải override authentication_classes/permission_classes, không kế thừa
    default REST_FRAMEWORK settings.
    """

    keyword = b"bearer"

    def authenticate(self, request):
        auth = get_authorization_header(request).split()
        if not auth or auth[0].lower() != self.keyword:
            return None
        if len(auth) != 2:
            raise exceptions.AuthenticationFailed("Header Authorization không hợp lệ.")

        raw = auth[1].decode("utf-8", errors="ignore")
        token_hash = hash_token(raw)
        try:
            token = AgentToken.objects.select_related("machine").get(
                token_hash=token_hash, revoked_at__isnull=True, machine__enabled=True,
            )
        except AgentToken.DoesNotExist:
            raise exceptions.AuthenticationFailed("Token agent không hợp lệ hoặc đã bị thu hồi.")

        AgentToken.objects.filter(pk=token.pk).update(last_used_at=timezone.now())
        request.agent_machine = token.machine
        return (AnonymousUser(), token)

    def authenticate_header(self, request):
        return "Bearer"
