# Memory plugin

Local-only "memory" for your job search — the no-keys, no-network counterpart
to a hosted memory service. It never talks to the network and needs no API
key: everything lives in a plain JSONL file under `output/memory/` (already
gitignored, so it's never committed).

## What it does

- **export** — archives every row of `data/applications.md` (company, role,
  status, score, report link, notes) to `output/memory/history.jsonl`,
  append-only. Run it after evaluations so your history accumulates over time.
- **search** — recalls archived rows whose company/role/notes match a query,
  resolves each hit's original posting URL from its report's `**URL:**`
  header, and returns them the same way any other plugin search does — the
  engine writes matches to `data/pipeline.md` for you to re-evaluate.

## Usage

```bash
node plugins.mjs run memory export              # archive the current tracker
node plugins.mjs run memory search "acme"        # recall past rows matching "acme"
node plugins.mjs run memory export --dry-run     # preview without writing
```

Enable it first in `config/plugins.yml`:

```yaml
plugins:
  memory:
    enabled: true
```

## Boundaries

Same contract as every plugin (see `plugins/README.md`): `export` never
modifies `data/applications.md` (the tracker stays canonical), `search`
results only ever reach the pipeline through the engine's canonical writer,
and there is no auto-submit hook. This plugin additionally never makes a
network call — its only interaction with the outside world is your own
filesystem.
