# auto-itr

A document-based helper for preparing an Indian **ITR-2** (salary + capital gains + foreign
assets) and producing the portal-ready offline-utility JSON. You drop in the documents your
providers already give you (Form 16, AIS, broker statements, bank certificates); it parses them,
computes capital gains / loss set-off / tax under the new regime, and assembles a schema-valid
ITR-2 JSON to import into the ITD offline Utility.

> Not affiliated with the Income Tax Department. A preparation aid, not tax advice - review with
> a professional before filing.

## Privacy model

The app is safe to share: **no personal data lives in this repo.** Each person's documents,
config, and output live in a **gitignored** workspace (`.users/<name>/`), and secrets (bank PDF
passwords) are encrypted at rest with a key kept outside the repo. Nothing identifying is in the
code - the built-in profile is a neutral placeholder; real employer/country details come from a
per-user `config/profile.json`.

## Quick start

```bash
make setup      # create the folder-local .venv + install deps (uses uv if present, else pip)
make check      # show Python + installed dependency versions (flags anything missing)
make run        # start the local web app (auto-reload) at http://127.0.0.1:8000
make test       # run the test suite
```

`make run`/`check`/`test` **auto-create the `.venv` on first use** if it's missing, so `make run`
alone is enough on a fresh clone. Everything is scoped to this folder's `.venv` - nothing global.

Then in the browser: create a person → fill personal details (or import last year's ITR JSON) →
upload the documents the checklist asks for → Generate → download the JSON.

CLI equivalent:

```bash
ITR_WORKSPACE=.users/<name> .venv/bin/python -m itr_auto.generate
```

## How it's organized

- `itr_auto/` - the engine: parsers, capital-gains + loss-set-off + tax compute, FX/price
  fetchers, schema-driven schedule builders, and `generate.py` (the assembler).
- `itr_auto/providers/` - one file per integration (portal, employer, bank, broker, custodian).
  Adding a new bank/broker is a single new file: declare its documents and, optionally, how to
  parse them into a normalized result. The registry auto-discovers it.
- `itr_auto/workspace.py` / `profile.py` - per-user data paths and taxpayer config.
- `app/` - the local FastAPI web app (checklist, upload, run, download).
- `config/*.example.json` - templates; copy into a workspace and fill in.

## Scope / limitations

- **Document upload, not live bank/broker APIs.** You provide the statements; nothing logs into
  your accounts.
- Parsers are written for specific providers (a common Indian salary + US-RSU/ESPP + Indian broker
  + bank set). A different provider needs a parser for its document format - that's the one-file
  provider addition above.
- Verify every number against your source documents before filing.
