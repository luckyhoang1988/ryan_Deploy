from django.db.models.signals import post_save
from django.dispatch import receiver

from .models import Deployment


@receiver(post_save, sender=Deployment)
def broadcast_deployment_on_save(sender, instance, **kwargs):
    from apps.core.realtime.broadcast import broadcast_deployment

    broadcast_deployment(instance)
