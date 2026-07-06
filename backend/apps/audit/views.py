import csv
import io
import json

from django.http import HttpResponse
from rest_framework import viewsets
from rest_framework.decorators import action
from rest_framework.pagination import PageNumberPagination

from apps.core.permissions import IsAdminStrict

from .models import AuditLog
from .serializers import AuditLogSerializer


class AuditLogPagination(PageNumberPagination):
    page_size = 30


class AuditLogViewSet(viewsets.ReadOnlyModelViewSet):
    permission_classes = [IsAdminStrict]
    queryset = AuditLog.objects.select_related("user").all()
    serializer_class = AuditLogSerializer
    pagination_class = AuditLogPagination

    def _apply_filters(self, qs):
        action = self.request.query_params.get("action")
        if action:
            qs = qs.filter(action=action)

        user_id = self.request.query_params.get("user")
        if user_id and user_id.isdigit():
            qs = qs.filter(user_id=int(user_id))

        date_from = self.request.query_params.get("date_from")
        if date_from:
            qs = qs.filter(created_at__date__gte=date_from)

        date_to = self.request.query_params.get("date_to")
        if date_to:
            qs = qs.filter(created_at__date__lte=date_to)

        return qs

    def get_queryset(self):
        return self._apply_filters(super().get_queryset())

    @action(detail=False, methods=["get"])
    def export(self, request):
        qs = self.get_queryset()
        buf = io.StringIO()
        buf.write("﻿")
        writer = csv.writer(buf)
        writer.writerow([
            "Thời gian", "Người dùng", "Hành động", "Đối tượng", "Mã đối tượng", "Máy", "Chi tiết"
        ])
        for log in qs.iterator(chunk_size=500):
            writer.writerow([
                log.created_at.strftime("%Y-%m-%d %H:%M:%S"),
                log.user.username if log.user else "",
                log.get_action_display(),
                log.target_type,
                log.target_id,
                log.machine_hostname,
                json.dumps(log.detail, ensure_ascii=False),
            ])
        resp = HttpResponse(buf.getvalue(), content_type="text/csv; charset=utf-8")
        resp["Content-Disposition"] = 'attachment; filename="audit-logs.csv"'
        return resp
