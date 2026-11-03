from django.conf import settings
from django.db import models


"""Small ops domain: just enough relational work to produce interesting DB spans."""


class Asset(models.Model):
    name = models.CharField(max_length=120)
    type = models.CharField(max_length=60, default="server")
    status = models.CharField(max_length=20, default="active")
    owner = models.CharField(max_length=120, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)


class WorkOrder(models.Model):
    asset = models.ForeignKey(Asset, on_delete=models.CASCADE, related_name="work_orders")
    title = models.CharField(max_length=200)
    priority = models.CharField(max_length=10, default="medium")
    status = models.CharField(max_length=20, default="open")
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)


class Report(models.Model):
    status = models.CharField(max_length=20, default="pending")
    result = models.JSONField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
