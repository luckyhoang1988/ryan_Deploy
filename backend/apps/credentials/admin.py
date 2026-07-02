from django import forms
from django.contrib import admin

from .models import DeployCredential


class DeployCredentialForm(forms.ModelForm):
    """Form nhập password dạng plaintext, lưu xuống dạng mã hóa."""

    raw_password = forms.CharField(
        label="Password", widget=forms.PasswordInput(render_value=False), required=False
    )

    class Meta:
        model = DeployCredential
        fields = ("name", "domain", "username", "is_default")

    def save(self, commit=True):
        instance = super().save(commit=False)
        raw = self.cleaned_data.get("raw_password")
        if raw:
            instance.set_password(raw)
        if commit:
            instance.save()
        return instance


@admin.register(DeployCredential)
class DeployCredentialAdmin(admin.ModelAdmin):
    form = DeployCredentialForm
    list_display = ("name", "domain", "username", "is_default", "updated_at")
    search_fields = ("name", "username", "domain")
    # KHÔNG bao giờ hiển thị password_encrypted trên admin
