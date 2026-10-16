"""The FastAPI app: health, security headers, caching helper, request logs, scheduler."""

import json
import logging
from typing import ClassVar

from fastapi import Request
from fastapi.testclient import TestClient

from rgv_flood import app as app_module
from rgv_flood.app import create_app
from rgv_flood.caching import conditional_json
from rgv_flood.settings import Settings


def test_health_ok(api_client):
    response = api_client.get("/health")

    assert response.status_code == 200
    assert response.json()["status"] == "ok"
    assert response.json()["database"] == "ok"


def test_health_before_build(make_client, tmp_path):
    response = make_client(tmp_path / "not-built.sqlite3").get("/health")

    assert response.status_code == 503
    assert response.json()["database"] == "missing"


def test_security_headers(api_client):
    headers = api_client.get("/health").headers

    assert "frame-ancestors 'none'" in headers["content-security-policy"]
    assert "worker-src 'self' blob:" in headers["content-security-policy"]
    assert headers["x-content-type-options"] == "nosniff"
    assert headers["referrer-policy"] == "strict-origin-when-cross-origin"


def test_conditional_json_304(fixture_db):
    app = create_app(Settings(database=fixture_db, live_signals_scheduler_enabled=False))

    @app.get("/probe")
    def probe(request: Request):
        return conditional_json(request, {"a": 1}, max_age=60)

    with TestClient(app) as client:
        first = client.get("/probe")
        second = client.get("/probe", headers={"If-None-Match": first.headers["etag"]})

    assert first.status_code == 200 and first.json() == {"a": 1}
    assert first.headers["cache-control"] == "public, max-age=60"
    assert second.status_code == 304
    assert second.content == b""


def test_request_log_line(api_client, caplog):
    with caplog.at_level(logging.INFO, logger="rgv_flood.access"):
        api_client.get("/health")

    (record,) = [r for r in caplog.records if r.name == "rgv_flood.access"]
    line = json.loads(record.getMessage())
    assert (line["method"], line["path"], line["status"]) == ("GET", "/health", 200)
    assert line["duration_ms"] >= 0


class _FakeScheduler:
    started: ClassVar[list[int]] = []

    def __init__(self, commands, *, interval_seconds, lock_file):
        self.interval_seconds = interval_seconds

    def start(self):
        _FakeScheduler.started.append(self.interval_seconds)
        return True


def test_scheduler_started_when_enabled(monkeypatch, fixture_db):
    _FakeScheduler.started.clear()
    monkeypatch.setattr(app_module, "LiveSignalScheduler", _FakeScheduler)
    settings = Settings(database=fixture_db, live_signals_refresh_interval_seconds=120)

    with TestClient(create_app(settings)) as client:
        assert isinstance(client.app.state.live_signals_scheduler, _FakeScheduler)

    assert _FakeScheduler.started == [120]


def test_scheduler_not_started_when_disabled(monkeypatch, fixture_db):
    _FakeScheduler.started.clear()
    monkeypatch.setattr(app_module, "LiveSignalScheduler", _FakeScheduler)

    with TestClient(create_app(Settings(database=fixture_db, live_signals_scheduler_enabled=False))):
        pass

    assert _FakeScheduler.started == []
