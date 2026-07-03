from django.contrib.auth import authenticate, login, logout
from django.db import connection
from django.middleware.csrf import get_token
from rest_framework import status
from rest_framework.decorators import api_view, permission_classes, throttle_classes
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.throttling import ScopedRateThrottle

from .permissions import user_roles


class LoginThrottle(ScopedRateThrottle):
    scope = "login"


@api_view(["GET"])
@permission_classes([AllowAny])
def health_check(request):
    """Healthcheck: kiểm tra API + kết nối DB."""
    db_ok = True
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1")
            cursor.fetchone()
    except Exception:
        db_ok = False

    status_code = 200 if db_ok else 503
    return Response(
        {"status": "ok" if db_ok else "degraded", "database": "up" if db_ok else "down"},
        status=status_code,
    )


def _user_payload(user):
    return {
        "id": user.id,
        "username": user.username,
        "is_superuser": user.is_superuser,
        "roles": sorted(user_roles(user)),
    }


@api_view(["GET"])
@permission_classes([AllowAny])
def csrf(request):
    """Đặt cookie csrftoken cho SPA."""
    return Response({"csrfToken": get_token(request)})


@api_view(["POST"])
@permission_classes([AllowAny])
@throttle_classes([LoginThrottle])
def login_view(request):
    username = request.data.get("username")
    password = request.data.get("password")
    user = authenticate(request, username=username, password=password)
    if user is None:
        return Response({"detail": "Sai tài khoản hoặc mật khẩu."}, status=status.HTTP_401_UNAUTHORIZED)
    login(request, user)
    return Response(_user_payload(user))


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def logout_view(request):
    logout(request)
    return Response({"detail": "Đã đăng xuất."})


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def me(request):
    return Response(_user_payload(request.user))


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def task_status(request, task_id):
    """
    Trạng thái một Celery task (cho các tác vụ nền: sync AD, kiểm tra online...).
    Client poll đến khi `ready=true` rồi đọc `result`.
    """
    from pydeploy.celery import app as celery_app

    res = celery_app.AsyncResult(task_id)
    payload = {"task_id": task_id, "state": res.state, "ready": res.ready()}
    if res.successful():
        payload["result"] = res.result
    elif res.failed():
        payload["error"] = str(res.result)
    return Response(payload)


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def stats(request):
    """Số liệu tổng quan cho dashboard."""
    from apps.deployments.models import Deployment
    from apps.jobs.models import Job, JobStatus
    from apps.machines.models import Machine
    from apps.packages.models import Package

    return Response(
        {
            "packages": Package.objects.count(),
            "machines": Machine.objects.count(),
            "machines_online": Machine.objects.filter(is_online=True).count(),
            "deployments": Deployment.objects.count(),
            "deployments_running": Deployment.objects.filter(status="running").count(),
            "jobs_success": Job.objects.filter(
                status__in=[JobStatus.SUCCESS, JobStatus.SUCCESS_REBOOT]
            ).count(),
            "jobs_failed": Job.objects.filter(status=JobStatus.FAILED).count(),
        }
    )
