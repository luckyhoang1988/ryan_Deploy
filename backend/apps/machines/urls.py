from rest_framework.routers import DefaultRouter

from .views import MachineGroupViewSet, MachineViewSet

router = DefaultRouter()
router.register("machines", MachineViewSet, basename="machine")
router.register("machine-groups", MachineGroupViewSet, basename="machinegroup")

urlpatterns = router.urls
