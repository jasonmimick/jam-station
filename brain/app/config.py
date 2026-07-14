import os

DATA_DIR = os.environ.get("DATA_DIR", "./data")
CACHE_DIR = os.environ.get("CACHE_DIR", "./cache")
MUSIC_DIR = os.environ.get("MUSIC_DIR", "./music")
DB_PATH = os.environ.get("DB_PATH", os.path.join(DATA_DIR, "channels.db"))

ANTHROPIC_MODEL = os.environ.get("ANTHROPIC_MODEL", "claude-sonnet-4-5")

LIQUIDSOAP_HOST = os.environ.get("LIQUIDSOAP_HOST", "liquidsoap")
LIQUIDSOAP_TELNET_PORT = int(os.environ.get("LIQUIDSOAP_TELNET_PORT", "1234"))

PREFETCH = os.environ.get("PREFETCH", "true").lower() in ("1", "true", "yes")
MIN_QUEUE = int(os.environ.get("MIN_QUEUE", "4"))

AUDIO_EXTENSIONS = (".mp3", ".flac", ".ogg", ".m4a", ".aac", ".opus", ".wav")

# Where icecast lives — the same origin the /stream proxy uses. This is the only
# honest source of "what is on air", because the queue runs ahead of the encoder.
ICECAST_ORIGIN = os.environ.get("ICECAST_ORIGIN", "http://jam-icecast:8000")

# slab injects this when `postgres = true` in slab.toml (shared slab-postgres,
# per-app database). Members and sessions are coming, and they need a real DB.
DATABASE_URL = os.environ.get("DATABASE_URL", "postgresql://slab:slab@localhost:20432/slab_jam_brain")

# ── auth ──────────────────────────────────────────────────────────────────────
OWNER_EMAIL   = os.environ.get("OWNER_EMAIL", "")
PUBLIC_URL    = os.environ.get("PUBLIC_URL", "https://jam-station.runslab.run")
AUTH_SECRET   = os.environ.get("AUTH_SECRET", "dev-secret-change-me")
SESSION_DAYS  = int(os.environ.get("SESSION_DAYS", "30"))
LOGIN_MINUTES = int(os.environ.get("LOGIN_MINUTES", "15"))
SESSION_COOKIE = "jam_session"

# Mail. SMTP is the portable interface — every provider speaks it, so swapping is three env
# vars and zero code. `console` is a REAL backend, not a stub: it prints the link and code,
# so the whole flow works with no credentials at all.
MAIL_BACKEND = os.environ.get("MAIL_BACKEND", "console")   # console | smtp
MAIL_FROM    = os.environ.get("MAIL_FROM", "jam-station <jam@runslab.run>")
SMTP_HOST    = os.environ.get("SMTP_HOST", "")
SMTP_PORT    = int(os.environ.get("SMTP_PORT", "587"))
SMTP_USER    = os.environ.get("SMTP_USER", "")
SMTP_PASS    = os.environ.get("SMTP_PASS", "")
