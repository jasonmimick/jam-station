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
import re
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


# ── access keys: the dead-simple path (owner hands out a link + code) ───────────
#
# The owner creates a person and gets a LINK and a CODE to relay however they like (text,
# in person). Both are REUSABLE — tap the link or type the code, anytime, and you're in.
# No email round-trip, no signup. Losing one is fine (the other still works); losing both is
# fine (the owner rotates). This is the recovery story Jason asked for, built in.

def _member_slug(name: str) -> str:
    base = "".join(c if c.isalnum() else "-" for c in (name or "").lower()).strip("-") or "guest"
    base = base[:20]
    # internal identity for someone with no email — kept in the same `email` column so sessions
    # and favourites need no schema change. The '@key.jam' host marks it as not a real address.
    cand = f"{base}@key.jam"
    n = 2
    while member(cand):
        cand = f"{base}-{n}@key.jam"
        n += 1
    return cand


def create_key_member(name: str, contact: str = "", email: str = "", code: str = "") -> dict:
    """Owner adds a person. Approved on the spot (the owner adding you IS the approval), with a
    fresh reusable link + code. Returns the raw link and code ONCE — they're stored hashed and
    can't be shown again; to re-send, rotate."""
    name = (name or "").strip()[:60]
    ident = norm(email) if email and "@" in email else _member_slug(name)
    db.execute(
        "INSERT INTO members(email, name, role, status, contact, created_at, approved_at) "
        "VALUES(?,?,'member','approved',?,?,?) "
        "ON CONFLICT (email) DO UPDATE SET name=excluded.name, status='approved', "
        "contact=excluded.contact",
        (ident, name, contact.strip()[:120], _stamp(_now()), _stamp(_now())),
    )
    link, code = _issue_key(ident, code)
    return {"email": ident, "name": name, "link": link, "code": code}


def _issue_key(email: str, code: str = "") -> tuple[str, str]:
    """Mint a reusable token+code for a member; returns the raw pair (caller relays them).
    A caller-supplied code must already be normalized (see normalize_code) — code_login
    normalizes what people type, so anything stored differently could never match."""
    raw_token, code = secrets.token_urlsafe(18), (code or _code())
    db.execute("INSERT INTO access_keys(token_hash, code_hash, email, created_at) VALUES(?,?,?,?)",
               (_hash(raw_token), _hash(code), norm(email), _stamp(_now())))
    return f"{config.PUBLIC_URL}/k/{raw_token}", code


def normalize_code(raw: str) -> str:
    """A custom passcode, the way code_login will see it typed: uppercase, no spaces/dashes.
    Returns "" if what's left is too short to be accepted at sign-in (min 6)."""
    c = (raw or "").strip().upper().replace("-", "").replace(" ", "")
    return c if 6 <= len(c) <= 24 else ""


def send_key_email(name: str, email: str, link: str, code: str) -> bool:
    """The invite itself — everything a person needs to start listening, contributing, and
    finding their own radio, in one email."""
    first = (name or "").split()[0] if (name or "").strip() else "there"
    handle = handle_for(email)
    base = config.PUBLIC_URL
    return mail.send(
        email,
        "Your key to jam-station",
        f"Hi {first},\n"
        "\n"
        "You're in. jam-station is a private internet radio station — live show tapes\n"
        "(Grateful Dead, jazz, bluegrass, funk…) and a shelf of ripped CDs, streaming\n"
        "around the clock.\n"
        "\n"
        "SIGN IN — two ways, both yours for good:\n"
        "\n"
        f"  Your link:      {link}\n"
        f"  Your passcode:  {code}\n"
        "\n"
        f"Tap the link on any device — or go to {base} and type the passcode into\n"
        "the Sign in box. Phone, laptop, the car: it all works.\n"
        "\n"
        "YOUR OWN RADIO\n"
        "\n"
        f"  {base}/{handle}\n"
        "\n"
        "Your personal dial — bookmark it. It's the same station, addressed to you, and\n"
        "it's where your own stations will live as you add them.\n"
        "\n"
        "ON YOUR MAC — the Session desktop app\n"
        "\n"
        f"  {base}/session\n"
        "\n"
        "A native Mac player: the full dial, a screensaver that moves to the music, and\n"
        "lock-screen controls. Download it there — the page walks you through the one-time\n"
        "install.\n"
        "\n"
        "ADD YOUR OWN MUSIC\n"
        "\n"
        f"  {base}/guide\n"
        "\n"
        "Got non-commercial music worth sharing — your own recordings, live tapings,\n"
        "out-of-print tapes? The guide walks you through sending folders to the station,\n"
        "where each one becomes a station on the dial.\n"
        "\n"
        "Keep this email — the link and passcode don't expire.\n"
        "\n"
        "— jam-station\n",
    )


def rotate_key(email: str) -> dict | None:
    """Recovery: kill this member's old keys and issue a fresh link + code. What the owner
    hits when someone's lost their link and their code both."""
    email = norm(email)
    m = member(email)
    if not m:
        return None
    db.execute("UPDATE access_keys SET revoked_at=? WHERE email=? AND revoked_at=''",
               (_stamp(_now()), email))
    link, code = _issue_key(email)
    return {"email": email, "name": m["name"], "link": link, "code": code}


