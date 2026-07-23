"""jam-contribd's two internal endpoints (docs/DESIGN-contributor-identity.md,
now superseded by the simpler per-member API-key path below) and the actual
/api/contribute upload flow: a member signs in, mints a personal token, and
that token — not a shared embedded secret — authenticates every upload."""
import zipfile
from io import BytesIO

from fastapi.testclient import TestClient

from app import auth, config, db
from app.main import app

INTERNAL = {"host": "jam-brain.localhost:8080"}
PUBLIC = {"host": "jam-station.runslab.run"}


def _zip_bytes(files: dict[str, bytes]) -> bytes:
    buf = BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        for name, content in files.items():
            zf.writestr(name, content)
    return buf.getvalue()


def test_internal_endpoints_hidden_from_the_public_tunnel(app_env):
    c = TestClient(app)
    assert c.get("/api/internal/member-by-email", params={"email": "x@example.com"},
                 headers=PUBLIC).status_code == 404
    assert c.post("/api/internal/contribution",
                  json={"email": "x@example.com", "slug": "s", "folder_name": "f"},
                  headers=PUBLIC).status_code == 404


def test_member_by_email_finds_an_approved_member(app_env):
    auth.create_key_member("Dad", email="dad@example.com")
    c = TestClient(app)
    r = c.get("/api/internal/member-by-email", params={"email": "dad@example.com"},
              headers=INTERNAL)
    assert r.status_code == 200
    body = r.json()
    assert body["email"] == "dad@example.com"
    assert body["handle"] == auth.handle_for("dad@example.com")


def test_member_by_email_404s_for_a_stranger(app_env):
    c = TestClient(app)
    r = c.get("/api/internal/member-by-email", params={"email": "nobody@example.com"},
              headers=INTERNAL)
    assert r.status_code == 404


def test_member_by_email_matches_a_tailscale_alias(app_env):
    # a member's jam-station email and their real Tailscale login aren't always the
    # same address (docs/DESIGN-contributor-identity.md) — the alias must resolve
    # to the SAME member record, primary email included in the response.
    auth.create_key_member("Dad", email="dad@example.com")
    db.execute("UPDATE members SET tailscale_email=? WHERE email=?",
               ("dad@icloud.com", "dad@example.com"))
    c = TestClient(app)
    r = c.get("/api/internal/member-by-email", params={"email": "dad@icloud.com"},
              headers=INTERNAL)
    assert r.status_code == 200
    assert r.json()["email"] == "dad@example.com"


def test_contribution_is_recorded(app_env):
    c = TestClient(app)
    r = c.post("/api/internal/contribution",
               json={"email": "dad@example.com", "slug": "inbox-guitar-fest",
                     "folder_name": "Guitar Fest"},
               headers=INTERNAL)
    assert r.status_code == 200
    rows = db.query("SELECT * FROM contributions WHERE email=?", ("dad@example.com",))
    assert any(row["slug"] == "inbox-guitar-fest" for row in rows)


# ── /api/contribute: the personal API-key path ───────────────────────────────

def test_contribute_token_requires_signin(app_env):
    c = TestClient(app)
    assert c.post("/api/contribute/token").status_code == 403


def test_contribute_token_mint_and_upload_end_to_end(app_env, tmp_path, monkeypatch):
    monkeypatch.setattr(config, "MUSIC_DIR", str(tmp_path))
    auth.create_key_member("Dad", email="dad2@example.com")
    c = TestClient(app)
    c.cookies.set(config.SESSION_COOKIE, auth.new_session("dad2@example.com"))

    token = c.post("/api/contribute/token").json()["token"]
    assert token

    zip_data = _zip_bytes({"track1.mp3": b"not really audio, just testing"})
    r = c.post("/api/contribute", data={"folder": "Guitar Fest 2007"},
               files={"file": ("upload.zip", zip_data, "application/zip")},
               headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 200
    body = r.json()
    assert body["slug"] == "inbox-guitar-fest-2007"

    landed = tmp_path / "inbox" / "Guitar Fest 2007" / "track1.mp3"
    assert landed.read_bytes() == b"not really audio, just testing"

    from app import channels
    ch = channels.get_channel("inbox-guitar-fest-2007")
    assert ch and ch["source"] == "library"

    rows = db.query("SELECT * FROM contributions WHERE email=?", ("dad2@example.com",))
    assert any(row["slug"] == "inbox-guitar-fest-2007" for row in rows)


def test_contribute_rejects_a_bad_token(app_env, tmp_path, monkeypatch):
    monkeypatch.setattr(config, "MUSIC_DIR", str(tmp_path))
    c = TestClient(app)
    r = c.post("/api/contribute", data={"folder": "x"},
               files={"file": ("upload.zip", _zip_bytes({"a.mp3": b"x"}), "application/zip")},
               headers={"Authorization": "Bearer not-a-real-token"})
    assert r.status_code == 403


def test_minting_a_new_token_revokes_the_old_one(app_env, tmp_path, monkeypatch):
    monkeypatch.setattr(config, "MUSIC_DIR", str(tmp_path))
    auth.create_key_member("Dad", email="dad3@example.com")
    c = TestClient(app)
    c.cookies.set(config.SESSION_COOKIE, auth.new_session("dad3@example.com"))

    old_token = c.post("/api/contribute/token").json()["token"]
    new_token = c.post("/api/contribute/token").json()["token"]
    assert old_token != new_token

    zip_data = _zip_bytes({"a.mp3": b"x"})
    old_r = c.post("/api/contribute", data={"folder": "Old"},
                   files={"file": ("u.zip", zip_data, "application/zip")},
                   headers={"Authorization": f"Bearer {old_token}"})
    assert old_r.status_code == 403

    new_r = c.post("/api/contribute", data={"folder": "New"},
                   files={"file": ("u.zip", zip_data, "application/zip")},
                   headers={"Authorization": f"Bearer {new_token}"})
    assert new_r.status_code == 200
