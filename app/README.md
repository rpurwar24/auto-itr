# ITR-2 Utility - local web app

A local, document-based UI on top of the `itr_auto` pipeline. One workspace per person; each
person's private documents/config/output live in a gitignored `.users/<name>/` folder, so the
app itself is safe to share on git.

## Run

```bash
.venv/bin/pip install -r requirements.txt
.venv/bin/python -m app.server        # http://127.0.0.1:8000
```

## Flow

1. **Who is this for?** - pick an existing person or create one (creates `.users/<name>/`).
2. **Personal details** - PAN / DOB / US-TIN, bank PDF passwords (+ to add more), and the few
   manual inputs. Or drop last year's ITR JSON to prefill PAN + DOB automatically.
3. **Required documents** - a checklist with ✓/✗ per slot. Upload a file and it is filed into
   the correct `sources/<provider>/<FY>/` folder with the right name automatically (multiple
   files allowed for banks, brokers, ESOP statements). No need to learn the naming convention.
4. **Generate** - runs the pipeline for that workspace, shows the tax summary + schema status,
   and offers the JSON for download (import into the ITD offline utility via Option 3).

## How it maps to the engine

- Paths resolve through `itr_auto/workspace.py` (per-user via `ITR_WORKSPACE`).
- Taxpayer constants (employer / TCS collector / foreign country / salary components) come from
  the workspace's `config/profile.json` (see `config/profile.example.json`), defaulting to the
  built-in profile.
- The document slots live in `itr_auto/checklist.py` (one source of truth for the UI + filing).
- Generation runs `app/run_pipeline.py` as a subprocess with `ITR_WORKSPACE` set, so paths bind
  to the right person and a bad input can't take down the server.

## Not yet done (next)

- Friendlier "missing/unreadable document X" messages instead of a raw traceback on failure.
- Encryption-at-rest for stored bank passwords (currently plaintext inside the gitignored
  workspace).
- Provider-plugin contract so a new bank/broker is a one-file parser addition.
