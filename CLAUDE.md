# CLAUDE.md

Read `AGENTS.md` first — it's the canonical guide (architecture, conventions,
commands, gotchas). Edit AGENTS.md, not this file, when guidance changes.

Quick reference:

```bash
cd brain && pytest        # must pass before any commit; network is mocked
liquidsoap --check liquidsoap/radio.liq   # after touching radio.liq
```

Claude-specific notes:

- The AI DJ in `brain/app/dj.py` uses the Anthropic Messages API with tool-calling;
  model comes from `ANTHROPIC_MODEL` (default `claude-sonnet-4-5`). If you change the
  TOOLS schema, keep inputs JSON-schema-valid and results serializable.
- The DJ's system prompt encodes real product constraints (Phish not on Archive,
  restart-liquidsoap-after-create-channel). Update the prompt when behavior changes.
- Personal-use project: never add audio extraction from subscription services.
