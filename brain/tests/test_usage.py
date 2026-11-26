"""Usage reports: finished listening sessions land in `listens`; the report rolls them up."""
import io
import sys
import time

from fastapi.testclient import TestClient

from app import db, presence, usage
from app.main import app


def _later(monkeypatch, secs):
    real = time.time
    monkeypatch.setattr(time, "time", lambda: real() + secs)


def _listens():
    return db.query("SELECT channel, mode, email, client, seconds FROM listens ORDER BY id")


def test_radio_session_logged_on_disconnect(app_env, monkeypatch):
    sid = presence.stream_connect("Dad", "dad@example.com", "dead77", "stereotop")
    _later(monkeypatch, 600)
    presence.stream_disconnect(sid)
    rows = _listens()
    assert len(rows) == 1
    r = rows[0]
    assert (r["channel"], r["mode"], r["email"], r["client"]) == ("dead77", "radio", "dad@example.com", "stereotop")
    assert 599 <= r["seconds"] <= 601


def test_short_session_not_logged(app_env):
    sid = presence.stream_connect("", "", "dead77")
    presence.stream_disconnect(sid)            # dial-surfing / a health probe
    assert _listens() == []


def test_ondemand_session_logged_on_channel_change_and_expiry(app_env, monkeypatch):
    real = time.time
    t = [real()]
    monkeypatch.setattr(time, "time", lambda: t[0])
    for _ in range(5):                         # a beat every 30 s, as the UI sends them
        presence.heartbeat("Bob", "bob@example.com", "bob@example.com", "cds/Album A", "web")
        t[0] += 30
    presence.heartbeat("Bob", "bob@example.com", "bob@example.com", "cds/Album B", "web")
    rows = _listens()
    assert [(r["channel"], r["mode"], r["seconds"]) for r in rows] == [("cds/Album A", "ondemand", 120)]
    for _ in range(2):
        t[0] += 30
        presence.heartbeat("Bob", "bob@example.com", "bob@example.com", "cds/Album B", "web")
    t[0] += presence.HEARTBEAT_TTL + 5         # beats stop
    presence.sweep()
    rows = _listens()
    assert rows[-1]["channel"] == "cds/Album B" and rows[-1]["seconds"] == 60


def test_report_flags_idle_continuous_channels(app_env):
    usage.record("dead77", "radio", "", "stereotop", time.time() - 7200, 5400)
    rep = usage.report(30)
    assert rep["total_hours"] == 1.5
    by = {c["slug"]: c for c in rep["channels"]}
    assert by["dead77"]["hours"] == 1.5 and not by["dead77"]["idle"]
    idle = [c for c in rep["channels"] if c["idle"]]
    assert idle and all(c["continuous"] and c["hours_30d"] < 1 for c in idle)
    assert rep["clients"][0] == {"name": "stereotop", "hours": 1.5}


def test_usage_route_owner_only(app_env):
    from app import auth, config
    c = TestClient(app)
    assert c.get("/api/admin/usage").status_code == 404
    auth.create_key_member("Kid", email="kid@example.com")
    c.cookies.set(config.SESSION_COOKIE, auth.new_session("kid@example.com"))
    assert c.get("/api/admin/usage").status_code == 404
    db.execute("UPDATE members SET role='owner' WHERE email=?", ("kid@example.com",))
    r = c.get("/api/admin/usage?days=7")
    assert r.status_code == 200 and r.json()["days"] == 7


def test_stream_client_tag_sanitised(app_env):
    from starlette.requests import Request
    from app.main import _listen_client
    req = Request({"type": "http", "query_string": b"client=stereo<top>", "headers": []})
    assert _listen_client(req) == "stereotop"


LOG = (
    '172.23.0.5 - - [07/Nov/2026:12:00:00 +0000] "GET /pat-and-john HTTP/1.1" 200 1 "-" "python-httpx/0.28.1" 600\n'
    '172.23.0.5 - - [07/Nov/2026:12:01:00 +0000] "GET /jam HTTP/1.1" 200 1 "-" "python-httpx/0.28.1" 3\n'
    '172.23.0.3 - - [07/Nov/2026:12:02:00 +0000] "SOURCE /jam HTTP/1.0" 200 19 "-" "Liquidsoap/2.2.5" 597\n'
    '172.23.0.5 - - [07/Nov/2026:12:03:00 +0000] "GET /status-json.xsl HTTP/1.1" 200 1 "-" "python-httpx/0.28.1" 0\n'
)


def test_backfill_loads_once(app_env, monkeypatch, capsys):
    from app import usage_backfill
    for _ in range(2):
        monkeypatch.setattr(sys, "stdin", io.TextIOWrapper(io.BytesIO(LOG.encode())))
        usage_backfill.main()
    rows = db.query("SELECT channel, client, started_at, seconds FROM listens")
    assert rows == [{"channel": "pat-and-john", "client": "icecast log",
                     "started_at": "2026-11-07 11:50:00", "seconds": 600}]


def test_internal_usage_host_gated(app_env):
    c = TestClient(app)
    assert c.get("/api/internal/usage").status_code == 404
    r = c.get("/api/internal/usage?days=7", headers={"Host": "jam-brain.localhost"})
    assert r.status_code == 200 and r.json()["days"] == 7


def test_internal_gate_refuses_tunnel_traffic(app_env):
    # the tunnel rewrites Host to jam-brain.localhost — the cf headers give it away
    c = TestClient(app)
    for hdr in ({"cf-ray": "8f00-EWR"}, {"cf-connecting-ip": "1.2.3.4"}, {"cdn-loop": "cloudflare"}):
        r = c.get("/api/internal/usage", headers={"Host": "jam-brain.localhost", **hdr})
        assert r.status_code == 404
        r = c.post("/api/internal/mint-session", json={"email": "x@example.com"},
                   headers={"Host": "jam-brain.localhost", **hdr})
        assert r.status_code == 404
