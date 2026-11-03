"""OpenTelemetry bootstrap: traces, metrics and logs, all exported over OTLP.

The app only knows about the OTLP endpoint (OTEL_EXPORTER_OTLP_ENDPOINT); which
backends receive the data is decided entirely by the Collector.
Call setup_telemetry() once per process (after fork for Celery prefork workers).
"""
import logging
import os
import re
import socket
import sys

from opentelemetry import _logs, metrics, trace
from opentelemetry.exporter.otlp.proto.grpc._log_exporter import OTLPLogExporter
from opentelemetry.exporter.otlp.proto.grpc.metric_exporter import OTLPMetricExporter
from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
from opentelemetry.sdk._logs import LoggerProvider, LoggingHandler
from opentelemetry.sdk._logs.export import BatchLogRecordProcessor
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.export import PeriodicExportingMetricReader
from opentelemetry.sdk.metrics.view import ExplicitBucketHistogramAggregation, View
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from pythonjsonlogger.json import JsonFormatter

SENSITIVE = re.compile(r"password|passwd|token|secret|authorization|cookie|api[_-]?key", re.I)
_STD_ATTRS = set(logging.LogRecord("", 0, "", 0, "", (), None).__dict__) | {"message", "asctime", "taskName"}
_configured = False


class RedactionFilter(logging.Filter):
    """Masks sensitive-looking extras (password, token, ...) before ANY handler sees them."""

    def filter(self, record):
        for key in list(record.__dict__):
            if key not in _STD_ATTRS and SENSITIVE.search(key):
                record.__dict__[key] = "[REDACTED]"
        return True


class ContextJsonFormatter(JsonFormatter):
    """JSON lines with service/environment and trace/span IDs for log<->trace correlation.

    Done at format time (not in a Filter) so the shared LogRecord is never mutated:
    the OTLP handler sees the same record and attaches trace context natively.
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.service = os.environ.get("OTEL_SERVICE_NAME", "portal")
        self.environment = os.environ.get("ENVIRONMENT", "dev")

    def add_fields(self, log_record, record, message_dict):
        super().add_fields(log_record, record, message_dict)
        ctx = trace.get_current_span().get_span_context()
        log_record["service_name"] = self.service
        log_record["environment"] = self.environment
        log_record["trace_id"] = format(ctx.trace_id, "032x") if ctx.is_valid else None
        log_record["span_id"] = format(ctx.span_id, "016x") if ctx.is_valid else None


class NotOtelInternal(logging.Filter):
    """Keeps the SDK's own log records out of the OTLP handler (prevents feedback loops)."""

    def filter(self, record):
        return not record.name.startswith("opentelemetry")


def _setup_logging(otlp_handler=None):
    """Root logger: JSON to stdout (for `docker logs`) + OTLP to the Collector."""
    root = logging.getLogger()
    for h in list(root.handlers):
        root.removeHandler(h)

    stdout = logging.StreamHandler(sys.stdout)
    stdout.setFormatter(
        ContextJsonFormatter(
            "%(asctime)s %(levelname)s %(name)s %(message)s",
            rename_fields={"asctime": "timestamp", "levelname": "level", "name": "logger"},
        )
    )
    stdout.addFilter(RedactionFilter())
    root.addHandler(stdout)

    if otlp_handler is not None:
        otlp_handler.addFilter(RedactionFilter())
        otlp_handler.addFilter(NotOtelInternal())
        root.addHandler(otlp_handler)

    root.setLevel(os.environ.get("LOG_LEVEL", "INFO").upper())
    # Django's `request` extra is not an OTel-legal attribute type; the warning is just noise.
    logging.getLogger("opentelemetry.attributes").setLevel(logging.ERROR)


def setup_telemetry(role):
    """role: 'django' | 'celery-worker' | 'celery-beat' (informational)."""
    global _configured
    if _configured:
        return
    _configured = True

    if os.environ.get("OTEL_SDK_DISABLED", "").lower() == "true":
        _setup_logging()
        return

    # service.name etc. come from OTEL_* env vars. service.instance.id MUST be unique per OS
    # process: gunicorn and Celery run several, and processes that export cumulative metrics
    # under an identical resource overwrite each other in the Collector/Prometheus (counters and
    # histogram buckets then jump around and under-count). One series per process; PromQL sums them.
    resource = Resource.create({"service.instance.id": f"{socket.gethostname()}-{os.getpid()}"})

    tp = TracerProvider(resource=resource)
    tp.add_span_processor(BatchSpanProcessor(OTLPSpanExporter()))
    trace.set_tracer_provider(tp)

    # The SDK's default histogram buckets (0, 5, 10, 25, ... 10000) are sized for MILLISECONDS.
    # Our *.duration histograms are in SECONDS, so with the defaults every observation lands in the
    # first bucket and percentiles are meaningless. This view gives them second-scale buckets.
    seconds_buckets = View(
        instrument_name="portal.*.duration",
        aggregation=ExplicitBucketHistogramAggregation([0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1, 2.5, 5, 10, 30, 60]),
    )
    metrics.set_meter_provider(
        MeterProvider(resource=resource, views=[seconds_buckets],
                      metric_readers=[PeriodicExportingMetricReader(OTLPMetricExporter())])
    )

    lp = LoggerProvider(resource=resource)
    lp.add_log_record_processor(BatchLogRecordProcessor(OTLPLogExporter()))
    _logs.set_logger_provider(lp)
    _setup_logging(LoggingHandler(level=logging.NOTSET, logger_provider=lp))

    from opentelemetry.instrumentation.celery import CeleryInstrumentor
    from opentelemetry.instrumentation.django import DjangoInstrumentor
    from opentelemetry.instrumentation.psycopg import PsycopgInstrumentor
    from opentelemetry.instrumentation.redis import RedisInstrumentor
    from opentelemetry.instrumentation.requests import RequestsInstrumentor

    DjangoInstrumentor().instrument()
    PsycopgInstrumentor().instrument()
    RedisInstrumentor().instrument()
    RequestsInstrumentor().instrument()
    CeleryInstrumentor().instrument()
    logging.getLogger(__name__).info("telemetry initialised", extra={"role": role})
