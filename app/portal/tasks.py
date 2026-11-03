import logging
import random
from datetime import timedelta

import requests
from celery import shared_task
from django.conf import settings
from django.core.cache import cache
from django.utils import timezone

logger = logging.getLogger(__name__)


# Task outcome/duration metrics come from portal.celery_signals; spans from the Celery instrumentation.
@shared_task
def generate_report(report_id):
    from .models import Asset, Report, WorkOrder

    report = Report.objects.get(pk=report_id)
    report.status = "running"
    report.save(update_fields=["status"])
    # Degrade gracefully: a failed upstream call should not fail the whole report.
    try:
        rates = requests.get(settings.EXTERNAL_API_URL, timeout=settings.EXTERNAL_API_TIMEOUT).json()
    except requests.RequestException:
        rates = None
        logger.warning("report generated without rates", extra={"report_id": report_id})
    report.result = {
        "assets": Asset.objects.count(),
        "open_work_orders": WorkOrder.objects.filter(status="open").count(),
        "rates": rates,
    }
    report.status = "done"
    report.save(update_fields=["status", "result"])
    cache.set(f"report:{report_id}", report.result, 300)
    logger.info("report generated", extra={"report_id": report_id})
    return report.result


@shared_task
def sweep_stale_workorders():
    """Scheduled housekeeping: marks long-open work orders stale."""
    from .models import WorkOrder

    cutoff = timezone.now() - timedelta(minutes=10)
    n = WorkOrder.objects.filter(status="open", updated_at__lt=cutoff).update(status="stale")
    logger.info("stale sweep", extra={"swept": n})
    return n


@shared_task
def heartbeat():
    """Cheapest possible scheduled task; proves Beat -> broker -> worker is alive."""
    logger.debug("celery heartbeat")


@shared_task
def synthetic_load_tick():
    """Creates baseline activity so dashboards are never empty."""
    from .models import Asset, WorkOrder

    asset = Asset.objects.create(
        name=f"asset-{random.randint(1000, 9999)}",
        type=random.choice(["server", "router", "sensor"]),
    )
    WorkOrder.objects.create(
        asset=asset, title="synthetic check", priority=random.choice(["low", "medium", "high"])
    )
    cache.get(f"asset:{asset.pk}")
    return asset.pk


@shared_task
def log_levels_demo():
    """Emits one record per severity so log pipelines and filters can be demonstrated."""
    logger.debug("demo debug record")
    logger.info("demo info record")
    logger.warning("demo warning record")
    logger.error("demo error record")
    logger.critical("demo critical record")
