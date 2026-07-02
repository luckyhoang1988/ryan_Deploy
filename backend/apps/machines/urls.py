from django.urls import path
from rest_framework.routers import DefaultRouter

from .views import (
    ADConfigTestView,
    ADConfigView,
    MachineGroupViewSet,
    MachineViewSet,
)

router = DefaultRouter()
router.register("machines", MachineViewSet, basename="machine")
router.register("machine-groups", MachineGroupViewSet, basename="machinegroup")

urlpatterns = [
    path("ad-config/", ADConfigView.as_view(), name="ad-config"),
    path("ad-config/test/", ADConfigTestView.as_view(), name="ad-config-test"),
    *router.urls,
]
