"""The engineer's booth: owner-only, and collectors never 500."""
from fastapi.testclient import TestClient

from app import admin
from app.main import app


def test_admin_hidden_from_anonymous(app_env):
    c = TestClient(app)
    assert c.get("/admin").status_code == 404          # not 403 — the booth doesn't exist for you
    assert c.get("/api/admin/status").status_code == 404


def test_status_survives_dead_services(app_env):
    # icecast/liquidsoap are unreachable in tests — collectors must report, not raise
    s = admin.status()
    assert s["icecast"]["ok"] is False
    assert s["liquidsoap"]["ok"] is False
    assert s["database"]["ok"] is True                 # the test db IS reachable
    assert isinstance(s["queues"], list)
    assert "not_visible_from_here" in s
