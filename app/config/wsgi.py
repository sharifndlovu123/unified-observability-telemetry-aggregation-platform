import os

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")

from config.telemetry import setup_telemetry  # noqa: E402

setup_telemetry("django")  # before the app loads so Django instrumentation hooks in

from django.core.wsgi import get_wsgi_application  # noqa: E402

application = get_wsgi_application()
