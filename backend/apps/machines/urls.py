from django.urls import path
from rest_framework.routers import DefaultRouter

from .views import (
    ADConfigTestView,
    ADConfigView,
    EnrollmentSecretViewSet,
    MachineGroupViewSet,
    MachineViewSet,
)

router = DefaultRouter()
router.register("machines", MachineViewSet, basename="machine")
router.register("machine-groups", MachineGroupViewSet, basename="machinegroup")
router.register("enrollment-secrets", EnrollmentSecretViewSet, basename="enrollmentsecret")

urlpatterns = [
    path("ad-config/", ADConfigView.as_view(), name="ad-config"),
    path("ad-config/test/", ADConfigTestView.as_view(), name="ad-config-test"),
    *router.urls,
]
