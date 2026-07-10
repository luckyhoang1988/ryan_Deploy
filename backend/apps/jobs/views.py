import csv
import io

from django.http import HttpResponse
from rest_framework import viewsets
from rest_framework.decorators import action
from rest_framework.pagination import PageNumberPagination

from apps.core.permissions import ROLE_ADMIN, ROLE_OPERATOR, has_role

from .models import Job
from .serializers import JobSerializer


class JobPagination(PageNumberPagination):
    page_size = 30


class JobViewSet(viewsets.ReadOnlyModelViewSet):
    serializer_class = JobSerializer
    pagination_class = JobPagination

    def _apply_filters(self, qs):
        """Áp dụng bộ lọc chung cho list và export."""
        params = self.request.query_params
        deployment_id = params.get("deployment")
        if deployment_id:
            qs = qs.filter(deployment_id=deployment_id)
        status_ = params.get("status")
        if status_:
            qs = qs.filter(status=status_)
        return qs

    def get_queryset(self):
        qs = Job.objects.select_related("machine", "deployment").all()
        return self._apply_filters(qs)

    @action(detail=False, methods=["get"])
    def export(self, request):
        """Xuất danh sách job ra file CSV (Excel-compatible, UTF-8 BOM)."""
        qs = self._apply_filters(Job.objects.select_related("machine", "deployment").all())
        # output/error_output có thể chứa dữ liệu nhạy cảm từ máy đích — chỉ
        # operator/admin mới thấy cột Lỗi, giống JobSerializer.to_representation.
        show_error = has_role(request.user, ROLE_OPERATOR, ROLE_ADMIN)
        buf = io.StringIO()
        buf.write("﻿")
        writer = csv.writer(buf)
        header = ["Máy", "Trạng thái", "Step", "Exit code", "Lần thử", "Bắt đầu", "Kết thúc"]
        if show_error:
            header.append("Lỗi")
        writer.writerow(header)
        for j in qs.iterator():
            row = [
                j.machine.hostname,
                j.get_status_display(),
                j.current_step or "",
                j.exit_code if j.exit_code is not None else "",
                j.attempts,
                j.started_at.strftime("%Y-%m-%d %H:%M") if j.started_at else "",
                j.finished_at.strftime("%Y-%m-%d %H:%M") if j.finished_at else "",
            ]
            if show_error:
                row.append(j.error_output or "")
            writer.writerow(row)
        resp = HttpResponse(buf.getvalue(), content_type="text/csv; charset=utf-8")
        resp["Content-Disposition"] = 'attachment; filename="jobs.csv"'
        return resp
