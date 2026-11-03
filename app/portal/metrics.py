"""Custom application metrics. Names/attributes are the contract used by dashboards and alerts.
Keep attribute cardinality low: never use user IDs, object IDs or raw URLs."""
import time

import redis
from django.conf import settings
from opentelemetry import metrics
from opentelemetry.metrics import Observation

meter = metrics.get_meter("portal")
_started = time.time()

cache_operations = meter.create_counter("portal.cache.operations", description="Cache lookups by result")
celery_tasks = meter.create_counter("portal.celery.tasks", description="Celery task outcomes")
celery_task_duration = meter.create_histogram("portal.celery.task.duration", unit="s")
db_query_duration = meter.create_histogram("portal.db.query.duration", unit="s")
external_requests = meter.create_counter("portal.external.requests")


def _uptime(_options):
    yield Observation(time.time() - _started)


def _queue_depth(_options):
    try:
        client = redis.Redis.from_url(settings.CELERY_BROKER_URL, socket_timeout=1)
        yield Observation(client.llen("celery"), {"queue": "celery"})
    except redis.RedisError:
        return


meter.create_observable_gauge("portal.app.uptime", callbacks=[_uptime], unit="s")
meter.create_observable_gauge("portal.celery.queue.depth", callbacks=[_queue_depth])
