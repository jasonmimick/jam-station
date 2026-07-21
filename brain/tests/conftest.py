import json
import os
import sys

import httpx
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

SEARCH_DOCS = [
    {"identifier": "gd1977-05-08.sbd.hicks.4982", "title": "Grateful Dead Live at Barton Hall",
     "date": "1977-05-08T00:00:00Z", "year": 1977, "venue": "Barton Hall, Cornell University",
     "avg_rating": 4.9, "num_reviews": 400},
    {"identifier": "gd1977-05-22.sbd", "title": "Grateful Dead Live at The Sportatorium",
     "date": "1977-05-22T00:00:00Z", "year": 1977, "venue": "Pembroke Pines",
     "avg_rating": 4.7, "num_reviews": 120},
]

METADATA = {
    "metadata": {"title": "Grateful Dead Live at Barton Hall on 1977-05-08",
                 "date": "1977-05-08", "venue": "Barton Hall, Cornell University",
                 "creator": "Grateful Dead"},
    "files": [
        {"name": "gd77-05-08d1t01.mp3", "format": "VBR MP3", "title": "New Minglewood Blues", "track": "01", "length": "300.1"},
        {"name": "gd77-05-08d1t02.mp3", "format": "VBR MP3", "title": "Loser", "track": "02", "length": "421.9"},
        {"name": "gd77-05-08d1t01.flac", "format": "Flac", "title": "New Minglewood Blues", "track": "01"},
        {"name": "gd77-05-08.txt", "format": "Text"},
    ],
}


PHISHIN_SHOWS = [
    {"date": "1997-11-17", "venue_name": "McNichols Arena", "tour_name": "Fall Tour 1997",
     "venue": {"location": "Denver, CO"}, "likes_count": 172, "duration": 8971076,
     "audio_status": "complete"},
    {"date": "1999-12-31", "venue_name": "Big Cypress Seminole Indian Reservation",
     "tour_name": "Big Cypress", "venue": {"location": "Big Cypress, FL"},
     "likes_count": 313, "duration": 32774349, "audio_status": "complete"},
]

PHISHIN_SHOW = {
    "date": "1997-11-17", "venue_name": "McNichols Arena", "likes_count": 172,
    "tracks": [
        {"title": "Tweezer", "position": 1, "slug": "tweezer", "duration": 1072274,
         "mp3_url": "https://phish.in/blob/track1.mp3"},
        {"title": "Reba", "position": 2, "slug": "reba", "duration": 900000,
         "mp3_url": "https://phish.in/blob/track2.mp3"},
        {"title": "No Audio", "position": 3, "slug": "no-audio", "duration": 0,
         "mp3_url": None},
    ],
}


def _handler(request: httpx.Request) -> httpx.Response:
    if request.url.path == "/advancedsearch.php":
        return httpx.Response(200, json={"response": {"docs": SEARCH_DOCS}})
    if request.url.path.startswith("/metadata/"):
        return httpx.Response(200, json=METADATA)
    if request.url.path.startswith("/download/"):
        return httpx.Response(200, content=b"\xff\xfb" + b"0" * 64)  # fake mp3 bytes
    return httpx.Response(404)


def _phishin_handler(request: httpx.Request) -> httpx.Response:
    if request.url.path == "/api/v2/shows":
        shows = PHISHIN_SHOWS
        year = request.url.params.get("year")
        if year:
            shows = [s for s in shows if s["date"].startswith(year)]
        return httpx.Response(200, json={"shows": shows, "total_entries": len(shows)})
    if request.url.path.startswith("/api/v2/shows/"):
        return httpx.Response(200, json=PHISHIN_SHOW)
    if request.url.path.startswith("/blob/"):
        return httpx.Response(200, content=b"\xff\xfb" + b"0" * 64)
    return httpx.Response(404)


def _test_db_url():
    """The configured DATABASE_URL with '_test' appended to the database name.

    Tests must NEVER run against the configured database itself: on the mini that is
    production — members, sessions, play history. (The old fixture patched DB_PATH,
    which the Postgres migration stopped reading, so every test run silently wrote
    into the live database and the suite rotted as state accumulated.)"""
    import re
    from app import config
    m = re.search(r"/([^/?]+?)(\?[^/]*)?$", config.DATABASE_URL)
    name = m.group(1) + "_test"
    return config.DATABASE_URL[: m.start(1)] + name + (m.group(2) or ""), name


@pytest.fixture()
def app_env(tmp_path, monkeypatch):
    """Fresh temp dirs + a dedicated, wiped _test database + mocked archive.org."""
    from app import config
    monkeypatch.setattr(config, "DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setattr(config, "CACHE_DIR", str(tmp_path / "cache"))
    monkeypatch.setattr(config, "MUSIC_DIR", str(tmp_path / "music"))
    monkeypatch.setattr(config, "PREFETCH", False)
    # next_track fires a background top-up thread; with the production MIN_QUEUE it races
    # the test's own assertions (it reliably LOST that race on SQLite and reliably wins it
    # on Postgres). At 1, "anything unserved" means topped-up, so the thread adds nothing.
    monkeypatch.setattr(config, "MIN_QUEUE", 1)

    import psycopg
    test_url, test_name = _test_db_url()
    with psycopg.connect(config.DATABASE_URL, autocommit=True) as con:
        try:
            con.execute(f'CREATE DATABASE "{test_name}"')
        except psycopg.errors.DuplicateDatabase:
            pass
    monkeypatch.setattr(config, "DATABASE_URL", test_url)

    from app.adapters import archive, attic, phishin
    archive.set_client(httpx.Client(transport=httpx.MockTransport(_handler),
                                    base_url="https://archive.org"))
    phishin.set_client(httpx.Client(transport=httpx.MockTransport(_phishin_handler),
                                    base_url="https://phish.in"))
    attic.set_client(None)   # cold cache; tests that want a shelf server inject their own

    from app import db, channels
    # the pool may still hold connections to the previous URL — rebuild it lazily,
    # and blow the schema away so every test starts from genuinely nothing
    if db._pool is not None:
        db._pool.close()
        db._pool = None
    with psycopg.connect(test_url, autocommit=True) as con:
        con.execute("DROP SCHEMA public CASCADE")
        con.execute("CREATE SCHEMA public")
    # background top-up threads from a previous test can still hold a
    # per-channel lock; start each test with a fresh lock table
    channels._topup_locks.clear()
    from app import presence
    presence._streams.clear(); presence._beats.clear(); presence._seen.clear()   # presence is process-global too
    db.init()
    channels.ensure_seeded()
    yield
    archive.set_client(None)  # type: ignore[arg-type]
    phishin.set_client(None)  # type: ignore[arg-type]
    attic.set_client(None)
    if db._pool is not None:
        db._pool.close()
        db._pool = None
