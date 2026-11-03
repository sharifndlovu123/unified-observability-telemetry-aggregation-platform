import logging
import random
import time

import requests
from django.conf import settings
from django.contrib.auth import authenticate, login, logout
from django.core.cache import cache
from django.db import connection, transaction
from django.http import JsonResponse
from rest_framework import status, viewsets
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import AllowAny
from rest_framework.response import Response

from .models import Asset, Report, WorkOrder
from .serializers import AssetSerializer, ReportSerializer, WorkOrderSerializer
from .tasks import generate_report

logger = logging.getLogger(__name__)
ASSET_CACHE_TTL = 60


def healthz(request):
    return JsonResponse({"status": "ok"})


def readyz(request):
    checks = {}
    try:
        with connection.cursor() as cur:
            cur.execute("SELECT 1")
        checks["database"] = "ok"
    except Exception as exc:  # noqa: BLE001
        checks["database"] = f"error: {exc.__class__.__name__}"
    try:
        cache.set("readyz", "1", 5)
        checks["redis"] = "ok"
    except Exception as exc:  # noqa: BLE001
        checks["redis"] = f"error: {exc.__class__.__name__}"
    ok = all(v == "ok" for v in checks.values())
    return JsonResponse(checks, status=200 if ok else 503)


def stub_rates(request):
    """Simulated third-party API with configurable latency."""
    time.sleep(random.uniform(0.01, 0.08))
    return JsonResponse({"base": "USD", "rates": {"EUR": 0.92, "ZAR": 18.4}})


@api_view(["POST"])
@permission_classes([AllowAny])
def login_view(request):
    user = authenticate(
        request,
        username=request.data.get("username"),
        password=request.data.get("password"),
    )
    if user is None:
        # Never log the submitted credentials.
        logger.warning("login failed", extra={"username": request.data.get("username")})
        return Response({"detail": "invalid credentials"}, status=status.HTTP_401_UNAUTHORIZED)
    login(request, user)
    logger.info("login ok", extra={"user_id": user.pk})
    return Response({"detail": "ok"})


@api_view(["POST"])
def logout_view(request):
    logout(request)
    return Response({"detail": "ok"})


class AssetViewSet(viewsets.ModelViewSet):
    queryset = Asset.objects.order_by("id")
    serializer_class = AssetSerializer

    def retrieve(self, request, *args, **kwargs):
        key = f"asset:{kwargs['pk']}"
        data = cache.get(key)
        if data is None:
            data = super().retrieve(request, *args, **kwargs).data
            cache.set(key, data, ASSET_CACHE_TTL)
            logger.debug("asset cache miss", extra={"asset_id": kwargs["pk"]})
        return Response(data)

    def perform_update(self, serializer):
        serializer.save()
        cache.delete(f"asset:{serializer.instance.pk}")

    def perform_destroy(self, instance):
        cache.delete(f"asset:{instance.pk}")
        instance.delete()


class WorkOrderViewSet(viewsets.ModelViewSet):
    queryset = WorkOrder.objects.select_related("asset").order_by("-id")
    serializer_class = WorkOrderSerializer

    @transaction.atomic
    def perform_create(self, serializer):
        order = serializer.save(created_by=self.request.user)
        Asset.objects.filter(pk=order.asset_id).update(status="maintenance")
        cache.delete(f"asset:{order.asset_id}")
        logger.info("work order created", extra={"work_order_id": order.pk})


class ReportViewSet(viewsets.GenericViewSet):
    queryset = Report.objects.all()
    serializer_class = ReportSerializer

    def create(self, request):
        report = Report.objects.create()
        generate_report.delay(report.pk)
        return Response(ReportSerializer(report).data, status=status.HTTP_202_ACCEPTED)

    def retrieve(self, request, pk=None):
        return Response(ReportSerializer(self.get_object()).data)


@api_view(["GET"])
def external_rates(request):
    try:
        resp = requests.get(settings.EXTERNAL_API_URL, timeout=settings.EXTERNAL_API_TIMEOUT)
        resp.raise_for_status()
        return Response(resp.json())
    except requests.RequestException as exc:
        logger.error("external api failed", extra={"error": exc.__class__.__name__})
        return Response({"detail": "upstream unavailable"}, status=status.HTTP_502_BAD_GATEWAY)
