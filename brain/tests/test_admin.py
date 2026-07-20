"""The engineer's booth: owner-only, and collectors never 500."""
from fastapi.testclient import TestClient

from app import admin
from app.main import app


def test_admin_hidden_from_anonymous(app_env):
    c = TestClient(app)
    assert c.get("/admin").status_code == 404          # not 403 — the booth doesn't exist for you
    assert c.get("/api/admin/status").status_code == 404


def test_engineer_chat_hidden_from_anonymous(app_env):
    c = TestClient(app)
    r = c.post("/api/admin/chat", json={"messages": [{"role": "user", "content": "status?"}]})
    assert r.status_code == 404


def test_engineer_tools_run_without_anthropic(app_env):
    # the tool layer must work standalone — the loop is dj.py's, already proven
    from app import engineer
    assert engineer._run_tool("station_status", {})["database"]["ok"] is True
    assert isinstance(engineer._run_tool("list_channels", {}), list)
    assert "unserved" in engineer._run_tool("queue_status", {"channel": "dead77"})
    assert engineer._run_tool("flush_queue", {"channel": "dead77"})["cleared"] >= 0
    assert engineer._run_tool("topup_queue", {"channel": "dead77"})["added"] >= 0
    assert "shelf" in engineer._run_tool("resync_shelf_stations", {})
    assert engineer._run_tool("kick_covers", {})["kicked"] is True
    assert isinstance(engineer._run_tool("play_history", {"limit": 5}), list)
    assert "error" in engineer._run_tool("made_up_tool", {})


def test_status_survives_dead_services(app_env):
    # icecast/liquidsoap are unreachable in tests — collectors must report, not raise
    s = admin.status()
    assert s["icecast"]["ok"] is False
    assert s["liquidsoap"]["ok"] is False
    assert s["database"]["ok"] is True                 # the test db IS reachable
    assert isinstance(s["queues"], list)
    assert "not_visible_from_here" in s
