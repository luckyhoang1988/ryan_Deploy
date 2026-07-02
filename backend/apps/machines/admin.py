from django.contrib import admin

from .models import ADConfig, Machine, MachineGroup


@admin.register(ADConfig)
class ADConfigAdmin(admin.ModelAdmin):
    list_display = ("server", "base_dn", "bind_user", "use_ssl", "enabled")
    exclude = ("bind_password_enc",)


@admin.register(Machine)
class MachineAdmin(admin.ModelAdmin):
    list_display = ("hostname", "fqdn", "ip_address", "os_name", "is_online", "last_seen", "enabled")
    list_filter = ("is_online", "enabled", "os_name")
    search_fields = ("hostname", "fqdn", "ip_address")


@admin.register(MachineGroup)
class MachineGroupAdmin(admin.ModelAdmin):
    list_display = ("name", "description")
    search_fields = ("name",)
    filter_horizontal = ("machines",)
