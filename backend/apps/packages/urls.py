from rest_framework.routers import DefaultRouter

from .views import PackageVersionViewSet, PackageViewSet

router = DefaultRouter()
router.register("packages", PackageViewSet, basename="package")
router.register("package-versions", PackageVersionViewSet, basename="packageversion")

urlpatterns = router.urls