def key_login(raw_token: str) -> dict | None:
    """Tap the link. Reusable — succeeds every time until revoked."""
    rows = db.query("SELECT email FROM access_keys WHERE token_hash=? AND revoked_at=''",
                    (_hash(raw_token or ""),))
    if not rows:
        return None
    m = member(rows[0]["email"])
    if not m or m["status"] != "approved":
        return None
    return {"email": m["email"], "name": m["name"]}


def code_login(code: str) -> dict | None:
    """Type the code — the fallback when a link mangles in a text or won't open. Reusable."""
    code = (code or "").strip().upper().replace("-", "").replace(" ", "")
    if len(code) < 6:
        return None
    rows = db.query("SELECT email FROM access_keys WHERE code_hash=? AND revoked_at=''",
                    (_hash(code),))
    if not rows:
        return None
    m = member(rows[0]["email"])
    if not m or m["status"] != "approved":
        return None
    return {"email": m["email"], "name": m["name"]}


# ── passphrase: what YOU set once and never lose (email + passphrase) ───────────
#
# Key links are the zero-effort on-ramp; a passphrase is the thing that never expires and can't
# be lost in a text. Anyone signed in can set one, then sign in with email + passphrase forever.
# The owner sets one so he's never locked out again. Hashed with PBKDF2 (200k rounds, per-user
# salt) — a real password hash, not the light token hash used for links.

_PBKDF_ROUNDS = 200_000


def _pass_hash(passphrase: str, salt: str) -> str:
    return hashlib.pbkdf2_hmac(
        "sha256", passphrase.encode(), (config.AUTH_SECRET + salt).encode(), _PBKDF_ROUNDS
    ).hex()


def set_passphrase(email: str, passphrase: str) -> dict:
    passphrase = (passphrase or "").strip()
    if len(passphrase) < 6:
        return {"error": "Use at least 6 characters."}
    email = norm(email)
    if not member(email):
        return {"error": "no such member"}
    salt = secrets.token_hex(16)
    db.execute("UPDATE members SET pass_hash=?, pass_salt=? WHERE email=?",
               (_pass_hash(passphrase, salt), salt, email))
    return {"ok": True}


def passphrase_login(email: str, passphrase: str) -> dict | None:
    email = norm(email)
    m = member(email)
    if not m or m["status"] != "approved" or not m.get("pass_hash"):
        return None
    if not hmac.compare_digest(m["pass_hash"], _pass_hash(passphrase or "", m["pass_salt"])):
        return None
    return {"email": m["email"], "name": m["name"]}


def has_passphrase(email: str) -> bool:
    m = member(email)
    return bool(m and m.get("pass_hash"))


def passphrase_login_any(passphrase: str) -> dict | None:
    """Sign in with JUST a passphrase — no email. Find the approved member whose passphrase
    matches. This is the 'just type your word' convenience for a small trusted circle; the cost
    is that a known/shared passphrase logs in as that person, which is fine at family scale
    (and passphrases are never displayed and stored hashed). O(members) PBKDF2, tiny N."""
    passphrase = (passphrase or "").strip()
    if len(passphrase) < 6:
        return None
    for m in db.query("SELECT email, name, pass_hash, pass_salt FROM members "
                      "WHERE status='approved' AND pass_hash<>''"):
        if hmac.compare_digest(m["pass_hash"], _pass_hash(passphrase, m["pass_salt"])):
            return {"email": m["email"], "name": m["name"]}
    return None


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
    # SLIDING SESSION: every visit pushes expiry back out to the full window. So anyone who
    # listens even once a month never gets logged out — "tap once, listen forever." Expiry
    # only culls the genuinely dormant. (There's no security reason a radio expires an active
    # session; revocation is server-side and immediate regardless.)
    now = _now()
    db.execute("UPDATE sessions SET last_seen=?, expires_at=? WHERE id_hash=?",
               (_stamp(now), _stamp(now + timedelta(days=config.SESSION_DAYS)), _hash(raw)))
    return {"email": m["email"], "name": m["name"], "role": m["role"]}


def end_session(raw: str | None) -> None:
    if raw:
        db.execute("DELETE FROM sessions WHERE id_hash=?", (_hash(raw),))


def revoke(email: str) -> None:
    """Owner slams the door. Status, every live session, AND every access key — so a revoked
    person's link and code stop working too, not just their current session."""
    email = norm(email)
    db.execute("UPDATE members SET status='revoked' WHERE email=?", (email,))
    db.execute("DELETE FROM sessions WHERE email=?", (email,))
    db.execute("UPDATE access_keys SET revoked_at=? WHERE email=? AND revoked_at=''",
               (_stamp(_now()), email))


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


# ── personal handles: the URL-safe name a member's radio lives at ────────────────
# Derived from the email's local part (before @), slugified. jmimick+dad@gmail.com ->
# "jmimick-dad". Not stored — computed, so there's no migration and no second source of
# truth. Collisions (two locals slugging the same) resolve to the first approved member.

def handle_for(email: str) -> str:
    # the email local part, kept readable — jmimick+dad@gmail.com -> "jmimick+dad".
    # Only strip characters that can't live in a URL path segment.
    local = norm(email).split("@", 1)[0]
    return re.sub(r"[^a-z0-9._+-]", "", local)[:48]


def member_by_handle(handle: str) -> dict | None:
    h = re.sub(r"[^a-z0-9._+-]", "", (handle or "").lower())[:48]
    if not h:
        return None
    for m in db.query("SELECT * FROM members WHERE status='approved' ORDER BY created_at"):
        if handle_for(m["email"]) == h:
            return m
    return None
