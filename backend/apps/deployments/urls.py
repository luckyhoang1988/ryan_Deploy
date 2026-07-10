from rest_framework.routers import DefaultRouter

from .views import DeploymentScheduleViewSet, DeploymentViewSet

router = DefaultRouter()
router.register("deployments", DeploymentViewSet, basename="deployment")
router.register("deployment-schedules", DeploymentScheduleViewSet, basename="deploymentschedule")

urlpatterns = router.urls
