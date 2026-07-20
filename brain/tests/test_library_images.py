"""Multiple typed photos per album: enumeration, the type->slug rule, and the typed upload."""
import io
import os

from fastapi.testclient import TestClient

from app import auth, config
from app.adapters import library
from app.main import app

JPEG = b"\xff\xd8\xff\xe0" + b"0" * 64          # enough to look like a jpeg to a byte sink


def _album(name: str, tracks: int = 2) -> str:
    folder = os.path.join(config.MUSIC_DIR, "cds", name)
    os.makedirs(folder, exist_ok=True)
    for i in range(1, tracks + 1):
        open(os.path.join(folder, f"{i:02d} Song {i}.mp3"), "wb").close()
    return os.path.join("cds", name)


def test_art_slug_sanitizes():
    assert library.art_slug("Tracklist") == "tracklist"
    assert library.art_slug("Back Insert") == "back-insert"
    assert library.art_slug("  disc!! ") == "disc"
    assert library.art_slug("../../etc") == "etc"          # no path chars survive
    assert library.art_slug("x" * 40) == "x" * 24          # capped
    assert library.art_slug("") == ""


def test_album_images_front_then_extras_sorted(app_env):
    rel = _album("Miles - Kind of Blue")
    folder = os.path.join(config.MUSIC_DIR, rel)
    # no cover, no extras yet -> nothing
    assert library.album_images(rel) == []
    open(os.path.join(folder, "_cover.jpg"), "wb").close()
    open(os.path.join(folder, "_art-tracklist.jpg"), "wb").close()
    open(os.path.join(folder, "_art-back.jpg"), "wb").close()
    open(os.path.join(folder, "not-art.jpg"), "wb").close()   # ignored — wrong prefix
    imgs = library.album_images(rel)
    assert imgs[0] == {"type": "front", "url": "/music/cds/Miles%20-%20Kind%20of%20Blue/_cover.jpg"}
    # front first, then extras alphabetized by type
    assert [i["type"] for i in imgs] == ["front", "back", "tracklist"]
    assert all("_art-" in i["url"] for i in imgs[1:])


def test_album_images_refuses_escape(app_env):
    assert library.album_images("../../etc") == []


def _authed_client() -> TestClient:
    r = auth.create_key_member("Owner", email="owner@example.com")
    raw = auth.new_session(r["email"])
    c = TestClient(app)
    c.cookies.set(config.SESSION_COOKIE, raw)
    return c


def test_typed_upload_writes_art_file_and_album_carries_images(app_env):
    rel = _album("Trane - Giant Steps")
    folder = os.path.join(config.MUSIC_DIR, rel)
    c = _authed_client()

    # a typed photo lands as _art-<slug>.jpg, NOT _cover.jpg
    r = c.post("/api/library/cover",
               data={"dir": rel, "type": "Tracklist"},
               files={"photo": ("t.jpg", io.BytesIO(JPEG), "image/jpeg")})
    assert r.status_code == 200 and r.json() == {"ok": True, "type": "tracklist"}
    assert os.path.exists(os.path.join(folder, "_art-tracklist.jpg"))
    assert not os.path.exists(os.path.join(folder, "_cover.jpg"))

    # the default/front path still writes _cover.jpg
    r = c.post("/api/library/cover",
               data={"dir": rel, "type": "front"},
               files={"photo": ("c.jpg", io.BytesIO(JPEG), "image/jpeg")})
    assert r.json() == {"ok": True, "type": "front"}
    assert os.path.exists(os.path.join(folder, "_cover.jpg"))

    # and the album detail now carries both, front first
    got = c.get(f"/api/library/album?dir={rel}").json()
    assert [i["type"] for i in got["images"]] == ["front", "tracklist"]


def test_typed_upload_is_members_only(app_env):
    rel = _album("Anon - Nope")
    r = TestClient(app).post("/api/library/cover",
                             data={"dir": rel, "type": "back"},
                             files={"photo": ("t.jpg", io.BytesIO(JPEG), "image/jpeg")})
    assert r.status_code == 403
