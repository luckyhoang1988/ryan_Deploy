from rest_framework.routers import DefaultRouter

from .views import DeployCredentialViewSet

router = DefaultRouter()
router.register("credentials", DeployCredentialViewSet, basename="credential")

urlpatterns = router.urls
