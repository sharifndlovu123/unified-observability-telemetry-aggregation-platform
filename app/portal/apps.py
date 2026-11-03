import time

from django.apps import AppConfig
from django.db.backends.signals import connection_created


def _timed_execute(execute, sql, params, many, context):
    from . import metrics

    op = (sql.lstrip().split(None, 1) or ["OTHER"])[0].upper()
    start = time.perf_counter()
    try:
        return execute(sql, params, many, context)
    finally:
        metrics.db_query_duration.record(time.perf_counter() - start, {"operation": op})


def _install_db_timer(sender, connection, **_):
    if _timed_execute not in connection.execute_wrappers:
        connection.execute_wrappers.append(_timed_execute)


class PortalConfig(AppConfig):
    name = "portal"

    def ready(self):
        connection_created.connect(_install_db_timer)
        from . import celery_signals  # noqa: F401
