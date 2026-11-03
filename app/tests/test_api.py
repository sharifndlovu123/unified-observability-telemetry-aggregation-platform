import pytest
from django.contrib.auth.models import User
from django.core.cache import cache
from rest_framework.test import APIClient

from portal.models import Asset


@pytest.fixture(autouse=True)
def locmem_cache(settings):
    settings.CACHES = {"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"}}
    cache.clear()


@pytest.fixture
def client(db):
    User.objects.create_user("alice", password="pw")
    c = APIClient()
    assert c.post("/api/auth/login", {"username": "alice", "password": "pw"}).status_code == 200
    return c


def test_requires_auth(db):
    assert APIClient().get("/api/assets/").status_code == 403


def test_login_rejects_bad_credentials(db):
    r = APIClient().post("/api/auth/login", {"username": "x", "password": "y"})
    assert r.status_code == 401


def test_asset_crud_and_cache(client):
    r = client.post("/api/assets/", {"name": "srv1"})
    assert r.status_code == 201
    pk = r.data["id"]
    assert client.get(f"/api/assets/{pk}/").data["name"] == "srv1"
    Asset.objects.filter(pk=pk).update(name="changed-behind-cache")
    assert client.get(f"/api/assets/{pk}/").data["name"] == "srv1"  # served from cache
    client.patch(f"/api/assets/{pk}/", {"name": "srv2"})
    assert client.get(f"/api/assets/{pk}/").data["name"] == "srv2"  # invalidated
    assert client.delete(f"/api/assets/{pk}/").status_code == 204


def test_workorder_marks_asset_maintenance(client):
    pk = client.post("/api/assets/", {"name": "srv"}).data["id"]
    r = client.post("/api/workorders/", {"asset": pk, "title": "fix"})
    assert r.status_code == 201
    assert Asset.objects.get(pk=pk).status == "maintenance"


def test_report_enqueues_task(client, monkeypatch):
    calls = []
    monkeypatch.setattr("portal.views.generate_report.delay", lambda pk: calls.append(pk))
    r = client.post("/api/reports/")
    assert r.status_code == 202 and calls == [r.data["id"]]


def test_healthz(db):
    assert APIClient().get("/healthz").status_code == 200


def test_only_failed_logins_consume_user_budget(db):
    from portal.views import LoginFailureThrottle, LoginIPThrottle

    LoginIPThrottle.THROTTLE_RATES = {"login_ip": "100/min"}
    LoginFailureThrottle.THROTTLE_RATES = {"login_user": "3/min"}
    User.objects.create_user("bob", password="pw")
    c = APIClient()
    ok = [c.post("/api/auth/login", {"username": "bob", "password": "pw"}).status_code for _ in range(5)]
    assert ok == [200] * 5  # successes (even while authenticated) never lock the account
    bad = [c.post("/api/auth/login", {"username": "bob", "password": "no"}).status_code for _ in range(5)]
    assert bad == [401, 401, 401, 429, 429]


def test_failure_lockout_is_per_ip_not_global(db):
    from portal.views import LoginFailureThrottle, LoginIPThrottle

    LoginIPThrottle.THROTTLE_RATES = {"login_ip": "100/min"}
    LoginFailureThrottle.THROTTLE_RATES = {"login_user": "2/min"}
    User.objects.create_user("carol", password="pw")
    attacker, victim = APIClient(REMOTE_ADDR="6.6.6.6"), APIClient(REMOTE_ADDR="7.7.7.7")
    for _ in range(3):
        attacker.post("/api/auth/login", {"username": "carol", "password": "no"})
    assert attacker.post("/api/auth/login", {"username": "carol", "password": "no"}).status_code == 429
    assert victim.post("/api/auth/login", {"username": "carol", "password": "pw"}).status_code == 200


def test_forwarded_header_does_not_evade_ip_throttle(db):
    from portal.views import LoginFailureThrottle, LoginIPThrottle

    LoginIPThrottle.THROTTLE_RATES = {"login_ip": "3/min"}
    LoginFailureThrottle.THROTTLE_RATES = {"login_user": "100/min"}
    c = APIClient()
    codes = [
        c.post("/api/auth/login", {"username": f"u{i}", "password": "y"}, HTTP_X_FORWARDED_FOR=f"1.2.3.{i}").status_code
        for i in range(5)
    ]
    assert 429 in codes[3:]
