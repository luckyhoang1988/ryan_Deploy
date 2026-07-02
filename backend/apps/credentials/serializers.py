from rest_framework import serializers

from .models import DeployCredential


class DeployCredentialSerializer(serializers.ModelSerializer):
    # write-only: nhận password khi tạo/sửa, KHÔNG bao giờ trả ra response
    password = serializers.CharField(write_only=True, required=False, allow_blank=True)
    has_password = serializers.SerializerMethodField()

    class Meta:
        model = DeployCredential
        fields = ["id", "name", "domain", "username", "is_default", "password", "has_password", "updated_at"]

    def get_has_password(self, obj) -> bool:
        return bool(obj.password_encrypted)

    def create(self, validated_data):
        raw = validated_data.pop("password", "")
        instance = DeployCredential(**validated_data)
        instance.set_password(raw)
        instance.save()
        return instance

    def update(self, instance, validated_data):
        raw = validated_data.pop("password", None)
        for k, v in validated_data.items():
            setattr(instance, k, v)
        if raw:  # chỉ đổi khi có nhập mới
            instance.set_password(raw)
        instance.save()
        return instance
