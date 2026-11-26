"""Usage reports: who listened to what, and for how long (docs/DESIGN-usage-reports.md).

presence.py calls `record()` when a listening session ENDS — a /stream connection closes,
or an on-demand heartbeat stops or moves to another channel. One row per session in
`listens`. `report()` rolls them up for the Usage page in jam-listen's #/admin.

Writing must never break listening: every failure here is logged and swallowed.
"""
from __future__ import annotations

import logging
import time

from . import channels, db

log = logging.getLogger(__name__)

MIN_SECONDS = 30          # shorter = dial-surfing or a health probe (jam-watch), not listening
IDLE_HOURS_30D = 1.0      # a continuous channel under this in 30 days is a candidate for on-demand


def _ts(t: float) -> str:
    return time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime(t))


def record(channel: str, mode: str, email: str, client: str, started: float, seconds: float) -> None:
    if seconds < MIN_SECONDS or not channel:
        return
    try:
        db.execute(
            "INSERT INTO listens(channel, mode, email, client, started_at, seconds) "
            "VALUES (?,?,?,?,?,?)",
            (channel[:120], mode, email or "", (client or "")[:40], _ts(started), int(seconds)))
    except Exception:   # noqa: BLE001 — a usage row is never worth a broken stream
        log.exception("usage.record failed")


def report(days: int = 30) -> dict:
    days = max(1, min(int(days), 3650))
    since = _ts(time.time() - days * 86400)
    since30 = _ts(time.time() - 30 * 86400)
    rows = db.query(
        "SELECT channel, mode, email, client, substr(started_at,1,10) AS day, "
        "count(*) AS sessions, sum(seconds) AS seconds, max(started_at) AS last "
        "FROM listens WHERE started_at >= ? GROUP BY channel, mode, email, client, day",
        (since,))
    last30 = {r["channel"]: r["seconds"] for r in db.query(
        "SELECT channel, sum(seconds) AS seconds FROM listens WHERE started_at >= ? "
        "GROUP BY channel", (since30,))}
    ever = {r["channel"]: r["last"] for r in db.query(
        "SELECT channel, max(started_at) AS last FROM listens GROUP BY channel")}

    all_chans = {c["slug"]: c for c in channels.list_all_channels()}
    # always-on = has a live icecast mount: playable and not a per-listener genre mix
    # (same rule as /api/dial). Attic stations (spotlight, vault) are on but not streamed.
    continuous = {c["slug"] for c in channels.list_channels()
                  if c["playable"] and not (c.get("query") or {}).get("genre")}

    by_channel: dict[str, dict] = {}
    by_client: dict[str, float] = {}
    by_person: dict[str, float] = {}
    by_day: dict[str, float] = {}
    total = 0.0
    for r in rows:
        s = float(r["seconds"])
        total += s
        c = by_channel.setdefault(r["channel"], {"seconds": 0.0, "sessions": 0, "days": {},
                                                 "modes": {}})
        c["seconds"] += s
        c["sessions"] += r["sessions"]
        c["days"][r["day"]] = c["days"].get(r["day"], 0.0) + s
        c["modes"][r["mode"]] = c["modes"].get(r["mode"], 0.0) + s
        by_client[r["client"] or "unknown"] = by_client.get(r["client"] or "unknown", 0.0) + s
        who = r["email"] or "anonymous"
        by_person[who] = by_person.get(who, 0.0) + s
        by_day[r["day"]] = by_day.get(r["day"], 0.0) + s

    out_channels = []
    for slug in sorted(set(by_channel) | continuous):
        c = by_channel.get(slug, {"seconds": 0.0, "sessions": 0, "days": {}, "modes": {}})
        ch = all_chans.get(slug, {})
        h30 = (last30.get(slug) or 0) / 3600
        out_channels.append({
            "slug": slug,
            "name": ch.get("name", slug),
            "source": ch.get("source", ""),
            "continuous": slug in continuous,
            "hours": round(c["seconds"] / 3600, 2),
            "sessions": c["sessions"],
            "days": {d: round(v / 3600, 2) for d, v in sorted(c["days"].items())},
            "modes": {m: round(v / 3600, 2) for m, v in c["modes"].items()},
            "hours_30d": round(h30, 2),
            "last_played": ever.get(slug, ""),
            "idle": slug in continuous and h30 < IDLE_HOURS_30D,
        })
    out_channels.sort(key=lambda c: (-c["hours"], c["slug"]))

    def hrs(d: dict) -> list[dict]:
        return [{"name": k, "hours": round(v / 3600, 2)}
                for k, v in sorted(d.items(), key=lambda kv: -kv[1])]

    first = db.query("SELECT min(started_at) AS first FROM listens")
    return {
        "days": days,
        "since": since,
        "data_since": (first[0]["first"] if first else None) or "",
        "total_hours": round(total / 3600, 2),
        "idle_threshold_hours_30d": IDLE_HOURS_30D,
        "channels": out_channels,
        "clients": hrs(by_client),
        "people": hrs(by_person),
        "by_day": {d: round(v / 3600, 2) for d, v in sorted(by_day.items())},
    }
