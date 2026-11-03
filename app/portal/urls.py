from django.urls import include, path
from rest_framework.routers import DefaultRouter

from . import views

router = DefaultRouter()
router.register("assets", views.AssetViewSet)
router.register("workorders", views.WorkOrderViewSet)
router.register("reports", views.ReportViewSet, basename="report")

urlpatterns = [
    path("auth/login", views.login_view),
    path("auth/logout", views.logout_view),
    path("external/rates/", views.external_rates),
    path("_faults/", views.fault_view),
    path("", include(router.urls)),
]
