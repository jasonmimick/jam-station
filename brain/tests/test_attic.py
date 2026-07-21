"""The attic shelf server adapter: vault stations, categories, and the /api/mix door."""
import httpx
import pytest

from app import auth, channels, config
from app.adapters import attic


def _catalog():
    tracks = []
    for artist, album, n, genres in [
        ("Miles Davis", "Kind of Blue", 6, ["Jazz"]),
        ("John Coltrane", "Giant Steps", 6, ["Jazz"]),
        ("Neil Young", "Harvest", 3, ["Rock", "Folk"]),
    ]:
        for i in range(1, n + 1):
            path = f"{artist}/{album}/{i:02d} Song {i}.mp3"
            tracks.append({
                "root": "drive03", "path": path, "artist": artist, "album": album,
                "title": f"Song {i}", "genres": genres,
                "url": "/file/drive03/" + path.replace(" ", "%20"),
            })
    # Rock has 3 tracks — below ATTIC_CHANNEL_MIN, so it never earns a channel
    return {"categories": ["Jazz", "Rock"], "tracks": tracks}


@pytest.fixture()
def shelf(app_env, monkeypatch):
    """A mocked shelf server behind ATTIC_SERVER_URL."""
    monkeypatch.setattr(config, "ATTIC_SERVER_URL", "http://shelf:8517")

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/catalog.json":
            return httpx.Response(200, json=_catalog())
        return httpx.Response(404)

    attic.set_client(httpx.Client(transport=httpx.MockTransport(handler)))
    yield


def _member_cookie(client):
    auth.create_key_member("Kid", email="kid@example.com")
    client.cookies.set(config.SESSION_COOKIE, auth.new_session("kid@example.com"))


# ── the adapter ──────────────────────────────────────────────────────────────

def test_no_shelf_server_means_no_tracks(app_env, monkeypatch):
    monkeypatch.setattr(config, "ATTIC_SERVER_URL", "")
    assert attic.pick_tracks({"all": True}) == []
    assert attic.categories() == []


def test_unreachable_shelf_server_degrades(app_env, monkeypatch):
    monkeypatch.setattr(config, "ATTIC_SERVER_URL", "http://shelf:8517")

    def down(request):
        raise httpx.ConnectError("no route to host")

    attic.set_client(httpx.Client(transport=httpx.MockTransport(down)))
    assert attic.pick_tracks({"all": True}) == []      # off air, not broken


def test_pick_tracks_all_and_urls_are_brain_proxied(shelf):
    picks = attic.pick_tracks({"all": True}, count=50)
    assert len(picks) == 15
    # stored same-origin so the browser plays them through the members-gated proxy;
    # _for_liquidsoap makes them absolute+keyed for the radio container
    assert all(t["url"].startswith("/attic/drive03/") for t in picks)
    assert all("/file/" not in t["url"] for t in picks)


def test_pick_tracks_by_artist_and_genre(shelf):
    picks = attic.pick_tracks({"artist": "miles davis"}, count=20)
    assert picks and all(t["artist"] == "Miles Davis" for t in picks)
    picks = attic.pick_tracks({"genre": "jazz"}, count=20)
    assert len(picks) == 12
    assert all(t["artist"] in ("Miles Davis", "John Coltrane") for t in picks)
    assert attic.pick_tracks({"genre": "Classical"}) == []


def test_spotlight_is_one_artist_per_batch(shelf):
    for _ in range(5):
        picks = attic.pick_tracks({"spotlight": True}, count=20)
        assert picks and len({t["artist"] for t in picks}) == 1


def test_genre_counts_only_declared_categories(shelf):
    counts = attic.genre_counts()
    assert counts == {"Jazz": 12, "Rock": 3}           # Folk present in tags, not declared


# ── channels wiring ──────────────────────────────────────────────────────────

def test_attic_channel_queues_and_annotates(shelf):
    channels.create_channel("vault", "The Vault", "everything", "attic", {"all": True})
    assert channels.ensure_queue("vault") > 0
    uri = channels.next_track("vault")
    assert uri.startswith("annotate:")
    # liquidsoap can't use a same-origin path: it must get the brain's absolute keyed url
    assert f"{config.INTERNAL_URL}/attic/" in uri and f"k={config.MUSIC_KEY}" in uri


def test_sync_attic_channels_creates_and_retires(shelf):
    channels.sync_attic_channels()
    slugs = {c["slug"] for c in channels.list_channels()}
    assert "vault-jazz" in slugs                       # 12 tracks >= ATTIC_CHANNEL_MIN
    assert "vault-rock" not in slugs                   # 3 tracks — not enough
    # the shelf server goes away -> its categories retire from the dial
    attic.set_client(httpx.Client(transport=httpx.MockTransport(
        lambda r: httpx.Response(200, json={"categories": [], "tracks": []}))))
    channels.sync_attic_channels()
    slugs = {c["slug"] for c in channels.list_channels()}
    assert "vault-jazz" not in slugs


def test_vault_channels_are_private_and_mix_only(shelf):
    channels.create_channel("vault", "The Vault", "", "attic", {"all": True})
    channels.sync_attic_channels()
    by_slug = {c["slug"]: c for c in channels.list_channels()}
    assert by_slug["vault"]["private"] is True
    assert by_slug["vault-jazz"]["private"] is True
    liq = {c["slug"] for c in channels.list_channels(streamable_only=True)}
    assert "vault" in liq                              # a real broadcast mount
    assert "vault-jazz" not in liq                     # mix-only, liquidsoap never mounts it


