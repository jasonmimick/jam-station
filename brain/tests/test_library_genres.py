"""Genres on the shelf: bucket mapping, section counts, mixes, owner curation."""
import json
import os

from app import config, covers
from app.adapters import library


def _album(tmp_music: str, name: str, tracks: int, genres=None, owner=False) -> str:
    folder = os.path.join(tmp_music, "cds", name)
    os.makedirs(folder, exist_ok=True)
    for i in range(1, tracks + 1):
        open(os.path.join(folder, f"{i:02d} Song {i}.mp3"), "wb").close()
    if genres is not None:
        meta = {"genres": genres}
        if owner:
            meta["genres_owner"] = True
        with open(os.path.join(folder, "_album.json"), "w") as f:
            json.dump(meta, f)
    return os.path.join("cds", name)


def test_bucketize_maps_fine_tags_to_coarse_sections():
    assert covers.bucketize(["bebop", "hard bop"]) == ["Jazz"]
    assert covers.bucketize(["progressive rock", "psychedelic"]) == ["Rock"]
    assert covers.bucketize(["jazz fusion", "funk"]) == ["Jazz", "Soul/Funk"]
    assert covers.bucketize(["polka oompa"]) == []          # unknown tags stay unmapped
    assert len(covers.bucketize(["jazz", "rock", "pop", "folk", "blues"])) == 3


def test_genre_counts_aggregates_the_shelf(app_env):
    _album(config.MUSIC_DIR, "Miles - Kind of Blue", 3, ["Jazz"])
    _album(config.MUSIC_DIR, "Trane - Giant Steps", 3, ["Jazz"])
    _album(config.MUSIC_DIR, "Hendrix - Axis", 3, ["Rock"])
    _album(config.MUSIC_DIR, "Unknown - Mystery", 3)        # no sidecar, no section
    counts = library.genre_counts()
    assert counts[0] == {"name": "Jazz", "count": 2}
    assert {"name": "Rock", "count": 1} in counts


def test_build_mix_stays_inside_the_section(app_env):
    _album(config.MUSIC_DIR, "Miles - Kind of Blue", 4, ["Jazz"])
    _album(config.MUSIC_DIR, "Trane - Giant Steps", 4, ["Jazz"])
    _album(config.MUSIC_DIR, "Hendrix - Axis", 4, ["Rock"])
    mix = library.build_mix("jazz", count=6)                # case-insensitive
    assert len(mix) == 6
    assert all(t["album"] in ("Kind of Blue", "Giant Steps") for t in mix)
    assert library.build_mix("Classical") == []


def test_set_genres_owner_pin_and_mtime(app_env):
    rel = _album(config.MUSIC_DIR, "Fela - Zombie", 2, ["Pop"])
    folder = os.path.join(config.MUSIC_DIR, rel)
    os.utime(folder, (1_600_000_000, 1_600_000_000))        # a week-old rip
    assert library.set_genres(rel, ["World", "  ", "Soul/Funk"])
    meta = json.load(open(os.path.join(folder, "_album.json")))
    assert meta["genres"] == ["World", "Soul/Funk"]         # blanks dropped
    assert meta["genres_owner"] is True
    # folder mtime IS "date added" — curation must not shuffle the gallery
    assert abs(os.stat(folder).st_mtime - 1_600_000_000) < 2
    assert not library.set_genres("../../etc", ["X"])       # no climbing out


def test_enricher_skips_owner_set_genres(app_env, monkeypatch):
    rel = _album(config.MUSIC_DIR, "Fela - Zombie", 2, ["World"], owner=True)
    folder = os.path.join(config.MUSIC_DIR, rel)
    monkeypatch.setattr(covers, "_search_release", lambda a, b: {"mbid": "m1", "year": "1976"})
    monkeypatch.setattr(covers, "_genres", lambda mbid: ["Pop"])
    monkeypatch.setattr(covers, "_fetch_cover", lambda m, d: False)
    monkeypatch.setattr(covers, "_itunes_cover", lambda a, b, d: False)
    monkeypatch.setattr(covers.time, "sleep", lambda s: None)
    covers._enrich_one(folder, "Fela - Zombie")
    meta = json.load(open(os.path.join(folder, "_album.json")))
    assert meta["genres"] == ["World"]                      # the owner's word stands


def test_sections_become_stations(app_env):
    from app import channels
    for i in range(3):
        _album(config.MUSIC_DIR, f"Cat {i} - Jazz Album {i}", 2, ["Jazz"])
    _album(config.MUSIC_DIR, "Lone - Rock Album", 2, ["Rock"])   # below threshold
    channels.sync_genre_channels()
    chans = {c["slug"]: c for c in channels.list_channels()}
    assert "shelf-jazz" in chans
    assert chans["shelf-jazz"]["name"] == "From the Shelf — Jazz"
    assert chans["shelf-jazz"]["private"] is True
    assert chans["shelf-jazz"]["playable"] is True
    assert "shelf-rock" not in chans                             # 1 record ≠ a station
    # the section empties -> the station retires
    for i in range(3):
        library.set_genres(f"cds/Cat {i} - Jazz Album {i}", [])
    channels.sync_genre_channels()
    assert "shelf-jazz" not in {c["slug"] for c in channels.list_channels()}


def test_pick_tracks_by_genre_stays_in_section(app_env):
    _album(config.MUSIC_DIR, "A - Jazz One", 3, ["Jazz"])
    _album(config.MUSIC_DIR, "B - Rock One", 3, ["Rock"])
    picks = library.pick_tracks({"genre": "jazz"}, count=10)
    assert picks and all(t["album"] == "Jazz One" for t in picks)
    assert library.pick_tracks({"genre": "Classical"}) == []


def test_genre_stations_are_mix_only_not_streamed(app_env):
    from app import channels
    for i in range(3):
        _album(config.MUSIC_DIR, f"Cat {i} - Jazz Album {i}", 2, ["Jazz"])
    channels.sync_genre_channels()
    dial = {c["slug"] for c in channels.list_channels()}
    liq = {c["slug"] for c in channels.list_channels(streamable_only=True)}
    assert "shelf-jazz" in dial          # on the dial for members
    assert "shelf-jazz" not in liq       # but liquidsoap never mounts it
