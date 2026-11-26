"""One-off: load icecast access.log listener lines into `listens` (client 'icecast log').

    docker exec slab-jam-icecast cat /var/log/icecast/access.log.old /var/log/icecast/access.log \\
      | docker exec -i slab-jam-brain python -m app.usage_backfill

Icecast writes the line when the listener DISCONNECTS, with seconds connected as the last
field, so started = logged time - seconds. Every listener reaches icecast through the
brain's proxy, so there is no person or app here — only channel and duration. Only lines
that end before the first real `listens` row are loaded, so running it twice, or after
live logging started, never double-counts.
"""
from __future__ import annotations

import re
import sys
from datetime import datetime, timezone

from . import db, usage

LINE = re.compile(r'\[(\d+/\w+/\d+:\d+:\d+:\d+) ([+-]\d{4})\] "GET /([^ ?/]+)[^"]*" 200 \S+ '
                  r'"[^"]*" "([^"]*)" (\d+)\s*$')


def main() -> None:
    db.init()
    first = db.query("SELECT min(started_at) AS f FROM listens WHERE client <> 'icecast log'")
    cutoff = (first[0]["f"] if first else None) or "9999"
    have = {(r["channel"], r["started_at"]) for r in db.query(
        "SELECT channel, started_at FROM listens WHERE client = 'icecast log'")}
    rows = []
    for raw in sys.stdin.buffer:
        m = LINE.search(raw.decode("utf-8", "replace"))
        if not m:
            continue
        stamp, tz, mount, agent, secs = m.groups()
        secs = int(secs)
        if "liquidsoap" in agent.lower() or mount.endswith(".xsl") or secs < usage.MIN_SECONDS:
            continue
        end = datetime.strptime(f"{stamp} {tz}", "%d/%b/%Y:%H:%M:%S %z").astimezone(timezone.utc)
        start = usage._ts(end.timestamp() - secs)
        if start >= cutoff or (mount, start) in have:
            continue
        rows.append((mount, "radio", "", "icecast log", start, secs))
    if rows:
        db.executemany("INSERT INTO listens(channel, mode, email, client, started_at, seconds) "
                       "VALUES (?,?,?,?,?,?)", rows)
    print(f"loaded {len(rows)} sessions (cutoff {cutoff})")


if __name__ == "__main__":
    main()
