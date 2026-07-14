"""Invite → approve → magic link + code. Email is the identity.

NO third-party identity provider. No Clerk, no OAuth, no passwords. Jason owns the whole
auth path and there is nothing to migrate off later.

THE FLOW
    ① he shares an invite link
    ② visitor requests access (email + name)          -> PENDING
    ③ HE gets an email and approves                   -> APPROVED
    ④ they get a MAGIC LINK *and* a CODE
    ⑤ session cookie, SESSION_DAYS
    ⑥ expiry -> re-verify by email. Approval is once; verification is routine.

WHY THE CODE EXISTS (Jason's idea, and it's the load-bearing one)
    A magic link signs in *whichever device opened the email* — usually the phone, when you
    wanted the laptop. The code redeems the SAME login attempt on ANY device. Two paths, one
    attempt.

⚠️  EMAIL CLIENTS PREFETCH LINKS. Outlook Safe Links, Gmail's proxy and corporate scanners
    issue a GET on every url in a message before a human sees it. So:

        NOTHING IN HERE ACTS ON A GET.

    The approve link and the magic link both open a CONFIRM PAGE; the action is a POST.
    Prefetchers don't POST. Without this, a scanner silently auto-approves strangers and
    burns magic links before they're clicked. And the code is the belt to that braces.

OTHER DELIBERATE CHOICES
    · Tokens and codes are stored HASHED. A database leak must not be a pile of working
      logins.
    · Sessions are SERVER-SIDE, not JWTs, because the entire point is that Jason can REVOKE
      someone. A token you cannot revoke is the wrong primitive here.
    · Codes use an unambiguous alphabet (no 0/O, no 1/I/L) — someone is typing this off a
      phone screen.
    · IDENTITY ENHANCES, IT NEVER GATES. Nobody logs in to listen to the radio.
"""
from __future__ import annotations

import hashlib
import hmac
import secrets
from datetime import datetime, timedelta, timezone

from . import config, db, mail

# No 0/O, no 1/I/L — a human is typing this from a phone screen.
_ALPHABET = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"
_TS = "%Y-%m-%d %H:%M:%S"


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _stamp(dt: datetime) -> str:
    return dt.strftime(_TS)


def _parse(s: str) -> datetime:
    return datetime.strptime(s, _TS).replace(tzinfo=timezone.utc)


def _hash(raw: str) -> str:
    """Hash a secret before it touches the database."""
    return hashlib.sha256((config.AUTH_SECRET + raw).encode()).hexdigest()


def _code() -> str:
    return "".join(secrets.choice(_ALPHABET) for _ in range(8))


def norm(email: str) -> str:
    return (email or "").strip().lower()


# ── members ────────────────────────────────────────────────────────────────────

def ensure_owner() -> None:
    """The owner is config, not a signup. He never has to approve himself."""
    email = norm(config.OWNER_EMAIL)
    if not email:
        return
    db.execute(
        "INSERT INTO members(email, name, role, status, approved_at) "
        "VALUES(?,?,'owner','approved',?) "
        "ON CONFLICT (email) DO UPDATE SET role='owner', status='approved'",
        (email, "Owner", _stamp(_now())),
    )


def member(email: str) -> dict | None:
    rows = db.query("SELECT * FROM members WHERE email=?", (norm(email),))
    return rows[0] if rows else None


def is_owner(email: str) -> bool:
    m = member(email)
    return bool(m and m["role"] == "owner")


# ── invites ────────────────────────────────────────────────────────────────────

def create_invite(label: str = "") -> str:
    """Reusable + revocable, so you can text one to the family group chat and kill it later."""
    raw = secrets.token_urlsafe(16)
    db.execute("INSERT INTO invites(token_hash, label, created_at) VALUES(?,?,?)",
               (_hash(raw), label, _stamp(_now())))
    return raw


def invite_ok(raw: str) -> bool:
    if not raw:
        return False
    rows = db.query("SELECT * FROM invites WHERE token_hash=? AND revoked_at=''", (_hash(raw),))
    return bool(rows)


# ── ② request access ───────────────────────────────────────────────────────────

