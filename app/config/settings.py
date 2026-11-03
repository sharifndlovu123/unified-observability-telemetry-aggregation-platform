import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent


def env(name, default=None):
    return os.environ.get(name, default)


def env_bool(name, default=False):
    return str(env(name, str(default))).lower() in ("1", "true", "yes")


SECRET_KEY = env("DJANGO_SECRET_KEY", "insecure-dev-key")
DEBUG = env_bool("DEBUG", False)
ALLOWED_HOSTS = env("DJANGO_ALLOWED_HOSTS", "localhost,127.0.0.1,django").split(",")

ENVIRONMENT = env("ENVIRONMENT", "dev")
APP_VERSION = env("APP_VERSION", "0.1.0")
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
CELERY_BEAT_SCHEDULE = {
    "heartbeat": {"task": "portal.tasks.heartbeat", "schedule": 15.0},
    "synthetic-load": {"task": "portal.tasks.synthetic_load_tick", "schedule": 30.0},
    "sweep-stale-workorders": {"task": "portal.tasks.sweep_stale_workorders", "schedule": 60.0},
}

# Simulated external API (served by this app by default, see portal.views.stub_rates)
EXTERNAL_API_URL = env("EXTERNAL_API_URL", "http://django:8000/stub/rates/")
EXTERNAL_API_TIMEOUT = float(env("EXTERNAL_API_TIMEOUT", "3"))

REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": ["rest_framework.authentication.SessionAuthentication"],
    "DEFAULT_PERMISSION_CLASSES": ["rest_framework.permissions.IsAuthenticated"],
    "DEFAULT_PAGINATION_CLASS": "rest_framework.pagination.PageNumberPagination",
    "PAGE_SIZE": 50,
}

AUTH_PASSWORD_VALIDATORS = []
LANGUAGE_CODE = "en-us"
TIME_ZONE = "UTC"
USE_TZ = True
STATIC_URL = "static/"
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"
