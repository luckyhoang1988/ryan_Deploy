from django.db.models.signals import post_save
from django.dispatch import receiver

from .models import Job


@receiver(post_save, sender=Job)
def broadcast_job_on_save(sender, instance, **kwargs):
    from apps.core.realtime.broadcast import broadcast_job

    broadcast_job(instance)
