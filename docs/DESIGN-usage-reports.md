# DESIGN — usage reports

Status: BUILT 2026-11-25 (option 2).

- brain: `app/usage.py` (record + report), `listens` table, `presence.py` logs a session
  when it ends, `GET /api/admin/usage?days=` (owner only), `app/usage_backfill.py`.
- jam-listen: streams and heartbeats carry `?client=jam-listen` / `jam-listen-iphone`;
  on-demand plays send `/api/presence` every 30 s; `#/admin` has a Usage tab.
- stereotop (stereo-ideas `server.py`): `?client=stereotop` / `stereotop-web`.
- jam-watch: Monday 13:00 UTC push with the week's hours (`/weekly`, admin token).
- Not done: icecast `logarchive` (the config is baked into the libretime image, and the
  `listens` table makes the raw log unnecessary).

## Problem

12 channels stream all the time (liquidsoap → icecast, each one decoding and encoding
24/7 on the mini). We don't know who listens to what, so we can't decide which ones to
move to on-demand. Nothing durable records listening today:

- `presence.py` tracks open `/stream` connections and on-demand heartbeats, in memory,
  on purpose. It answers "who's on now", not "who listened last week".
- `history` records what each channel *played*, not whether anyone heard it.
- icecast's `access.log` has one line per listener connection, with seconds connected.
  But every listener arrives through the brain's proxy (user agent `python-httpx`,
  internal IP), so it can't say who or from which app. It also rotates at 10 MB
  (`logsize`, no `logarchive`), which is about 20 days, and then the old file is overwritten.

## First numbers (icecast log, 2026-11-06 → 11-25, incl. a 5-day outage 11-20 → 11-25)

| channel | connections | 5 min+ | hours |
|---|---|---|---|
| pat-and-john | 146 | 28 | 5.7 |
| disc-changer | 5 | 1 | 2.4 |
| fusion-live | 12 | 1 | 0.2 |
| jam | 18 | 1 | 0.2 |
| bluegrass | 19 | 0 | 0.1 |
| umphreys, radio100, inbox-collection-2, newgrass, ragtime, ambient, ocean | 2–12 each | 0 | ~0 |

~8.6 hours of radio in 2 weeks, two thirds of it on one channel. Most other "plays" are
seconds long, which looks like tuning through the dial.

## Options

1. **Parse icecast logs on a schedule.** No brain changes. But it can't see who or which
   app, and it can't see on-demand listening at all (Archive MP3s, shelf/vault mixes are
   played by the browser, not icecast).
2. **A `listens` table in the brain (recommended).** Write one row when a listening
   session ends: radio, when the `/stream` connection closes (the place `presence.py`
   already hooks), and on-demand, when heartbeats stop. Columns: channel, mode
   (radio/ondemand), member email (blank = anonymous), client (jam-listen, iphone4,
   mobile, mac app, stereotop — from a `?client=` param or the user agent), started_at,
   seconds. Skip sessions under 30 s (dial-surfing and the `jam-watch` probe).
   presence stays in memory; this is a separate write-once log, one row per session.
3. **Loki queries in Grafana.** Already shipping logs, but only request lines (no
   durations), and Loki retention is short. Good for ops, poor for "last 3 months".

Tradeoff of 2: needs a brain deploy and a small change in each client (send
`?client=`). jam-listen visitors all ride one service session, so they show up as
"jam-listen", not per person — fine for this question (which channels get used).

## What the reports show

- **`#/admin` → Usage tab in jam-listen** (already token-gated): hours per channel for
  7 / 30 / 90 days, each with a sparkline. Continuous channels get a "candidate for
  on-demand" flag when they had < 1 h in 30 days. Split by client and by member.
- **Weekly ntfy summary** from `jam-watch` (Mondays): top channels, total hours, and
  the channels nobody played.
- Backfill from the two icecast log files so the page doesn't start empty.
- Turn on `logarchive` in icecast.xml so raw logs stop getting overwritten.

## Open questions

- The stereotop plays jam-station streams straight from `jam-station.runslab.run/stream/<slug>` (stereo-ideas `server.py`), so it is already in the counts above, as anonymous. It should send `?client=stereotop`.
- What counts as "in use" for trimming: 1 h / 30 days is a guess.
