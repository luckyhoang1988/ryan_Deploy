from django.urls import path
from rest_framework.routers import DefaultRouter

from .views import (
    PackageDownloadViewSet,
    PackageFolderViewSet,
    PackageVersionViewSet,
    PackageViewSet,
    UpdateDeployView,
    UpdatesView,
)

router = DefaultRouter()
router.register("packages", PackageViewSet, basename="package")
router.register("package-folders", PackageFolderViewSet, basename="packagefolder")
router.register("package-versions", PackageVersionViewSet, basename="packageversion")
router.register("package-downloads", PackageDownloadViewSet, basename="packagedownload")

urlpatterns = [
    path("updates/", UpdatesView.as_view(), name="updates"),
    path("updates/<int:package_id>/deploy/", UpdateDeployView.as_view(), name="updates-deploy"),
    *router.urls,
]
