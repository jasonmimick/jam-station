import os

from app import channels, config, db


def test_seed_channels(app_env):
    slugs = {c["slug"] for c in channels.list_channels()}
    assert {"dead77", "jam", "fusion", "latenight-jazz"} <= slugs


def test_next_track_tops_up_and_annotates(app_env):
    uri = channels.next_track("dead77")
    assert uri.startswith("annotate:")
    assert 'artist="Grateful Dead"' in uri
    assert uri.endswith(".mp3")
    np = channels.get_nowplaying("dead77")
    assert np["title"] in ("New Minglewood Blues", "Loser")


def test_next_track_marks_served_and_advances(app_env):
    first = channels.next_track("dead77")
    second = channels.next_track("dead77")
    assert first != second


def test_library_channel(app_env):
    folder = os.path.join(config.MUSIC_DIR, "fusion")
    os.makedirs(folder, exist_ok=True)
    with open(os.path.join(folder, "Weather Report - Birdland.mp3"), "wb") as f:
        f.write(b"\xff\xfb" + b"0" * 32)
    uri = channels.next_track("fusion")
    assert 'title="Birdland"' in uri
    assert 'artist="Weather Report"' in uri


def test_empty_library_returns_empty(app_env):
    assert channels.next_track("fusion") == ""


def test_enqueue_show_clear(app_env):
    channels.next_track("dead77")  # populate + serve one
    n = channels.enqueue_show("dead77", "gd1977-05-08.sbd.hicks.4982", clear=True)
    assert n == 2
    status = channels.queue_status("dead77")
    assert status["unserved"] == 2


def test_create_channel_and_history(app_env):
    ch = channels.create_channel("spring77", "Spring '77", "test",
                                 "archive", {"collections": ["GratefulDead"]})
    assert ch["slug"] == "spring77"
    channels.next_track("spring77")
    rows = db.query("SELECT * FROM history WHERE channel='spring77'")
    assert len(rows) == 1
