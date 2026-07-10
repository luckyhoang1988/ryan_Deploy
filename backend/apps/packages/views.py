import csv
import io

from django.db.models import Prefetch, ProtectedError
from django.http import HttpResponse
from django.utils import timezone
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import ValidationError
from rest_framework.pagination import PageNumberPagination
from rest_framework.parsers import FormParser, MultiPartParser
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.audit.models import AuditLog
from apps.core.permissions import IsAdmin, IsOperatorOrAbove
from apps.core.task_registry import remember_task_owner

from . import updates as updates_svc
from .models import APPROVED_VERSIONS_ATTR, Package, PackageDownload, PackageFolder, PackageVersion
from .serializers import (
    PackageDownloadSerializer,
    PackageFolderSerializer,
    PackageSerializer,
    PackageVersionSerializer,
)


class PackagePagination(PageNumberPagination):
    page_size = 30


class PackageViewSet(viewsets.ModelViewSet):
    # prefetch_related("versions") cho field lồng `versions` trong serializer; Prefetch
    # riêng (to_attr) cho `latest_version` để tránh mỗi package tự query lại (N+1 khi list).
    # select_related("folder") cho field `folder` (FK) — tránh N+1 khi liệt kê nhiều package.
    queryset = Package.objects.select_related("folder").prefetch_related(
        "versions",
        Prefetch(
            "versions",
            queryset=PackageVersion.objects.filter(approved=True).order_by("-created_at"),
            to_attr=APPROVED_VERSIONS_ATTR,
        ),
    )
    serializer_class = PackageSerializer
    pagination_class = PackagePagination
    # Tier-0: chỉ admin được tạo/sửa/xóa package (đọc vẫn cho mọi user auth).
    permission_classes = [IsAdmin]

    def _apply_filters(self, qs):
        """Áp dụng bộ lọc chung cho list và export — khớp cây thư mục trên frontend."""
        folder_param = self.request.query_params.get("folder")
        if folder_param:
            qs = qs.filter(folder_id=folder_param)
        return qs

    def get_queryset(self):
        return self._apply_filters(super().get_queryset())

    @action(detail=False, methods=["get"])
    def export(self, request):
        """Xuất danh sách package ra file CSV (Excel-compatible, UTF-8 BOM)."""
        qs = self.get_queryset()
        buf = io.StringIO()
        buf.write("﻿")
        writer = csv.writer(buf)
        writer.writerow(["Tên", "Vendor", "Số version", "License đã dùng", "Tổng license", "Trạng thái"])
        # chunk_size bắt buộc vì queryset có prefetch_related (versions).
        for p in qs.iterator(chunk_size=200):
            writer.writerow([
                p.name,
                p.vendor or "",
                p.versions.count(),
                p.used_licenses,
                p.total_licenses,
                "Sẵn sàng" if p.latest_version else "Chưa có installer",
            ])
        resp = HttpResponse(buf.getvalue(), content_type="text/csv; charset=utf-8")
        resp["Content-Disposition"] = 'attachment; filename="packages.csv"'
        return resp

    def perform_update(self, serializer):
        package = serializer.save()
        AuditLog.record(
            AuditLog.Action.PACKAGE_UPDATE,
            user=self.request.user,
            target=package,
            package=package.name,
        )

    @action(detail=False, methods=["post"])
    def seed_catalog(self, request):
        """
        Nạp Package Library mẫu (mirror PDQ Deploy) — CHỈ metadata (tên/vendor/
        inventory_name) cho các phần mềm doanh nghiệp phổ biến. KHÔNG kèm download_url:
        admin tự upload hoặc "Tải từ URL" installer thật sau khi đã có sẵn khung Package.
        Idempotent — gọi lại không tạo trùng (get_or_create theo tên).
        """
        from . import catalog_seed

        result = catalog_seed.seed_default_catalog()
        AuditLog.record(AuditLog.Action.CATALOG_SEED, user=request.user, **result)
        return Response(result)

    @action(detail=True, methods=["post"])
    def fetch(self, request, pk=None):
        """
        Tải một version từ URL về repository (bất đồng bộ qua Celery).
        Body: {url?: str (mặc định package.download_url), version: str}.
        """
        package = self.get_object()
        url = (request.data.get("url") or package.download_url or "").strip()
        version = (request.data.get("version") or "").strip()
        if not url:
            return Response(
                {"detail": "Chưa có URL tải (nhập url hoặc đặt download_url cho package)."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        if not version:
            return Response(
                {"detail": "Cần nhập nhãn version cho bản tải về."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        from .tasks import fetch_package_version

        task = fetch_package_version.delay(package.id, url, version, request.user.id)
        remember_task_owner(task.id, request.user.id)
        return Response(
            {"detail": "Đang tải trong nền.", "task_id": task.id},
            status=status.HTTP_202_ACCEPTED,
        )

    def perform_destroy(self, instance):
        # Xóa Package sẽ CASCADE toàn bộ version — thu thập đường dẫn file installer
        # TRƯỚC khi xóa DB để dọn file trên đĩa sau đó (FileField không tự xóa file).
        files = [v.installer_file for v in instance.versions.all() if v.installer_file]
        name = instance.name
        saved_pk = instance.pk
        try:
            instance.delete()
        except ProtectedError:
            # Có deployment đang tham chiếu version của package (FK PROTECT).
            raise ValidationError(
                "Không thể xóa package: vẫn còn deployment đang tham chiếu tới version của nó. "
                "Hãy xóa các deployment liên quan trước."
            )
        for f in files:
            f.delete(save=False)
        # delete() đặt instance.pk = None; gán lại để bản ghi audit giữ được target_id.
        instance.pk = saved_pk
        AuditLog.record(
            AuditLog.Action.PACKAGE_DELETE,
            user=self.request.user,
            target=instance,
            package=name,
        )


class PackageFolderViewSet(viewsets.ModelViewSet):
    """Cây thư mục Package Library (mirror PDQ Deploy) — chỉ admin được tạo/sửa/xóa."""

    queryset = PackageFolder.objects.all()
    serializer_class = PackageFolderSerializer
    permission_classes = [IsAdmin]

    def perform_destroy(self, instance):
        # Chặn xóa folder còn package hoặc folder con — tránh package/folder "mồ côi"
        # biến mất khỏi cây mà admin không hay (folder.package FK là SET_NULL, không CASCADE).
        if instance.packages.exists() or instance.children.exists():
            raise ValidationError(
                "Không thể xóa thư mục còn package hoặc thư mục con bên trong. "
                "Hãy chuyển/xóa chúng trước."
            )
        instance.delete()


class PackageVersionViewSet(viewsets.ModelViewSet):
    queryset = PackageVersion.objects.select_related("package").all()
    serializer_class = PackageVersionSerializer
    parser_classes = [MultiPartParser, FormParser]
    # Tier-0: chỉ admin được upload installer (.msi/.exe) lên repository.
    permission_classes = [IsAdmin]

    def perform_create(self, serializer):
        version = serializer.save()
        AuditLog.record(
            AuditLog.Action.PACKAGE_UPLOAD,
            user=self.request.user,
            target=version,
            package=version.package.name,
            version=version.version,
            sha256=version.sha256,
        )

    @action(detail=True, methods=["post"])
    def approve(self, request, pk=None):
        """Duyệt một version (mới được coi là 'latest' cho dò cập nhật & deploy)."""
        version = self.get_object()
        if not version.approved:
            version.approved = True
            version.approved_at = timezone.now()
            version.save(update_fields=["approved", "approved_at", "updated_at"])
            AuditLog.record(
                AuditLog.Action.PACKAGE_APPROVE,
                user=request.user,
                target=version,
                package=version.package.name,
                version=version.version,
            )
        return Response(PackageVersionSerializer(version).data)

    def perform_destroy(self, instance):
        installer_file = instance.installer_file
        pkg_name = instance.package.name
        ver = instance.version
        saved_pk = instance.pk
        try:
            instance.delete()
        except ProtectedError:
            raise ValidationError(
                "Không thể xóa version: đang có deployment tham chiếu tới nó. "
                "Hãy xóa các deployment liên quan trước."
            )
        # Dọn file installer trên đĩa sau khi bản ghi đã xóa thành công.
        if installer_file:
            installer_file.delete(save=False)
        instance.pk = saved_pk  # giữ target_id cho bản ghi audit sau khi delete()
        AuditLog.record(
            AuditLog.Action.PACKAGE_VERSION_DELETE,
            user=self.request.user,
            target=instance,
            package=pkg_name,
            version=ver,
        )


class PackageDownloadViewSet(viewsets.ReadOnlyModelViewSet):
    """Download History — chỉ đọc, chỉ admin (có thể lộ URL nội bộ)."""

    queryset = PackageDownload.objects.select_related("package", "requested_by").all()
    serializer_class = PackageDownloadSerializer
    permission_classes = [IsAdmin]


class UpdatesView(APIView):
    """GET /api/updates/ — danh sách package có máy lỗi thời (bản '133 Updates' của RyanDeploy)."""

    permission_classes = [IsAuthenticated]

    def get(self, request):
        items = updates_svc.compute_updates()
        return Response({"count": len(items), "results": items})


class UpdateDeployView(APIView):
    """
    POST /api/updates/<package_id>/deploy/ — tạo & kích hoạt deployment cập nhật cho các
    máy lỗi thời của package. Body: {credential: id, name?: str}.
    """

    permission_classes = [IsOperatorOrAbove]

    def post(self, request, package_id=None):
        from apps.credentials.models import DeployCredential
        from apps.deployments.models import Deployment, DeploymentAction, DeploymentStatus
        from apps.deployments.orchestrator import launch_deployment

        package = Package.objects.filter(pk=package_id).first()
        if not package:
            return Response({"detail": "Package không tồn tại."}, status=status.HTTP_404_NOT_FOUND)

        latest = package.latest_version
        if latest is None:
            return Response(
                {"detail": "Package chưa có version đã duyệt."}, status=status.HTTP_400_BAD_REQUEST
            )

        credential_id = request.data.get("credential")
        credential = DeployCredential.objects.filter(pk=credential_id).first()
        if credential is None:
            return Response(
                {"detail": "Cần chọn credential hợp lệ."}, status=status.HTTP_400_BAD_REQUEST
            )

        machine_ids = updates_svc.outdated_machine_ids(package)
        if not machine_ids:
            return Response(
                {"detail": "Không có máy nào lỗi thời."}, status=status.HTTP_400_BAD_REQUEST
            )

        name = (request.data.get("name") or "").strip() or (
            f"Cập nhật {package.name} → {latest.version}"
        )
        deployment = Deployment.objects.create(
            name=name,
            action=DeploymentAction.INSTALL,
            package_version=latest,
            credential=credential,
            created_by=request.user,
        )
        deployment.target_machines.set(machine_ids)

        AuditLog.record(
            AuditLog.Action.UPDATE_DEPLOY,
            user=request.user,
            target=deployment,
            package=package.name,
            version=latest.version,
            machines=len(machine_ids),
        )

        try:
            job_count = launch_deployment(deployment)
        except Exception:
            deployment.status = DeploymentStatus.FAILED
            deployment.finished_at = timezone.now()
            deployment.save(update_fields=["status", "finished_at"])
            return Response(
                {"detail": "Không kích hoạt được deployment (lỗi hệ thống)."},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

        if job_count == 0:
            # Máy có thể bị disable/loại khỏi targeting giữa lúc outdated_machine_ids() và
            # resolve_targets() chạy — không có gì để đẩy. Đóng deployment lại (khớp pattern
            # đã dùng ở DeploymentViewSet.trigger/deployments/tasks.py), tránh kẹt DRAFT
            # vĩnh viễn (Deployment.objects.create() ở trên mặc định status=DRAFT).
            deployment.status = DeploymentStatus.COMPLETED
            deployment.finished_at = timezone.now()
            deployment.save(update_fields=["status", "finished_at"])

        return Response(
            {
                "detail": "Đã tạo & kích hoạt deployment cập nhật.",
                "deployment_id": deployment.id,
                "jobs": job_count,
            },
            status=status.HTTP_202_ACCEPTED,
        )
