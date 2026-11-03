import hashlib
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
from rest_framework.decorators import api_view, permission_classes, throttle_classes
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.throttling import SimpleRateThrottle

from . import metrics
from .models import Asset, Report, WorkOrder
from .serializers import AssetSerializer, ReportSerializer, WorkOrderSerializer
from .tasks import generate_report

"""HTTP layer. Note what is NOT here: no tracing/metrics boilerplate. Django, Redis,
psycopg and requests are auto-instrumented; only business-level metrics are recorded
explicitly (cache hit/miss, external calls) via portal.metrics."""
logger = logging.getLogger(__name__)
ASSET_CACHE_TTL = 60


class _LoginThrottle(SimpleRateThrottle):
    """Always yields a cache key (even for authenticated sessions) so it cannot be skipped."""

    def key_suffix(self, request):
        raise NotImplementedError

    def get_cache_key(self, request, view):
        return self.cache_format % {"scope": self.scope, "ident": self.key_suffix(request)}


class LoginIPThrottle(_LoginThrottle):
    scope = "login_ip"

    def key_suffix(self, request):
        return self.get_ident(request)  # NUM_PROXIES=0 -> REMOTE_ADDR only


class LoginUserThrottle(_LoginThrottle):
    """Limits guessing against one account even when the source IP rotates."""

    scope = "login_user"

    def key_suffix(self, request):
        name = str(request.data.get("username", "")).strip().lower()
        return hashlib.sha256(name.encode()).hexdigest()


def healthz(request):
    # Liveness: process is up. Excluded from tracing (OTEL_PYTHON_DJANGO_EXCLUDED_URLS).
    return JsonResponse({"status": "ok"})


def readyz(request):
    # Readiness: dependencies reachable. Returns 503 so orchestrators stop routing to us.
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
@throttle_classes([LoginIPThrottle, LoginUserThrottle])
def login_view(request):
    user = authenticate(
        request,
        username=request.data.get("username"),
        password=request.data.get("password"),
    )
    if user is None:
        # Never log submitted credentials or the attempted username.
        logger.warning("login failed")
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
        # Read-through cache: hit/miss is counted so the ratio is visible in metrics.
        key = f"asset:{kwargs['pk']}"
        data = cache.get(key)
        metrics.cache_operations.add(1, {"operation": "asset_get", "result": "hit" if data is not None else "miss"})
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

    # One atomic unit: order insert + asset status update. Shows up as a single DB transaction in traces.
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
        # 202 + background task: the trace continues into the Celery worker (context travels in message headers).
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
        metrics.external_requests.add(1, {"target": "rates", "status_class": f"{resp.status_code // 100}xx"})
        return Response(resp.json())
    except requests.RequestException as exc:
        metrics.external_requests.add(1, {"target": "rates", "status_class": "error"})
        logger.error("external api failed", extra={"error": exc.__class__.__name__})
        return Response({"detail": "upstream unavailable"}, status=status.HTTP_502_BAD_GATEWAY)
