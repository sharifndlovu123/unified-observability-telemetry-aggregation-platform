"""Settings are 100% environment-driven (12-factor); nothing provider-specific lives here.
Telemetry wiring is in config/telemetry.py."""
import os
from pathlib import Path

from django.core.exceptions import ImproperlyConfigured

BASE_DIR = Path(__file__).resolve().parent.parent


def env(name, default=None):
    return os.environ.get(name, default)


def env_bool(name, default=False):
    return str(env(name, str(default))).lower() in ("1", "true", "yes")


# Fail closed: a missing secret must stop the app, not silently fall back to a known key.
DEBUG = env_bool("DEBUG", False)
SECRET_KEY = env("DJANGO_SECRET_KEY")
if not SECRET_KEY:
    if not DEBUG:
        raise ImproperlyConfigured("DJANGO_SECRET_KEY must be set (or DEBUG=true for local dev)")
    SECRET_KEY = "insecure-dev-key"
ALLOWED_HOSTS = env("DJANGO_ALLOWED_HOSTS", "localhost,127.0.0.1,django").split(",")

ENVIRONMENT = env("ENVIRONMENT", "dev")
APP_VERSION = env("APP_VERSION", "0.1.0")
# Gates the fault-injection endpoints used by the demo scenarios (added later).
FAULTS_ENABLED = env_bool("FAULTS_ENABLED", False)

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "rest_framework",
    "portal",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
]

ROOT_URLCONF = "config.urls"
WSGI_APPLICATION = "config.wsgi.application"
TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ]
        },
    }
]

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.postgresql",
        "NAME": env("POSTGRES_DB", "portal"),
        "USER": env("POSTGRES_USER", "portal"),
        "PASSWORD": env("POSTGRES_PASSWORD", "portal"),
        "HOST": env("POSTGRES_HOST", "postgres"),
        "PORT": env("POSTGRES_PORT", "5432"),
    }
}

# Redis serves two roles on separate DBs: /0 = Django cache, /1 = Celery broker.
REDIS_URL = env("REDIS_URL", "redis://redis:6379/0")
CACHES = {
    "default": {
        "BACKEND": "django.core.cache.backends.redis.RedisCache",
        "LOCATION": REDIS_URL,
    }
}

CELERY_BROKER_URL = env("CELERY_BROKER_URL", REDIS_URL.rsplit("/", 1)[0] + "/1")
CELERY_RESULT_BACKEND = CELERY_BROKER_URL
CELERY_TASK_TRACK_STARTED = True
# Beat keeps telemetry flowing with no human traffic (so dashboards are never empty).
CELERY_BEAT_SCHEDULE = {
    "heartbeat": {"task": "portal.tasks.heartbeat", "schedule": 15.0},
    "synthetic-load": {"task": "portal.tasks.synthetic_load_tick", "schedule": 30.0},
    "log-levels-demo": {"task": "portal.tasks.log_levels_demo", "schedule": 120.0},
    "sweep-stale-workorders": {"task": "portal.tasks.sweep_stale_workorders", "schedule": 60.0},
}

# The "external API" is a stub route served by this same app: it gives us a client
# span + latency to observe without depending on the internet.
# Simulated external API (served by this app by default, see portal.views.stub_rates)
EXTERNAL_API_URL = env("EXTERNAL_API_URL", "http://django:8000/stub/rates/")
EXTERNAL_API_TIMEOUT = float(env("EXTERNAL_API_TIMEOUT", "3"))

REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": ["rest_framework.authentication.SessionAuthentication"],
    "DEFAULT_PERMISSION_CLASSES": ["rest_framework.permissions.IsAuthenticated"],
    "DEFAULT_PAGINATION_CLASS": "rest_framework.pagination.PageNumberPagination",
    "PAGE_SIZE": 50,
    # Django is reached directly (no trusted proxy), so never trust X-Forwarded-For.
    "NUM_PROXIES": 0,
    "DEFAULT_THROTTLE_RATES": {
        "login_ip": env("LOGIN_IP_THROTTLE_RATE", "20/min"),
        "login_user": env("LOGIN_USER_THROTTLE_RATE", "5/min"),
    },
}

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]
LANGUAGE_CODE = "en-us"
TIME_ZONE = "UTC"
USE_TZ = True
STATIC_URL = "static/"
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# Logging is configured by config.telemetry (JSON + OTLP); stop Celery from replacing it.
CELERY_WORKER_HIJACK_ROOT_LOGGER = False
CELERY_WORKER_REDIRECT_STDOUTS = False
LOGGING_CONFIG = None