def test_unplayable_without_shelf_server(app_env, monkeypatch):
    monkeypatch.setattr(config, "ATTIC_SERVER_URL", "")
    channels.create_channel("vault", "The Vault", "", "attic", {"all": True})
    ch = [c for c in channels.list_channels() if c["slug"] == "vault"][0]
    assert ch["playable"] is False                     # honestly OFF AIR
    assert "vault" not in {c["slug"] for c in channels.list_channels(streamable_only=True)}


# ── the API ──────────────────────────────────────────────────────────────────

def test_attic_channels_hidden_from_anonymous(shelf):
    from fastapi.testclient import TestClient
    from app.main import app
    channels.create_channel("vault", "The Vault", "", "attic", {"all": True})
    with TestClient(app) as client:
        anon = {c["slug"] for c in client.get("/api/channels").json()}
        assert "vault" not in anon
        _member_cookie(client)
        seen = {c["slug"] for c in client.get("/api/channels").json()}
        assert "vault" in seen


def test_tracks_carry_lazy_cover_url(shelf):
    t = attic.pick_tracks({"artist": "Miles Davis"}, count=1)[0]
    assert t["cover_url"].startswith("/api/attic/cover?")
    assert "Kind+of+Blue" in t["cover_url"] or "Kind%20of%20Blue" in t["cover_url"]


def test_attic_cover_fetches_once_then_caches(shelf, monkeypatch):
    from fastapi.testclient import TestClient
    from app import covers
    from app.main import app
    calls = []

    def fake_itunes(artist, album, dest):
        calls.append(album)
        with open(dest, "wb") as f:
            f.write(b"\xff\xd8fakejpg")
        return True

    monkeypatch.setattr(covers, "_itunes_cover", fake_itunes)
    with TestClient(app) as client:
        url = "/api/attic/cover?artist=Miles+Davis&album=Kind+of+Blue"
        assert client.get(url).status_code == 403          # members only
        _member_cookie(client)
        assert client.get(url).status_code == 200          # fetched
        assert client.get(url).status_code == 200          # cached
        assert calls == ["Kind of Blue"]                   # iTunes hit exactly once
        # a miss is cached too — one lookup, then 404s forever
        monkeypatch.setattr(covers, "_itunes_cover", lambda *a: calls.append("miss") or False)
        miss = "/api/attic/cover?artist=Obscure&album=Nothing"
        assert client.get(miss).status_code == 404
        assert client.get(miss).status_code == 404
        assert calls.count("miss") == 1


def test_attic_crate_lists_and_plays_albums(shelf):
    albums = attic.list_albums()
    assert {a["album"] for a in albums} == {"Kind of Blue", "Giant Steps", "Harvest"}
    kob = [a for a in albums if a["album"] == "Kind of Blue"][0]
    assert kob["tracks"] == 6 and kob["dir"] == "attic:drive03/Miles Davis/Kind of Blue"
    tracks = attic.album_tracks(kob["dir"])
    assert [t["title"] for t in tracks] == [f"Song {i}" for i in range(1, 7)]  # running order
    assert attic.album_tracks("attic:drive03/Nobody/Nothing") == []


def test_attic_albums_api_and_album_door(shelf):
    from fastapi.testclient import TestClient
    from app.main import app
    with TestClient(app) as client:
        assert client.get("/api/attic/albums").json() == []          # anonymous: empty, not 403
        _member_cookie(client)
        albums = client.get("/api/attic/albums").json()
        assert len(albums) == 3
        # attic albums play through the SAME album door the CD gallery uses
        show = client.get("/api/library/album",
                          params={"dir": albums[0]["dir"]}).json()
        assert show["tracks"] and all(t["url"].startswith("/attic/") for t in show["tracks"])


def test_artist_mix_and_api(shelf):
    mix = attic.artist_mix("miles davis")                # case-insensitive, whole catalog
    assert len(mix) == 6 and all(t["artist"] == "Miles Davis" for t in mix)
    from fastapi.testclient import TestClient
    from app.main import app
    with TestClient(app) as client:
        assert client.get("/api/attic/artist", params={"name": "Miles Davis"}).status_code == 403
        _member_cookie(client)
        show = client.get("/api/attic/artist", params={"name": "Miles Davis"}).json()
        assert len(show["tracks"]) == 6 and show["album"] == "Miles Davis — from the attic"
        assert client.get("/api/attic/artist", params={"name": "Nobody"}).status_code == 404


def test_api_mix_dispatches_by_source(shelf):
    from fastapi.testclient import TestClient
    from app.main import app
    with TestClient(app) as client:                    # lifespan syncs vault-jazz
        assert client.get("/api/mix", params={"slug": "vault-jazz"}).status_code == 403
        _member_cookie(client)
        mix = client.get("/api/mix", params={"slug": "vault-jazz"}).json()
        assert mix["tracks"] and all(t["url"].startswith("/attic/") for t in mix["tracks"])
        assert all(t["artist"] in ("Miles Davis", "John Coltrane") for t in mix["tracks"])
        assert client.get("/api/mix", params={"slug": "dead77"}).status_code == 404
