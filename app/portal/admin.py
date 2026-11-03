from django.contrib import admin

from .models import Asset, Report, WorkOrder

admin.site.register([Asset, WorkOrder, Report])
