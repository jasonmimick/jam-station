# CLAUDE.md

Read `AGENTS.md` first — it's the canonical guide (architecture, conventions,
commands, gotchas). Edit AGENTS.md, not this file, when guidance changes.

Quick reference:

```bash
cd brain && pytest        # must pass before any commit; network mocked, DB isolated
                          # (needs a reachable Postgres — tests use <dbname>_test)
liquidsoap --check liquidsoap/radio.liq   # after touching radio.liq

# deploy: push, PULL ON THE MINI, then slab deploy (it builds from the mini's checkout)
git push origin main && ssh jason@jasons-mac-mini 'cd ~/business/jam-station && git pull --ff-only'
slab -N jasons-mac-mini deploy jam-brain
```

Claude-specific notes:

- The AI DJ in `brain/app/dj.py` uses the Anthropic Messages API with tool-calling;
  model comes from `ANTHROPIC_MODEL` (default `claude-sonnet-4-5`). If you change the
  TOOLS schema, keep inputs JSON-schema-valid and results serializable.
- The DJ's system prompt encodes real product constraints (Phish not on Archive, how
  channels come on air). Update the prompt when behavior changes.
- Personal-use project: never add audio extraction from subscription services.
