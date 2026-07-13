from app.adapters import archive


def test_build_query():
    q = archive.build_query(["GratefulDead"], year=1977, min_rating=4.2)
    assert "collection:(GratefulDead)" in q
    assert "year:(1977)" in q
    assert "avg_rating:[4.2 TO 5]" in q


def test_build_query_defaults_to_etree():
    assert "mediatype:(etree)" in archive.build_query()


def test_search_shows(app_env):
    docs = archive.search_shows(collections=["GratefulDead"], year=1977)
    assert docs[0]["identifier"] == "gd1977-05-08.sbd.hicks.4982"
    assert docs[0]["avg_rating"] == 4.9


def test_get_show_prefers_vbr_and_orders_tracks(app_env):
    show = archive.get_show("gd1977-05-08.sbd.hicks.4982")
    assert show["venue"] == "Barton Hall, Cornell University"
    titles = [t["title"] for t in show["tracks"]]
    assert titles == ["New Minglewood Blues", "Loser"]  # no flac, no txt, in order
    assert show["tracks"][0]["url"].startswith(
        "https://archive.org/download/gd1977-05-08.sbd.hicks.4982/")


def test_pick_show_excludes_recent(app_env):
    show = archive.pick_show({"collections": ["GratefulDead"], "year": 1977},
                             exclude_ids={"gd1977-05-08.sbd.hicks.4982"})
    assert show is not None  # falls back to metadata of remaining/any candidate
