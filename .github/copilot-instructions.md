# Copilot instructions for jam-station

Read `AGENTS.md` at the repo root — it's the canonical agent guide. In short:

- FastAPI backend in `brain/app/`; adapters in `brain/app/adapters/` are the extension
  point for new audio sources; `dj.py` holds the AI DJ tool schemas.
- Keep dependencies minimal (no ORM, no frontend framework, single-file web UI).
- `cd brain && pytest` must pass — tests mock archive.org via httpx.MockTransport;
  never add tests that hit the real network.
- Run `liquidsoap --check liquidsoap/radio.liq` after editing radio.liq (pinned 2.2.x).
- Personal-use radio: playlist-only integration for subscription services; never
  extract or rebroadcast their audio.
