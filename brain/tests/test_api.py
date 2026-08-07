from fastapi.testclient import TestClient

from app.main import app


def test_health_and_channels(app_env):
    with TestClient(app) as client:
        h = client.get("/health").json()
        assert h["ok"] is True and h["db"] is True     # `ok` keeps its original meaning
        assert h["channels"] > 0 and h["shelf"] is None  # no shelf server configured here
        chans = client.get("/api/channels").json()
        assert any(c["slug"] == "dead77" for c in chans)


def test_internal_mint_session(app_env):
    from app import auth, config
    with TestClient(app) as client:
        # public callers (no internal Host header) never reach it
        r = client.post("/api/internal/mint-session", json={"email": "nobody@example.com"})
        assert r.status_code == 404

        internal = {"Host": "jam-brain.localhost"}
        # unknown/unapproved email: still 404, doesn't leak which
        r = client.post("/api/internal/mint-session", json={"email": "nobody@example.com"},
                         headers=internal)
        assert r.status_code == 404

        auth.create_key_member("Kid", email="kid@example.com")
        r = client.post("/api/internal/mint-session", json={"email": "kid@example.com"},
                         headers=internal)
        assert r.status_code == 200
        body = r.json()
        assert body["cookie_name"] == config.SESSION_COOKIE
        assert body["email"] == "kid@example.com"

        # the minted token is a real, usable session
        client.cookies.set(config.SESSION_COOKIE, body["cookie_value"])
        me = client.get("/api/me").json()["user"]
        assert me and me["email"] == "kid@example.com"


def test_banner_roundtrip(app_env):
    from app import auth, config, db
    with TestClient(app) as client:
        assert client.get("/api/banner").json() == {"text": ""}
        # non-owner can't set it
        auth.create_key_member("Kid", email="kid@example.com")
        client.cookies.set(config.SESSION_COOKIE, auth.new_session("kid@example.com"))
        r = client.post("/api/owner/banner", json={"text": "hi"})
        assert r.status_code == 403
        # owner can
        db.execute("UPDATE members SET role='owner' WHERE email=?", ("kid@example.com",))
        r = client.post("/api/owner/banner", json={"text": "  Deploying tonight — glitches possible  "})
        assert r.json()["text"] == "Deploying tonight — glitches possible"
        assert client.get("/api/banner").json()["text"] == "Deploying tonight — glitches possible"
        assert client.get("/health").json()["banner"] == "Deploying tonight — glitches possible"
        client.post("/api/owner/banner", json={"text": ""})     # clear takes it down
        assert client.get("/api/banner").json() == {"text": ""}


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
