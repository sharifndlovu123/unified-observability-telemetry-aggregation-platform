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


def _login(c, user, pw, ip=None):
    kw = {"REMOTE_ADDR": ip} if ip else {}
    return c.post("/api/auth/login", {"username": user, "password": pw}, **kw).status_code


def test_only_failed_logins_consume_budget(db, settings):
    settings.LOGIN_FAIL_LIMIT_PER_IP = 3
    User.objects.create_user("bob", password="pw")
    c = APIClient()
    assert [_login(c, "bob", "pw") for _ in range(6)] == [200] * 6  # successes are refunded
    assert [_login(c, "bob", "no") for _ in range(5)] == [401, 401, 401, 429, 429]


def test_ip_lockout_does_not_lock_out_the_real_user(db, settings):
    settings.LOGIN_FAIL_LIMIT_PER_IP = 2
    User.objects.create_user("carol", password="pw")
    c = APIClient()
    for _ in range(3):
        _login(c, "carol", "no", "6.6.6.6")
    assert _login(c, "carol", "no", "6.6.6.6") == 429
    assert _login(c, "carol", "pw", "7.7.7.7") == 200


def test_rotating_ips_cannot_evade_account_limit(db, settings):
    settings.LOGIN_FAIL_LIMIT_PER_USER = 3
    User.objects.create_user("dave", password="pw")
    c = APIClient()
    codes = [_login(c, "dave", "no", f"9.9.9.{i}") for i in range(5)]
    assert codes == [401, 401, 401, 429, 429]


def test_forwarded_header_does_not_evade_ip_throttle(db):
    from portal.views import LoginIPThrottle

    LoginIPThrottle.THROTTLE_RATES = {"login_ip": "3/min"}
    c = APIClient()
    codes = [
        c.post("/api/auth/login", {"username": f"u{i}", "password": "y"}, HTTP_X_FORWARDED_FOR=f"1.2.3.{i}").status_code
        for i in range(5)
    ]
    assert 429 in codes[3:]
