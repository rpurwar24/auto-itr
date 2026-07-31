"""Run the generator for the workspace named by $ITR_WORKSPACE and print a JSON result.

Invoked as a SUBPROCESS by the web server (never imported in-process): the generator and
parsers freeze their paths at import time from $ITR_WORKSPACE, so a fresh process per run is
what makes per-user path resolution correct (and isolates a bad-input crash from the server).

stdout: a single JSON line {summary, errors, output} on success.
Any parse/compute failure exits non-zero with the traceback on stderr.
"""
from __future__ import annotations

import json

from itr_auto.generate import build, OUT
from itr_auto.schema_tools import validate


def main() -> None:
    itr, summary = build()
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(itr, indent=2, ensure_ascii=False))
    errors = validate(itr["ITR"]["ITR2"])
    print(json.dumps({"summary": summary, "errors": errors, "output": str(OUT)}))


if __name__ == "__main__":
    main()
