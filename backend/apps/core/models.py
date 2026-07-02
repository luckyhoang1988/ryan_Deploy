from django.db import models


class TimeStampedModel(models.Model):
    """Abstract base: thêm created_at / updated_at cho mọi model."""

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        abstract = True
