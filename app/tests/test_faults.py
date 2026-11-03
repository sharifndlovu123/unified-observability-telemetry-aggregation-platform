import pytest
from django.contrib.auth.models import User
from django.core.cache import cache
from rest_framework.test import APIClient

import faults
from portal.models import Asset


@pytest.fixture(autouse=True)
def _env(settings):
    settings.CACHES = {"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"}}
    settings.FAULTS_ENABLED = True
    cache.clear()


@pytest.fixture
def staff(db):
    User.objects.create_user("ops", password="pw", is_staff=True)
    c = APIClient()
    assert c.post("/api/auth/login", {"username": "ops", "password": "pw"}).status_code == 200
    return c


def test_fault_api_requires_staff(db):
    User.objects.create_user("plain", password="pw")
    c = APIClient()
    c.post("/api/auth/login", {"username": "plain", "password": "pw"})
    assert c.get("/api/_faults/").status_code == 403
    assert APIClient().get("/api/_faults/").status_code == 403


def test_fault_api_disabled_by_setting(staff, settings):
    settings.FAULTS_ENABLED = False
    assert staff.get("/api/_faults/").status_code == 404


def test_set_list_and_clear(staff):
    assert staff.post("/api/_faults/", {"fault": "slow_endpoint", "delay_ms": 250}, format="json").data == {"slow_endpoint": {"delay_ms": 250.0}}
    assert staff.post("/api/_faults/", {"fault": "slow_endpoint", "enabled": False}, format="json").data == {}
    staff.post("/api/_faults/", {"fault": "http_500", "rate": 0.5}, format="json")
    assert staff.delete("/api/_faults/").data == {}


@pytest.mark.parametrize("body", [
    {"fault": "nope"}, {"fault": "http_500", "rate": 2}, {"fault": "slow_db", "delay_ms": -1},
    {"fault": "slow_db", "delay_ms": "abc"}, {},
])
def test_invalid_fault_requests_are_rejected(staff, body):
    assert staff.post("/api/_faults/", body, format="json").status_code == 400


def test_http_500_fault_raises_controlled_error(staff):
    pk = Asset.objects.create(name="a").pk
    staff.post("/api/_faults/", {"fault": "http_500", "rate": 1}, format="json")
    staff.raise_request_exception = False
    assert staff.get(f"/api/assets/{pk}/").status_code == 500
    faults.clear()
    assert staff.get(f"/api/assets/{pk}/").status_code == 200


def test_faults_are_inert_when_disabled(staff, settings):
    faults.set_fault("http_500", {"rate": 1})
    settings.FAULTS_ENABLED = False
    pk = Asset.objects.create(name="a").pk
    assert staff.get(f"/api/assets/{pk}/").status_code == 200  # a stale fault in Redis must not fire


def test_celery_fault_raises():
    faults.set_fault("celery_fail", {"rate": 1})
    with pytest.raises(faults.SimulatedTaskError):
        faults.maybe_fail_task()
    faults.clear("celery_fail")
    faults.maybe_fail_task()  # no exception
