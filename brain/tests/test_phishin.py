from app import channels
from app.adapters import phishin


def test_search_shows_shape(app_env):
    docs = phishin.search_shows(sort="likes_count:desc")
    assert len(docs) == 2
    assert docs[0]["identifier"] == "1997-11-17"
    assert docs[0]["venue"] == "McNichols Arena"
    assert docs[0]["likes_count"] == 172


def test_search_shows_year_filter(app_env):
    docs = phishin.search_shows(year=1999)
    assert [d["identifier"] for d in docs] == ["1999-12-31"]


def test_get_show_skips_tracks_without_audio(app_env):
    show = phishin.get_show("1997-11-17")
    assert show["creator"] == "Phish"
    assert show["title"] == "Phish Live at McNichols Arena on 1997-11-17"
    assert [t["title"] for t in show["tracks"]] == ["Tweezer", "Reba"]
    assert show["tracks"][0]["url"].endswith(".mp3")


def test_pick_show_excludes_recent(app_env):
    show = phishin.pick_show({}, exclude_ids={"1999-12-31"})
    assert show["identifier"] == "1997-11-17"


def test_phish_seed_channel_plays(app_env):
    uri = channels.next_track("phish")
    assert uri.startswith("annotate:")
    assert 'artist="Phish"' in uri


def test_enqueue_phish_show_by_date(app_env):
    n = channels.enqueue_show("phish", "1997-11-17", clear=True)
    assert n == 2
    status = channels.queue_status("phish")
    assert status["unserved"] == 2
    assert status["upcoming"][0]["title"] == "Tweezer"
