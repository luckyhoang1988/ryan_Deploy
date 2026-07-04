from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.models import User
from django.db import connection
from django.db.models import Q
from django.middleware.csrf import get_token
from rest_framework import status, viewsets
from rest_framework.decorators import api_view, permission_classes, throttle_classes
from rest_framework.exceptions import ValidationError
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.throttling import ScopedRateThrottle

from .permissions import ROLE_ADMIN, IsAdminStrict, user_roles
from .serializers import UserSerializer


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
    from ryandeploy.celery import app as celery_app

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


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def report(request):
    """Số liệu chi tiết cho biểu đồ báo cáo trên dashboard.

    Trả về: phân bố trạng thái job/deployment, máy online/offline, và
    timeline 14 ngày gần nhất (số job hoàn tất mỗi ngày, tách thành công/thất bại).
    """
    from datetime import timedelta

    from django.db.models import Count, Q
    from django.db.models.functions import TruncDate
    from django.utils import timezone

    from apps.deployments.models import Deployment, DeploymentStatus
    from apps.jobs.models import Job, JobStatus
    from apps.machines.models import Machine

    job_raw = {r["status"]: r["c"] for r in Job.objects.values("status").annotate(c=Count("id"))}
    jobs_by_status = {
        "success": job_raw.get(JobStatus.SUCCESS, 0) + job_raw.get(JobStatus.SUCCESS_REBOOT, 0),
        "failed": job_raw.get(JobStatus.FAILED, 0),
        "running": (
            job_raw.get(JobStatus.PENDING, 0)
            + job_raw.get(JobStatus.QUEUED, 0)
            + job_raw.get(JobStatus.RUNNING, 0)
        ),
        "skipped": job_raw.get(JobStatus.SKIPPED, 0),
        "cancelled": job_raw.get(JobStatus.CANCELLED, 0),
    }

    dep_raw = {
        r["status"]: r["c"] for r in Deployment.objects.values("status").annotate(c=Count("id"))
    }
    deployments_by_status = {s.value: dep_raw.get(s.value, 0) for s in DeploymentStatus}

    machines_online = Machine.objects.filter(is_online=True).count()
    machines_total = Machine.objects.count()

    # Timeline 14 ngày: job hoàn tất mỗi ngày (theo finished_at, múi giờ dự án).
    today = timezone.localdate()
    start = today - timedelta(days=13)
    tl_raw = {
        r["day"]: r
        for r in (
            Job.objects.filter(finished_at__date__gte=start)
            .annotate(day=TruncDate("finished_at"))
            .values("day")
            .annotate(
                success=Count(
                    "id",
                    filter=Q(status__in=[JobStatus.SUCCESS, JobStatus.SUCCESS_REBOOT]),
                ),
                failed=Count("id", filter=Q(status=JobStatus.FAILED)),
            )
        )
    }
    timeline = []
    for i in range(14):
        d = start + timedelta(days=i)
        row = tl_raw.get(d)
        timeline.append(
            {
                "date": d.isoformat(),
                "success": row["success"] if row else 0,
                "failed": row["failed"] if row else 0,
            }
        )

    return Response(
        {
            "jobs_by_status": jobs_by_status,
            "deployments_by_status": deployments_by_status,
            "machines": {
                "online": machines_online,
                "offline": machines_total - machines_online,
            },
            "timeline": timeline,
        }
    )


class UserViewSet(viewsets.ModelViewSet):
    """
    Quản lý người dùng + vai trò (RBAC). Chỉ admin thao tác.
    Có bảo vệ chống tự khoá mình và chống hạ/xoá admin cuối cùng (tránh mất quyền vào hệ thống).
    """

    queryset = User.objects.all().order_by("username").prefetch_related("groups")
    serializer_class = UserSerializer
    permission_classes = [IsAdminStrict]

    @staticmethod
    def _is_admin_capable(user, *, is_active=None, role=None):
        """User còn quyền admin và đang bật? role/is_active cho phép dự đoán trạng thái sau khi sửa."""
        active = user.is_active if is_active is None else is_active
        if not active:
            return False
        if user.is_superuser:
            return True
        if role is not None:
            return role == ROLE_ADMIN
        return user.groups.filter(name=ROLE_ADMIN).exists()

    def _other_admins_exist(self, exclude_pk):
        qs = (
            User.objects.filter(is_active=True)
            .filter(Q(is_superuser=True) | Q(groups__name=ROLE_ADMIN))
            .exclude(pk=exclude_pk)
            .distinct()
        )
        return qs.exists()

    def perform_update(self, serializer):
        instance = serializer.instance
        new_active = serializer.validated_data.get("is_active", instance.is_active)
        new_role = serializer.validated_data.get("role")  # None nếu không đổi
        was_admin = self._is_admin_capable(instance)
        will_be_admin = self._is_admin_capable(instance, is_active=new_active, role=new_role)
        if was_admin and not will_be_admin and not self._other_admins_exist(instance.pk):
            raise ValidationError("Không thể hạ quyền/khoá admin cuối cùng — hệ thống sẽ mất quản trị.")
        serializer.save()

    def perform_destroy(self, instance):
        if instance.pk == self.request.user.pk:
            raise ValidationError("Không thể xoá chính tài khoản đang đăng nhập.")
        if self._is_admin_capable(instance) and not self._other_admins_exist(instance.pk):
            raise ValidationError("Không thể xoá admin cuối cùng.")
        instance.delete()
