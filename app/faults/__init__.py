"""Runtime fault injection for the demo scenarios (spec section 8).

Faults are toggled through POST /api/_faults/ and stored in Redis (the shared Django cache),
so the web and worker processes all see them with no redeploy. Three safety rails:
  * everything is a no-op unless settings.FAULTS_ENABLED is true
  * every fault auto-expires (TTL) so a forgotten one cannot linger
  * the API requires a staff user

Each fault is applied at one named place in the app so a scenario's effect is attributable:
  slow_endpoint  GET /api/assets/            sleeps inside a span named simulated.slow_operation
  slow_db        GET /api/workorders/        runs SELECT pg_sleep(...)
  http_500       GET /api/assets/<id>/       raises a controlled exception with probability `rate`
  celery_fail    generate_report task        raises with probability `rate`
"""
import logging
import random
import time

from django.conf import settings
from django.core.cache import cache
from django.db import connection
from opentelemetry import trace

logger = logging.getLogger(__name__)
tracer = trace.get_tracer("portal.faults")

TTL_SECONDS = 900
# fault -> {parameter: (min, max)}
FAULTS = {
    "slow_endpoint": {"delay_ms": (0, 10_000)},
    "slow_db": {"delay_ms": (0, 10_000)},
    "http_500": {"rate": (0.0, 1.0)},
    "celery_fail": {"rate": (0.0, 1.0)},
}


class SimulatedError(Exception):
    """Controlled application exception (Scenario 2)."""


class SimulatedTaskError(Exception):
    """Controlled Celery task failure (Scenario 3)."""


def _key(name):
    return f"fault:{name}"


def validate(name, params):
    if name not in FAULTS:
        raise ValueError(f"unknown fault '{name}', expected one of {sorted(FAULTS)}")
    clean = {}
    for param, (lo, hi) in FAULTS[name].items():
        value = float(params.get(param, lo))
        if not lo <= value <= hi:
            raise ValueError(f"{param} must be between {lo} and {hi}")
        clean[param] = value
    return clean


def set_fault(name, params):
    clean = validate(name, params)
    cache.set(_key(name), clean, TTL_SECONDS)
    return clean


def clear(name=None):
    for n in [name] if name else FAULTS:
        cache.delete(_key(n))


def active():
    return {n: v for n in FAULTS if (v := cache.get(_key(n))) is not None}


def _get(name):
    return cache.get(_key(name)) if settings.FAULTS_ENABLED else None


def slow_endpoint():
    f = _get("slow_endpoint")
    if f:
        # A dedicated span makes the slow step obvious in the trace waterfall.
        with tracer.start_as_current_span("simulated.slow_operation"):
            logger.warning("fault injected: slow endpoint", extra={"fault": "slow_endpoint", "delay_ms": f["delay_ms"]})
            time.sleep(f["delay_ms"] / 1000)


def slow_db():
    f = _get("slow_db")
    if f:
        logger.warning("fault injected: slow database query", extra={"fault": "slow_db", "delay_ms": f["delay_ms"]})
        with connection.cursor() as cur:
            cur.execute("SELECT pg_sleep(%s)", [f["delay_ms"] / 1000])


def maybe_fail_http():
    f = _get("http_500")
    if f and random.random() < f["rate"]:
        raise SimulatedError("injected failure (http_500 fault)")


def maybe_fail_task():
    f = _get("celery_fail")
    if f and random.random() < f["rate"]:
        raise SimulatedTaskError("injected failure (celery_fail fault)")
