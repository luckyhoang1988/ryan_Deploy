from django.apps import AppConfig


class DeploymentsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.deployments"

    def ready(self):
        from . import signals  # noqa: F401
