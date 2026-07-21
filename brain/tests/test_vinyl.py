"""The record wall: shaping, cache reading, sections. Network never touched."""
import json
import os

from app import config, discogs


def _cache(records):
    d = os.path.join(config.MUSIC_DIR, "_vinyl")
    os.makedirs(os.path.join(d, "covers"), exist_ok=True)
    with open(os.path.join(d, "collection.json"), "w") as f:
        json.dump({"synced_at": 1, "username": "jmimick", "records": records}, f)


def test_shape_cleans_discogs_disambiguation():
    r = discogs._shape({"id": 7, "basic_information": {
        "title": "Aja ", "year": 1977, "artists": [{"name": "Steely Dan (2)"}],
        "styles": ["Jazz-Rock"], "genres": ["Rock"], "cover_image": "http://x/y.jpg"}})
    assert r["artist"] == "Steely Dan"
    assert r["title"] == "Aja"
    assert r["styles"] == ["Jazz-Rock"]


def test_records_reads_cache_and_attaches_mirrored_covers(app_env):
    _cache([
        {"id": 1, "artist": "Miles Davis", "title": "Kind of Blue", "year": 1959,
         "styles": ["Modal"], "genres": ["Jazz"], "thumb": "http://x/1.jpg"},
        {"id": 2, "artist": "AC/DC", "title": "Back in Black", "year": 1980,
         "styles": ["Hard Rock"], "genres": ["Rock"], "thumb": "http://x/2.jpg"},
    ])
    open(os.path.join(config.MUSIC_DIR, "_vinyl", "covers", "1.jpg"), "wb").close()
    out = discogs.records()
    assert [r["artist"] for r in out] == ["AC/DC", "Miles Davis"]     # crate order
    byid = {r["id"]: r for r in out}
    assert byid[1]["cover_url"] == "/music/_vinyl/covers/1.jpg"
    assert "cover_url" not in byid[2]                                  # not mirrored yet
    assert "thumb" not in byid[1]                                      # Discogs URL stays private


def test_sections_prefer_styles_fall_back_to_genres(app_env):
    _cache([
        {"id": 1, "artist": "A", "title": "T1", "styles": ["Hard Bop"], "genres": ["Jazz"]},
        {"id": 2, "artist": "B", "title": "T2", "styles": ["Hard Bop"], "genres": ["Jazz"]},
        {"id": 3, "artist": "C", "title": "T3", "styles": [], "genres": ["Children's"]},
        {"id": 4, "artist": "D", "title": "T4", "styles": [], "genres": ["Children's"]},
        {"id": 5, "artist": "E", "title": "T5", "styles": ["Lone Style"], "genres": []},
    ])
    secs = {s["name"]: s["count"] for s in discogs.sections()}
    assert secs == {"Hard Bop": 2, "Children's": 2}     # singleton styles fold away


def test_records_empty_without_cache(app_env):
    assert discogs.records() == []
    assert discogs.sections() == []
