from fastapi.testclient import TestClient

from app.main import app


def test_health_and_channels(app_env):
    with TestClient(app) as client:
        assert client.get("/health").json() == {"ok": True}
        chans = client.get("/api/channels").json()
        assert any(c["slug"] == "dead77" for c in chans)


def test_channels_liq_format(app_env):
    with TestClient(app) as client:
        body = client.get("/api/channels.liq").text
        lines = body.strip().split("\n")
        assert "dead77|Dead '77" in lines
        assert all("|" in line for line in lines)


def test_next_endpoint(app_env):
    with TestClient(app) as client:
        r = client.get("/api/next", params={"channel": "dead77"})
        assert r.status_code == 200
        assert r.text.startswith("annotate:")


def test_nowplaying_roundtrip(app_env):
    with TestClient(app) as client:
        r = client.post("/api/nowplaying", json={
            "channel": "dead77", "title": "Scarlet Begonias",
            "artist": "Grateful Dead", "album": "Barton Hall"})
        assert r.json() == {"ok": True}
        np = client.get("/api/nowplaying", params={"channel": "dead77"}).json()
        assert np["title"] == "Scarlet Begonias"


def test_index_served(app_env):
    with TestClient(app) as client:
        r = client.get("/")
        assert r.status_code == 200
        assert "jam-station" in r.text
