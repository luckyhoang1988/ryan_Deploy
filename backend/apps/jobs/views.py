from rest_framework import viewsets

from .models import Job
from .serializers import JobSerializer


class JobViewSet(viewsets.ReadOnlyModelViewSet):
    serializer_class = JobSerializer

    def get_queryset(self):
        qs = Job.objects.select_related("machine", "deployment").all()
        deployment_id = self.request.query_params.get("deployment")
        if deployment_id:
            qs = qs.filter(deployment_id=deployment_id)
        return qs
