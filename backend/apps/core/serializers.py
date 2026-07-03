"""Serializers cho quản lý người dùng (RBAC dựa trên Django Group)."""
from django.contrib.auth.models import Group, User
from django.contrib.auth.password_validation import validate_password
from rest_framework import serializers

from .permissions import ROLE_ADMIN, ROLE_OPERATOR, ROLE_VIEWER, user_roles

ROLE_CHOICES = (ROLE_ADMIN, ROLE_OPERATOR, ROLE_VIEWER)


class UserSerializer(serializers.ModelSerializer):
    # role = vai trò chính (map sang đúng 1 Group). superuser luôn hiển thị admin.
    role = serializers.ChoiceField(choices=ROLE_CHOICES, write_only=True, required=False)
    roles = serializers.SerializerMethodField()
    password = serializers.CharField(
        write_only=True, required=False, allow_blank=False,
        style={"input_type": "password"},
        help_text="Bắt buộc khi tạo; để trống khi sửa = giữ mật khẩu cũ.",
    )

    class Meta:
        model = User
        fields = [
            "id", "username", "email", "is_active", "is_superuser",
            "last_login", "date_joined", "role", "roles", "password",
        ]
        read_only_fields = ["is_superuser", "last_login", "date_joined"]

    def get_roles(self, obj):
        return sorted(user_roles(obj))

    def validate_username(self, value):
        value = value.strip()
        if not value:
            raise serializers.ValidationError("Tên đăng nhập không được trống.")
        qs = User.objects.filter(username__iexact=value)
        if self.instance:
            qs = qs.exclude(pk=self.instance.pk)
        if qs.exists():
            raise serializers.ValidationError("Tên đăng nhập đã tồn tại.")
        return value

    def validate_password(self, value):
        validate_password(value)
        return value

    def _apply_role(self, user, role):
        """Gán đúng 1 group theo role (bỏ các group role khác)."""
        if user.is_superuser:
            return  # superuser luôn là admin, không đổi qua group
        group = Group.objects.get_or_create(name=role)[0]
        user.groups.set([group])

    def create(self, validated_data):
        role = validated_data.pop("role", ROLE_VIEWER)
        password = validated_data.pop("password", None)
        if not password:
            raise serializers.ValidationError({"password": "Bắt buộc khi tạo người dùng."})
        user = User(**validated_data)
        user.set_password(password)
        user.save()
        self._apply_role(user, role)
        return user

    def update(self, instance, validated_data):
        role = validated_data.pop("role", None)
        password = validated_data.pop("password", None)
        for key, value in validated_data.items():
            setattr(instance, key, value)
        if password:
            instance.set_password(password)
        instance.save()
        if role:
            self._apply_role(instance, role)
        return instance
