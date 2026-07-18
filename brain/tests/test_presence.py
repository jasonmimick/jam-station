"""Who's listening: stream connections + on-demand heartbeats, member-gated listing."""
import time

from fastapi.testclient import TestClient

from app import presence
from app.main import app


def test_stream_connect_and_disconnect(app_env):
    sid = presence.stream_connect("Dad", "dad@example.com", "dead77")
    ls = presence.listeners()
    assert any(l["name"] == "Dad" and l["channel"] == "dead77" and l["mode"] == "radio" for l in ls)
    presence.stream_disconnect(sid)
    assert not any(l["name"] == "Dad" for l in presence.listeners())


def test_heartbeat_expires(app_env, monkeypatch):
    presence.heartbeat("Bob", "bob@example.com", "bob@example.com", "cds/Some Album")
    assert any(l["name"] == "Bob" and l["mode"] == "ondemand" for l in presence.listeners())
    # jump past the TTL — the beat should be culled, not linger forever
    real = time.time
    monkeypatch.setattr(time, "time", lambda: real() + presence.HEARTBEAT_TTL + 1)
    assert not any(l["name"] == "Bob" for l in presence.listeners())


def test_same_person_same_channel_collapses(app_env):
    presence.heartbeat("Ann", "ann@example.com", "ann@example.com", "dead77")
    sid = presence.stream_connect("Ann", "ann@example.com", "dead77")
    rows = [l for l in presence.listeners() if l["name"] == "Ann"]
    assert len(rows) == 1 and rows[0]["mode"] == "radio"     # radio wins
    presence.stream_disconnect(sid)


def test_listeners_endpoint_anonymous_sees_empty_room(app_env):
    presence.stream_connect("Dad", "dad@example.com", "dead77")
    c = TestClient(app)
    d = c.get("/api/listeners").json()
    assert d == {"count": 0, "listeners": []}    # soft gate, same spirit as the catalog


def test_presence_endpoint_accepts_anonymous_beat(app_env):
    c = TestClient(app)
    r = c.post("/api/presence", json={"channel": "on-demand", "aid": "testdevice1"})
    assert r.status_code == 200
    assert any(l["name"] == "Someone" for l in presence.listeners())
