"""Auto-fetch SBI TT-BUY (TTBR) USD->INR from SBI's published daily rate cards.

Source: https://sbi-ttr.s3.ap-south-1.amazonaws.com/<YYYY-MM-DD>.pdf  (SBI's own forex
card rate PDF). The first number after "UNITED STATES DOLLAR USD/INR" is the TT BUY rate.
This is authoritative (SBI's published card), so it replaces the hand-maintained monthly CSV
and removes the "verify vs sbi.co.in" caveat.

SBI publishes only on working days, so a requested date that is a weekend/holiday falls back
to the nearest PRIOR working day (which is exactly what Rule 115's "last day of the month"
resolves to in practice). Results cache to data/fx/sbi_daily_cache.json.
"""
from __future__ import annotations

import datetime as dt
import io
import json
import re
from pathlib import Path

import requests
from pypdf import PdfReader

REPO = Path(__file__).resolve().parents[2]
CACHE = REPO / "reference" / "fx" / "sbi_daily_cache.json"
_S3 = "https://sbi-ttr.s3.ap-south-1.amazonaws.com/{date}.pdf"
_UA = {"User-Agent": "Mozilla/5.0"}
_USD_RE = re.compile(r"UNITED STATES DOLLAR\s+USD/INR\s+([\d.]+)", re.I)


def _load_cache() -> dict:
    return json.loads(CACHE.read_text()) if CACHE.exists() else {}


def _save_cache(c: dict) -> None:
    CACHE.parent.mkdir(parents=True, exist_ok=True)
    CACHE.write_text(json.dumps(c, indent=2, sort_keys=True))


def _fetch_one(date: dt.date) -> float | None:
    """TT BUY for an exact date, or None if SBI didn't publish that day."""
    r = requests.get(_S3.format(date=date.isoformat()), timeout=30, headers=_UA)
    if r.status_code != 200:
        return None
    text = re.sub(r"[ \t]+", " ", PdfReader(io.BytesIO(r.content)).pages[0].extract_text() or "")
    m = _USD_RE.search(text)
    return float(m.group(1)) if m else None


def ttbr_on(date: str | dt.date, max_back: int = 6) -> tuple[float, str]:
    """SBI TT-BUY on `date`, falling back to the nearest prior working day.

    Returns (rate, actual_date_iso). Caches by requested date.
    """
    req = date if isinstance(date, dt.date) else dt.date.fromisoformat(date)
    cache = _load_cache()
    key = req.isoformat()
    if key in cache:
        c = cache[key]
        return c["ttbr"], c["resolved"]
    for back in range(max_back + 1):
        d = req - dt.timedelta(days=back)
        rate = _fetch_one(d)
        if rate is not None:
            cache[key] = {"ttbr": rate, "resolved": d.isoformat()}
            _save_cache(cache)
            return rate, d.isoformat()
    raise LookupError(f"no SBI rate found for {key} (tried back to {max_back} days)")


if __name__ == "__main__":
    for d in ["2025-08-31", "2025-09-30", "2025-12-31", "2025-02-13"]:
        rate, resolved = ttbr_on(d)
        note = "" if resolved == d else f"(fell back to working day {resolved})"
        print(f"  {d}: TTBR {rate}  {note}")
