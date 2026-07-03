from django.urls import path
from rest_framework.routers import DefaultRouter

from . import views

router = DefaultRouter()
router.register("users", views.UserViewSet, basename="user")

urlpatterns = [
    path("auth/csrf/", views.csrf, name="auth-csrf"),
    path("auth/login/", views.login_view, name="auth-login"),
    path("auth/logout/", views.logout_view, name="auth-logout"),
    path("auth/me/", views.me, name="auth-me"),
    path("stats/", views.stats, name="stats"),
    path("tasks/<str:task_id>/", views.task_status, name="task-status"),
    *router.urls,
]
