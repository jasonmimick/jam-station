"""Filename -> track tags, including the Various-Artists mix form where every track names
its own artist (a homemade comp like 'iSS.1'). The path IS the tags."""
import os

from app import config
from app.adapters import library


def _write(folder_name: str, filenames: list[str]) -> str:
    folder = os.path.join(config.MUSIC_DIR, "cds", folder_name)
    os.makedirs(folder, exist_ok=True)
    for fn in filenames:
        open(os.path.join(folder, fn), "wb").close()
    return os.path.join("cds", folder_name)


def test_classic_ripped_cd_takes_artist_from_folder(app_env):
    """'Artist - Album/07 Title' — the artist lives in the folder, unchanged behaviour."""
    rel = _write("Bela Fleck - UFO Tofu", ["09 Life Without Elvis.mp3"])
    t = library.album_tracks(rel)[0]
    assert t["artist"] == "Bela Fleck"
    assert t["album"] == "UFO Tofu"
    assert t["title"] == "Life Without Elvis"


def test_various_artists_mix_keeps_per_track_artist(app_env):
    """'Various Artists - iSS.1/03 Pink Floyd - Speak to Me' — number stripped first, then the
    per-track artist survives; the folder only supplies the album."""
    rel = _write("Various Artists - iSS.1", [
        "01 Phish - Ghost.mp3",
        "03 Pink Floyd - Speak to Me - Breathe.mp3",
    ])
    tracks = {t["title"]: t for t in library.album_tracks(rel)}
    assert tracks["Ghost"]["artist"] == "Phish"
    assert tracks["Ghost"]["album"] == "iSS.1"
    # a title that itself contains ' - ' only splits on the FIRST separator (after the number)
    assert tracks["Speak to Me - Breathe"]["artist"] == "Pink Floyd"
    assert tracks["Speak to Me - Breathe"]["album"] == "iSS.1"


def test_loose_file_and_titleonly(app_env):
    rel = _write("Assorted", ["Nina Simone - Feeling Good.mp3", "05 Untitled.mp3"])
    by = {t["title"]: t for t in library.album_tracks(rel)}
    assert by["Feeling Good"]["artist"] == "Nina Simone"   # no number, artist - title
    assert by["Untitled"]["artist"] == ""                  # number only, no folder artist
