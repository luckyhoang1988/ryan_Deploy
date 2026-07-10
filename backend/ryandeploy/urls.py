"""Root URL configuration cho RyanDeploy."""
from django.contrib import admin
from django.urls import include, path

from apps.core.views import health_check

urlpatterns = [
    path("admin/", admin.site.urls),
    path("api/health/", health_check, name="health-check"),
    path("api/", include("apps.core.urls")),
    path("api/", include("apps.packages.urls")),
    path("api/", include("apps.machines.urls")),
    path("api/", include("apps.deployments.urls")),
    path("api/", include("apps.jobs.urls")),
    path("api/", include("apps.credentials.urls")),
    path("api/", include("apps.audit.urls")),
    path("api/agent/", include("apps.agents.urls")),
]
