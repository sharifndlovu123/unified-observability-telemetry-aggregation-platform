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
