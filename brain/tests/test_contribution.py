"""jam-contribd's two internal endpoints — gated to internal-only calls, never the
public tunnel (docs/DESIGN-contributor-identity.md)."""
from fastapi.testclient import TestClient

from app import auth, db
from app.main import app

INTERNAL = {"host": "jam-brain.localhost:8080"}
PUBLIC = {"host": "jam-station.runslab.run"}


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
