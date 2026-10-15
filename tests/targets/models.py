import uuid

from django.db import models


class Product(models.Model):
    site = models.ForeignKey("wagtailcore.Site", on_delete=models.CASCADE)
    title = models.CharField(max_length=80)
    visible = models.BooleanField(default=True)

    def __str__(self):
        return self.title


class StringTarget(Product):
    key = models.CharField(max_length=255, primary_key=True)


class UUIDTarget(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4)
    site = models.ForeignKey("wagtailcore.Site", on_delete=models.CASCADE)
    title = models.CharField(max_length=80)
    visible = models.BooleanField(default=True)

    def __str__(self):
        return self.title
