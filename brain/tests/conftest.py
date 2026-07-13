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


def _handler(request: httpx.Request) -> httpx.Response:
    if request.url.path == "/advancedsearch.php":
        return httpx.Response(200, json={"response": {"docs": SEARCH_DOCS}})
    if request.url.path.startswith("/metadata/"):
        return httpx.Response(200, json=METADATA)
    if request.url.path.startswith("/download/"):
        return httpx.Response(200, content=b"\xff\xfb" + b"0" * 64)  # fake mp3 bytes
    return httpx.Response(404)


@pytest.fixture()
def app_env(tmp_path, monkeypatch):
    """Fresh temp DB/dirs + mocked archive.org for every test."""
    from app import config
    monkeypatch.setattr(config, "DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setattr(config, "CACHE_DIR", str(tmp_path / "cache"))
    monkeypatch.setattr(config, "MUSIC_DIR", str(tmp_path / "music"))
    monkeypatch.setattr(config, "DB_PATH", str(tmp_path / "data" / "channels.db"))
    monkeypatch.setattr(config, "PREFETCH", False)

    from app.adapters import archive
    archive.set_client(httpx.Client(transport=httpx.MockTransport(_handler),
                                    base_url="https://archive.org"))

    from app import db, channels
    db.init()
    channels.ensure_seeded()
    yield
    archive.set_client(None)  # type: ignore[arg-type]
