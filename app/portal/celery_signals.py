"""Task outcome/duration metrics from Celery signals (runs in worker processes)."""
import time

from celery.signals import task_failure, task_postrun, task_prerun, task_retry, task_success

from . import metrics

_starts = {}


@task_prerun.connect(weak=False)
def _start(task_id=None, **_):
    _starts[task_id] = time.perf_counter()


@task_postrun.connect(weak=False)
def _end(task_id=None, task=None, **_):
    started = _starts.pop(task_id, None)
    if started is not None:
        metrics.celery_task_duration.record(time.perf_counter() - started, {"task": task.name})


@task_success.connect(weak=False)
def _ok(sender=None, **_):
    metrics.celery_tasks.add(1, {"task": sender.name, "outcome": "success"})


@task_failure.connect(weak=False)
def _fail(sender=None, **_):
    metrics.celery_tasks.add(1, {"task": sender.name, "outcome": "failure"})


@task_retry.connect(weak=False)
def _retry(sender=None, **_):
    metrics.celery_tasks.add(1, {"task": sender.name, "outcome": "retry"})
