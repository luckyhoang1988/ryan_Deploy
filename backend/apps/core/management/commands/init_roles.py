from django.contrib.auth.models import Group
from django.core.management.base import BaseCommand

from apps.core.permissions import ROLE_ADMIN, ROLE_OPERATOR, ROLE_VIEWER


class Command(BaseCommand):
    help = "Khởi tạo 3 nhóm RBAC: admin / operator / viewer."

    def handle(self, *args, **options):
        for role in (ROLE_ADMIN, ROLE_OPERATOR, ROLE_VIEWER):
            group, created = Group.objects.get_or_create(name=role)
            status = "tạo mới" if created else "đã có"
            self.stdout.write(f"  - {role}: {status}")
        self.stdout.write(self.style.SUCCESS("Xong khởi tạo RBAC groups."))
