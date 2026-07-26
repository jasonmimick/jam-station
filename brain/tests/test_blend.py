"""The blend adapter: genre-balanced RADIO100 across library + attic."""
import json
import os

import httpx
import pytest

from app import auth, channels, config
from app.adapters import attic, blend, library


def _album(name: str, tracks: int, genres=None) -> None:
    folder = os.path.join(config.MUSIC_DIR, "cds", name)
    os.makedirs(folder, exist_ok=True)
    for i in range(1, tracks + 1):
        open(os.path.join(folder, f"{i:02d} Song {i}.mp3"), "wb").close()
    if genres is not None:
        with open(os.path.join(folder, "_album.json"), "w") as f:
            json.dump({"genres": genres}, f)


def _attic_catalog():
    tracks = []
    for artist, album, n, genres in [
        ("Miles Davis", "Kind of Blue", 4, ["Jazz"]),
        ("Brook Sounds", "Field Recordings", 2, ["Ambient"]),
    ]:
        for i in range(1, n + 1):
            path = f"{artist}/{album}/{i:02d} Song {i}.mp3"
            tracks.append({
                "root": "drive03", "path": path, "artist": artist, "album": album,
                "title": f"Song {i}", "genres": genres,
                "url": "/file/drive03/" + path.replace(" ", "%20"),
            })
    return {"categories": ["Jazz", "Ambient"], "tracks": tracks, "bytes": 1}


@pytest.fixture()
def shelf(app_env, monkeypatch):
    monkeypatch.setattr(config, "ATTIC_SERVER_URL", "http://shelf:8517")

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/catalog.json":
            return httpx.Response(200, json=_attic_catalog())
        return httpx.Response(404)

    attic.set_client(httpx.Client(transport=httpx.MockTransport(handler)))
    yield


# ── the adapter ──────────────────────────────────────────────────────────────

def test_no_sources_means_no_tracks(app_env):
    assert blend.pick_tracks({}) == []


def test_balances_a_huge_genre_against_a_tiny_one(app_env):
    _album("A - Jazz Big", 20, ["Jazz"])
    _album("B - Rock Small", 2, ["Rock"])
    picks = blend.pick_tracks({}, count=4)
    assert len(picks) == 4
    by_album = {}
    for t in picks:
        by_album[t["album"]] = by_album.get(t["album"], 0) + 1
    # round-robin: the 2-track genre isn't drowned out by the 20-track one
    assert by_album.get("Rock Small", 0) == 2
    assert by_album.get("Jazz Big", 0) == 2


def test_untagged_albums_get_their_own_bucket(app_env):
    _album("A - No Genre", 3)              # no _album.json at all
    picks = blend.pick_tracks({}, count=3)
    assert len(picks) == 3
    assert all(t["album"] == "No Genre" for t in picks)


def test_blends_library_and_attic(shelf):
    _album("A - Jazz Shelf", 4, ["Jazz"])
    picks = blend.pick_tracks({}, count=10)
    albums = {t["album"] for t in picks}
    assert "Jazz Shelf" in albums                    # library side
    assert {"Kind of Blue", "Field Recordings"} & albums  # attic side
    assert all(t["url"].startswith(("/music/", "/attic/")) for t in picks)


def test_sources_cfg_filters_to_one_source(shelf):
    _album("A - Jazz Shelf", 4, ["Jazz"])
    only_library = blend.pick_tracks({"sources": ["library"]}, count=10)
    assert all(t["url"].startswith("/music/") for t in only_library)
    only_attic = blend.pick_tracks({"sources": ["attic"]}, count=10)
    assert all(t["url"].startswith("/attic/") for t in only_attic)


# ── channel wiring ───────────────────────────────────────────────────────────

def test_radio100_is_seeded_private_and_streamable(shelf):
    _album("A - Jazz Shelf", 4, ["Jazz"])
    by_slug = {c["slug"]: c for c in channels.list_channels()}
    assert "radio100" in by_slug
    assert by_slug["radio100"]["private"] is True
    assert by_slug["radio100"]["playable"] is True
    liq = {c["slug"] for c in channels.list_channels(streamable_only=True)}
    assert "radio100" in liq                          # a real broadcast mount, not mix-only


def test_radio100_queues_and_annotates(shelf):
    _album("A - Jazz Shelf", 4, ["Jazz"])
    assert channels.ensure_queue("radio100") > 0
    uri = channels.next_track("radio100")
    assert uri.startswith("annotate:")


def test_radio100_hidden_from_anonymous(shelf):
    from fastapi.testclient import TestClient
    from app.main import app
    _album("A - Jazz Shelf", 4, ["Jazz"])
    with TestClient(app) as client:
        anon = {c["slug"] for c in client.get("/api/channels").json()}
        assert "radio100" not in anon
        auth.create_key_member("Kid", email="kid@example.com")
        client.cookies.set(config.SESSION_COOKIE, auth.new_session("kid@example.com"))
        seen = {c["slug"] for c in client.get("/api/channels").json()}
        assert "radio100" in seen
