import os

from celery import Celery
from celery.signals import beat_init, worker_process_init

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
app = Celery("portal")
app.config_from_object("django.conf:settings", namespace="CELERY")
app.autodiscover_tasks()


# The SDK spawns background threads, so it must be initialised in each forked
# pool process, not in the prefork parent.
@worker_process_init.connect(weak=False)
def _init_worker_telemetry(**_):
    from config.telemetry import setup_telemetry

    setup_telemetry("celery-worker")


@beat_init.connect(weak=False)
def _init_beat_telemetry(**_):
    from config.telemetry import setup_telemetry

    setup_telemetry("celery-beat")
