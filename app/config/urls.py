from django.contrib import admin
from django.urls import include, path

from portal import views

urlpatterns = [
    path("admin/", admin.site.urls),
    path("healthz", views.healthz),
    path("readyz", views.readyz),
    path("stub/rates/", views.stub_rates),
    path("api/", include("portal.urls")),
]
