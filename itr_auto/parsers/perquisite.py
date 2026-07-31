"""Parse Adobe ESOP "Stock Perquisites" statements (perquisites/YY_YY.html).

These are the AUTHORITATIVE source for vest lots (acquisitions). One HTML row per
grant per vest date. Sales are NOT here (see trade confirmations).

Column semantics (verified against Form 16 / .numbers, 2026-07-28):
  Quantity        = NET shares delivered to the account (the sellable qty)
  Equity WH (QTY) = shares withheld & sold to cover tax
  gross vested    = Quantity + Equity WH        <- cost-basis quantity
  FMV in USD      = per-share fair market value at vest (tax cost basis, RSU & ESPP)
The statement's own "Forex rates" are Adobe's; we do NOT use them for tax - the
statutory SBI TTBR (Rule 115) is applied later by the FX service.
"""
from __future__ import annotations

import glob
import html
import re
from pathlib import Path
from typing import Any

from itr_auto.workspace import sources_dir, workspace_root
PERQ_DIR = sources_dir() / "adobe" / "esop"

# 0-based column positions in the statement table
COL = {
    "plan": 0, "grant": 1, "grant_price_usd": 2, "net_qty": 3,
    "exercise_date": 4, "vest_date": 5, "fmv_usd": 6, "perq_usd": 7,
    "adobe_forex": 8, "perq_inr": 9, "wh_qty": 10, "form16_perq_inr": 15,
}


def _num(cell: str) -> float:
    s = re.sub(r"[^0-9.]", "", cell or "")
    return float(s) if re.search(r"\d", s or "") else 0.0


_MONTHS = {m: i + 1 for i, m in enumerate(
    ["jan", "feb", "mar", "apr", "may", "jun",
     "jul", "aug", "sep", "oct", "nov", "dec"])}


def _iso(raw: str) -> str | None:
    """Parse the many day-first formats Adobe uses into ISO 'YYYY-MM-DD'.

    Seen variants: 15-05-2018, 29/12/2017, 24-Oct-20, 24-01-22, 30-Jun-22.
    Always day-month-year order. Returns None if not a date.
    """
    parts = re.split(r"[-/ ]+", (raw or "").strip())
    if len(parts) != 3:
        return None
    d_s, m_s, y_s = parts
    if not (d_s.isdigit() and y_s.isdigit()):
        return None
    day = int(d_s)
    month = int(m_s) if m_s.isdigit() else _MONTHS.get(m_s[:3].lower())
    if month is None:
        return None
    year = int(y_s)
    if year < 100:
        year += 2000
    if not (1 <= day <= 31 and 1 <= month <= 12):
        return None
    return f"{year:04d}-{month:02d}-{day:02d}"


def indian_fy(iso_date: str) -> str:
    """Indian financial year label 'YYYY-YY' for an ISO date (Apr 1 - Mar 31)."""
    y, m, _ = (int(x) for x in iso_date.split("-"))
    start = y if m >= 4 else y - 1
    return f"{start}-{str(start + 1)[2:]}"


def _rows(path: Path) -> list[list[str]]:
    text = path.read_text(encoding="utf-8", errors="ignore")
    out = []
    for tr in re.findall(r"<tr[^>]*>(.*?)</tr>", text, re.S | re.I):
        cells = re.findall(r"<t[dh][^>]*>(.*?)</t[dh]>", tr, re.S | re.I)
        vals = [re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", c))).strip()
                for c in cells]
        out.append(vals)
    return out


def parse_file(path: str | Path) -> list[dict[str, Any]]:
    path = Path(path)
    source_fy = path.stem.replace("_", "-")  # "24_25" -> "24-25"
    lots: list[dict[str, Any]] = []
    for r in _rows(path):
        if len(r) <= COL["wh_qty"] or r[COL["plan"]] not in ("RSU", "ESPP"):
            continue
        vest = _iso(r[COL["vest_date"]])
        if vest is None:
            continue
        net = _num(r[COL["net_qty"]])
        wh = _num(r[COL["wh_qty"]])
        lots.append({
            "instrument": r[COL["plan"]],
            "grant": r[COL["grant"]],
            "vest_date": vest,
            "fy": indian_fy(vest),
            "source_file_fy": source_fy,
            "net_qty": net,
            "wh_qty": wh,
            "gross_qty": round(net + wh, 4),
            "fmv_usd": _num(r[COL["fmv_usd"]]),
            "grant_price_usd": _num(r[COL["grant_price_usd"]]),  # 0 for RSU, discounted price for ESPP
            "adobe_forex": _num(r[COL["adobe_forex"]]),
            "form16_perquisite_inr": _num(r[COL["form16_perq_inr"]]) if len(r) > COL["form16_perq_inr"] else 0.0,
            "source": str(path.relative_to(workspace_root())),
        })
    return lots


def parse_all(perq_dir: str | Path = PERQ_DIR) -> list[dict[str, Any]]:
    lots: list[dict[str, Any]] = []
    for f in sorted(glob.glob(str(Path(perq_dir) / "*.html"))):
        lots.extend(parse_file(f))
    return lots


if __name__ == "__main__":
    import collections
    lots = parse_all()
    by_fy = collections.defaultdict(lambda: [0.0, 0.0, 0.0, 0])
    for lot in lots:
        b = by_fy[lot["fy"]]
        b[0] += lot["gross_qty"]; b[1] += lot["net_qty"]
        b[2] += lot["wh_qty"]; b[3] += 1
    print(f"parsed {len(lots)} vest lines from {PERQ_DIR}")
    print(f"{'FY':9} | {'gross':>9} | {'net':>9} | {'wh':>7} | lines")
    for fy in sorted(by_fy):
        g, n, w, c = by_fy[fy]
        print(f"{fy:9} | {g:9.3f} | {n:9.3f} | {w:7.3f} | {c}")
