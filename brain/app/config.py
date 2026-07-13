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
