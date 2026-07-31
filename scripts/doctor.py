"""Report the folder-local venv's Python + dependency versions (`make check`).

Reads requirements.txt, prints each package's installed version (or MISSING), and exits
non-zero if anything required is absent - so `make check` doubles as a health check.
"""
from __future__ import annotations

import re
import sys
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path

REQ = Path(__file__).resolve().parents[1] / "requirements.txt"


def _requirements() -> list[tuple[str, str | None]]:
    out = []
    for line in REQ.read_text().splitlines():
        line = line.split("#")[0].strip()
        if not line:
            continue
        m = re.match(r"([A-Za-z0-9_.\-]+)(?:\[[^\]]*\])?\s*==\s*([0-9][^\s;]*)", line)
        if m:
            out.append((m.group(1), m.group(2)))
    return out


def main() -> None:
    print(f"python : {sys.version.split()[0]}   ({sys.executable})")
    print(f"reqs   : {REQ}")
    print()
    missing = 0
    for name, pin in _requirements():
        try:
            v = version(name)
            note = "" if v == pin else f"  (requirements pins {pin})"
            print(f"  ✓ {name:18} {v}{note}")
        except PackageNotFoundError:
            print(f"  ✗ {name:18} MISSING")
            missing += 1
    if missing:
        print(f"\n{missing} package(s) missing - run 'make setup'.")
        sys.exit(1)
    print("\nall dependencies present.")


if __name__ == "__main__":
    main()
