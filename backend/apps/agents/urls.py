from django.urls import path

from .views import (
    AgentHeartbeatView,
    AgentJobPollView,
    AgentJobReportView,
    AgentPackageDownloadView,
    AgentScriptView,
)

urlpatterns = [
    path("jobs/poll/", AgentJobPollView.as_view(), name="agent-job-poll"),
    path("jobs/<int:job_id>/report/", AgentJobReportView.as_view(), name="agent-job-report"),
    path("packages/<int:version_id>/download/", AgentPackageDownloadView.as_view(), name="agent-package-download"),
    path("scripts/<str:name>/", AgentScriptView.as_view(), name="agent-script"),
    path("heartbeat/", AgentHeartbeatView.as_view(), name="agent-heartbeat"),
]
