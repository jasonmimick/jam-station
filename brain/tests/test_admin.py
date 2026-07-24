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
    assert s["uploads"]["ok"] is True
    assert "total" in s["uploads"]
    assert s["channels"]["ok"] is True                 # icecast being down still yields the list
    assert any(c["slug"] == "dead77" for c in s["channels"]["channels"])
    assert "not_visible_from_here" in s


def test_channel_toggle_owner_only_and_works(app_env):
    from app import auth, config, db
    c = TestClient(app)
    auth.create_key_member("Kid", email="kid@example.com")
    c.cookies.set(config.SESSION_COOKIE, auth.new_session("kid@example.com"))
    r = c.post("/api/admin/channel/toggle", json={"slug": "dead77", "enabled": False})
    assert r.status_code == 404                        # not owner — the booth doesn't exist for you

    db.execute("UPDATE members SET role='owner' WHERE email=?", ("kid@example.com",))
    r = c.post("/api/admin/channel/toggle", json={"slug": "dead77", "enabled": False})
    assert r.status_code == 200 and r.json()["enabled"] == 0
    from app import channels
    assert "dead77" not in {ch["slug"] for ch in channels.list_channels()}

    r = c.post("/api/admin/channel/toggle", json={"slug": "no-such-channel", "enabled": False})
    assert r.status_code == 404
