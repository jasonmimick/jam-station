"""The mix adapter: one channel drawing from shelf folders, vault artists and named archive.org shows."""
import os

import httpx
import pytest

from app import channels, config, db
from app.adapters import archive, attic, library, mix

SHOW = {"identifier": "pmg1985-07-12", "title": "1985-07-12 Pier 84", "creator": "Pat Metheny Group",
        "tracks": [{"url": "https://archive.org/download/pmg1985-07-12/01.mp3", "title": "Phase Dance"},
                   {"url": "https://archive.org/download/pmg1985-07-12/02.mp3", "title": "Are You Going With Me"}]}


def _album(name: str, tracks: int) -> None:
    folder = os.path.join(config.MUSIC_DIR, "cds", name)
    os.makedirs(folder, exist_ok=True)
    for i in range(1, tracks + 1):
        open(os.path.join(folder, f"{i:02d} Song {i}.mp3"), "wb").close()


@pytest.fixture()
def fake_archive(monkeypatch):
    calls = []

    def get_show(ident):
        calls.append(ident)
        if ident == "broken":
            raise RuntimeError("archive.org is down")
        return dict(SHOW, identifier=ident)
    monkeypatch.setattr(archive, "get_show", get_show)
    return calls


def test_no_parts_means_no_tracks(app_env):
    assert mix.pick_tracks({}) == []
    assert mix.playable({}) is False


def test_library_part_plays_only_its_folders(app_env):
    _album("Pat Metheny - Bright Size Life", 3)
    _album("Somebody Else - Other", 3)
    picks = mix.pick_tracks({"parts": [{"source": "library", "folders": ["cds/Pat Metheny - Bright Size Life"]}]})
    assert len(picks) == 3
    assert all(t["album"] == "Bright Size Life" for t in picks)


def test_archive_part_returns_a_whole_show_with_its_id(app_env, fake_archive):
    picks = mix.pick_tracks({"parts": [{"source": "archive", "identifiers": ["pmg1985-07-12"]}]})
    assert [t["title"] for t in picks] == ["Phase Dance", "Are You Going With Me"]
    assert {t["show_id"] for t in picks} == {"pmg1985-07-12"}
    assert picks[0]["artist"] == "Pat Metheny Group" and picks[0]["album"] == "1985-07-12 Pier 84"


def test_recently_played_shows_are_avoided(app_env, fake_archive):
    cfg = {"parts": [{"source": "archive", "identifiers": ["a", "b"]}]}
    for _ in range(10):
        assert mix.pick_tracks(cfg, exclude={"a"})[0]["show_id"] == "b"
    # everything heard: repeats beat silence
    assert mix.pick_tracks(cfg, exclude={"a", "b"})


def test_a_show_that_will_not_load_does_not_silence_the_channel(app_env, fake_archive):
    cfg = {"parts": [{"source": "archive", "identifiers": ["broken", "good"]}]}
    for _ in range(10):
        assert mix.pick_tracks(cfg)[0]["show_id"] == "good"


def test_an_empty_part_is_skipped_for_one_that_has_music(app_env, fake_archive):
    cfg = {"parts": [{"source": "library", "folders": ["cds/Not Ripped Yet"], "weight": 100},
                     {"source": "archive", "identifiers": ["pmg1985-07-12"]}]}
    for _ in range(10):
        assert mix.pick_tracks(cfg)[0]["show_id"] == "pmg1985-07-12"


def test_weight_zero_parts_never_play(app_env, fake_archive):
    _album("Some - Album", 2)
    cfg = {"parts": [{"source": "library", "folders": ["cds/Some - Album"], "weight": 0},
                     {"source": "archive", "identifiers": ["x"]}]}
    for _ in range(10):
        assert mix.pick_tracks(cfg)[0]["show_id"] == "x"


def test_playable_needs_no_network_for_archive_parts(app_env, monkeypatch):
    monkeypatch.setattr(archive, "get_show", lambda i: pytest.fail("playable() must not fetch shows"))
    assert mix.playable({"parts": [{"source": "archive", "identifiers": ["x"]}]}) is True
    assert mix.playable({"parts": [{"source": "library", "folders": ["cds/Nothing"]}]}) is False


# ── in the channel machinery ─────────────────────────────────────────────────

def test_mix_is_private_and_streamable():
    assert "mix" in channels.PRIVATE_SOURCES and "mix" in channels.STREAMABLE_SOURCES


def test_pat_and_john_is_seeded_private_and_enqueues(app_env, fake_archive):
    channels.ensure_seeded()
    ch = channels.get_channel("pat-and-john")
    assert ch and ch["source"] == "mix"
    listed = {c["slug"]: c for c in channels.list_channels()}
    assert listed["pat-and-john"]["private"] is True and listed["pat-and-john"]["playable"] is True
    for _ in range(5):                                   # whichever part is picked, the queue fills
        assert channels.ensure_queue("pat-and-john") > 0 or db.query(
            "SELECT 1 FROM queue WHERE channel=?", ("pat-and-john",))
        db.execute("DELETE FROM queue WHERE channel=?", ("pat-and-john",))


def test_archive_shows_in_a_mix_link_to_archive_org_but_batches_do_not():
    assert channels.source_link("mix", "pmg1985-07-12") == "https://archive.org/details/pmg1985-07-12"
    assert channels.source_link("mix", "mix-pat-and-john-1700000000") == ""