def request_access(invite: str, email: str, name: str, note: str = "") -> dict:
    """A visitor asks to be let in. Requires a valid invite — otherwise /join is a public
    form that lets the whole internet flood the owner's inbox."""
    if not invite_ok(invite):
        return {"error": "That invite link isn't valid."}
    email = norm(email)
    if "@" not in email:
        return {"error": "That doesn't look like an email address."}

    existing = member(email)
    if existing and existing["status"] == "approved":
        return {"ok": True, "already": True}     # already in — just let them sign in

    db.execute(
        "INSERT INTO members(email, name, role, status, note, created_at) "
        "VALUES(?,?,'member','pending',?,?) "
        "ON CONFLICT (email) DO UPDATE SET name=excluded.name, note=excluded.note",
        (email, name.strip()[:60], note.strip()[:200], _stamp(_now())),
    )

    raw = secrets.token_urlsafe(24)
    db.execute(
        "INSERT INTO approvals(token_hash, email, expires_at) VALUES(?,?,?)",
        (_hash(raw), email, _stamp(_now() + timedelta(days=14))),
    )
    # NOTE the link is a GET that only SHOWS a confirm page. The approval is a POST.
    link = f"{config.PUBLIC_URL}/auth/approve?t={raw}"
    mail.send(
        config.OWNER_EMAIL,
        f"jam-station: {name or email} wants in",
        f"{name or email} <{email}> is asking for access to jam-station.\n"
        + (f'\nThey said: "{note}"\n' if note else "")
        + f"\nReview and approve:\n{link}\n\n"
        "(That link opens a page — it won't approve anything on its own.)\n",
    )
    return {"ok": True}


# ── ③ approve ──────────────────────────────────────────────────────────────────

def approval_for(raw: str) -> dict | None:
    """Look up an approval token WITHOUT consuming it — this is what the GET page uses."""
    rows = db.query("SELECT * FROM approvals WHERE token_hash=? AND used_at=''", (_hash(raw),))
    if not rows or _parse(rows[0]["expires_at"]) < _now():
        return None
    return rows[0]


def approve(raw: str) -> dict:
    """The POST. Approves the member and sends them their way in."""
    rec = approval_for(raw)
    if not rec:
        return {"error": "That approval link has expired or was already used."}
    email = rec["email"]
    db.execute("UPDATE approvals SET used_at=? WHERE token_hash=?", (_stamp(_now()), _hash(raw)))
    db.execute("UPDATE members SET status='approved', approved_at=? WHERE email=?",
               (_stamp(_now()), email))
    start_login(email)                        # they get their link + code immediately
    return {"ok": True, "email": email}


# ── ④/⑤ login: magic link + code ───────────────────────────────────────────────

def start_login(email: str) -> dict:
    """Send BOTH a magic link and a code. Approved members only — but say the same thing
    either way, so this can't be used to discover who's a member."""
    email = norm(email)
    m = member(email)
    if not m or m["status"] != "approved":
        return {"ok": True}                   # deliberately indistinguishable

    raw_token, code = secrets.token_urlsafe(24), _code()
    db.execute(
        "INSERT INTO login_attempts(email, token_hash, code_hash, expires_at) "
        "VALUES(?,?,?,?)",
        (email, _hash(raw_token), _hash(code),
         _stamp(_now() + timedelta(minutes=config.LOGIN_MINUTES))),
    )
    link = f"{config.PUBLIC_URL}/auth/signin?t={raw_token}"
    mail.send(
        email, "Your jam-station sign-in",
        f"Hi{(' ' + m['name']) if m['name'] else ''} — here are two ways in.\n\n"
        f"1) Open this on the device you want to listen on:\n   {link}\n\n"
        f"2) Or type this code into jam-station on ANY device:\n\n      {code}\n\n"
        f"Either one works. Both expire in {config.LOGIN_MINUTES} minutes.\n\n"
        "(Opening the link shows a page — you'll still have to press a button.)\n",
    )
    return {"ok": True}


def _attempt_by_token(raw: str) -> dict | None:
    rows = db.query(
        "SELECT * FROM login_attempts WHERE token_hash=? AND used_at='' ORDER BY id DESC LIMIT 1",
        (_hash(raw),))
    if not rows or _parse(rows[0]["expires_at"]) < _now():
        return None
    return rows[0]


def peek_token(raw: str) -> str | None:
    """Whose sign-in is this? Used by the confirm PAGE — does not consume the token."""
    a = _attempt_by_token(raw)
    return a["email"] if a else None


def redeem_token(raw: str) -> dict:
    a = _attempt_by_token(raw)
    if not a:
        return {"error": "That sign-in link has expired. Ask for a new one."}
    db.execute("UPDATE login_attempts SET used_at=? WHERE id=?", (_stamp(_now()), a["id"]))
    return {"ok": True, "email": a["email"]}


def redeem_code(email: str, code: str) -> dict:
    email, code = norm(email), (code or "").strip().upper().replace("-", "").replace(" ", "")
    rows = db.query(
        "SELECT * FROM login_attempts WHERE email=? AND used_at='' ORDER BY id DESC LIMIT 1",
        (email,))
    if not rows:
        return {"error": "No sign-in is pending for that address."}
    a = rows[0]
    if _parse(a["expires_at"]) < _now():
        return {"error": "That code has expired. Ask for a new one."}
    if a["attempts"] >= 5:
        return {"error": "Too many tries. Ask for a new code."}
    db.execute("UPDATE login_attempts SET attempts=attempts+1 WHERE id=?", (a["id"],))
    # constant-time — don't leak the code one character at a time
    if not hmac.compare_digest(a["code_hash"], _hash(code)):
        return {"error": "That code isn't right."}
    db.execute("UPDATE login_attempts SET used_at=? WHERE id=?", (_stamp(_now()), a["id"]))
    return {"ok": True, "email": email}


# ── sessions (server-side, so they can be revoked) ─────────────────────────────

def new_session(email: str, user_agent: str = "") -> str:
    raw = secrets.token_urlsafe(32)
    now = _now()
    db.execute(
        "INSERT INTO sessions(id_hash, email, created_at, expires_at, last_seen, user_agent) "
        "VALUES(?,?,?,?,?,?)",
        (_hash(raw), norm(email), _stamp(now),
         _stamp(now + timedelta(days=config.SESSION_DAYS)), _stamp(now), user_agent[:200]),
    )
    return raw


def whoami(raw: str | None) -> dict | None:
    """Resolve a session cookie to a member. Returns None for anonymous — which is a normal,
    supported state, not an error. Nobody logs in to listen to the radio."""
    if not raw:
        return None
    rows = db.query("SELECT * FROM sessions WHERE id_hash=?", (_hash(raw),))
    if not rows or _parse(rows[0]["expires_at"]) < _now():
        return None
    m = member(rows[0]["email"])
    if not m or m["status"] != "approved":     # revoked mid-session: the door shuts now
        return None
    db.execute("UPDATE sessions SET last_seen=? WHERE id_hash=?", (_stamp(_now()), _hash(raw)))
    return {"email": m["email"], "name": m["name"], "role": m["role"]}


def end_session(raw: str | None) -> None:
    if raw:
        db.execute("DELETE FROM sessions WHERE id_hash=?", (_hash(raw),))


def revoke(email: str) -> None:
    """Owner slams the door. Status AND every live session, immediately."""
    email = norm(email)
    db.execute("UPDATE members SET status='revoked' WHERE email=?", (email,))
    db.execute("DELETE FROM sessions WHERE email=?", (email,))


# ── favourites ────────────────────────────────────────────────────────────────

def favourites(email: str) -> list[dict]:
    return db.query(
        "SELECT title, artist, album, url, channel, added_at FROM favourites "
        "WHERE email=? ORDER BY added_at DESC", (norm(email),))


def merge_favourites(email: str, local: list[dict]) -> list[dict]:
    """MERGE, never overwrite.

    On first sign-in a person has likes in localStorage on their phone AND their laptop, and
    the two lists differ. If we overwrote, the very first thing this auth system would do is
    DELETE THEIR MUSIC. Union them, keyed by url.
    """
    email = norm(email)
    for t in local or []:
        url = (t.get("url") or "").strip()
        if not url:
            continue
        db.execute(
            "INSERT INTO favourites(email, url, title, artist, album, channel, added_at) "
            "VALUES(?,?,?,?,?,?,?) ON CONFLICT (email, url) DO NOTHING",
            (email, url, t.get("title", ""), t.get("artist", ""), t.get("album", ""),
             t.get("channel", ""), t.get("addedAt") or _stamp(_now())),
        )
    return favourites(email)


def add_favourite(email: str, t: dict) -> None:
    if not (t.get("url") or "").strip():
        return
    db.execute(
        "INSERT INTO favourites(email, url, title, artist, album, channel, added_at) "
        "VALUES(?,?,?,?,?,?,?) ON CONFLICT (email, url) DO NOTHING",
        (norm(email), t["url"], t.get("title", ""), t.get("artist", ""),
         t.get("album", ""), t.get("channel", ""), _stamp(_now())),
    )


def remove_favourite(email: str, url: str) -> None:
    db.execute("DELETE FROM favourites WHERE email=? AND url=?", (norm(email), url))
