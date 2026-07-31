"""Parse E*TRADE 'G&L Expanded' XLSX (authoritative lot-level SALE records).

Each 'Sell' row = one sold lot: which acquisition lot (Date Acquired), quantity,
per-share FMV (Adjusted Cost Basis Per Share), USD proceeds, date sold, and E*TRADE's
US gain/term. This is the specific-identification data for Schedule CG.

We use: vest date + qty + FMV (cost basis, USD) + proceeds (USD) + sold date.
We IGNORE E*TRADE's Short/Long (US 1-year rule) and re-classify per India's 24-month rule,
and convert to INR ourselves (cost at Adobe vest rate per Sec 49(2AA); proceeds at SBI TTBR).
Files are per US CALENDAR year; a single Indian FY can span two files.
"""
from __future__ import annotations

import glob
from pathlib import Path
from typing import Any

import openpyxl

from itr_auto.workspace import sources_dir
GL_DIR = sources_dir() / "etrade" / "gains_losses"

C = {"record": 0, "plan": 2, "qty": 3, "acquired": 4, "adj_cost_basis_usd": 10,
     "fmv_per_share": 11, "sold": 12, "proceeds_usd": 13, "gain_usd": 16,
     "adj_gain_usd": 18, "us_status": 20, "grant": 39}


def _iso(v: Any) -> str | None:
    if v is None:
        return None
    s = str(v).strip()
    if " " in s:                      # datetime cell
        s = s.split(" ")[0]
    if "/" in s:                      # MM/DD/YYYY
        m, d, y = s.split("/")
        return f"{y}-{m.zfill(2)}-{d.zfill(2)}"
    if "-" in s and len(s) == 10:     # already ISO
        return s
    return None


def indian_fy(iso_date: str) -> str:
    y, m, _ = (int(x) for x in iso_date.split("-"))
    start = y if m >= 4 else y - 1
    return f"{start}-{str(start + 1)[2:]}"


def parse_file(path: str | Path) -> list[dict[str, Any]]:
    ws = openpyxl.load_workbook(path, data_only=True).active
    out = []
    for row in ws.iter_rows(min_row=2, values_only=True):
        if not row or row[C["record"]] != "Sell":
            continue
        sold = _iso(row[C["sold"]])
        acquired = _iso(row[C["acquired"]])
        plan = "RSU" if str(row[C["plan"]]).strip() in ("RS", "RSU") else "ESPP"
        out.append({
            "instrument": plan,
            "vest_date": acquired,
            "sold_date": sold,
            "fy_sold": indian_fy(sold) if sold else None,
            "qty": float(row[C["qty"]]),
            "fmv_usd": float(row[C["fmv_per_share"]]),          # = adjusted cost basis / share
            "cost_basis_usd": float(row[C["adj_cost_basis_usd"]]),
            "proceeds_usd": float(row[C["proceeds_usd"]]),
            "us_gain_usd": float(row[C["adj_gain_usd"]]),
            "us_status": str(row[C["us_status"]]).strip(),      # US Short/Long - NOT used for India
            "source": str(Path(path).name),
        })
    return out


def parse_all(gl_dir: str | Path = GL_DIR) -> list[dict[str, Any]]:
    out = []
    for f in sorted(glob.glob(str(Path(gl_dir) / "*.xlsx"))):
        out.extend(parse_file(f))
    return out


if __name__ == "__main__":
    import collections
    sales = parse_all()
    print(f"parsed {len(sales)} sold-lot rows\n")
    byfy = collections.defaultdict(lambda: [0.0, 0.0])
    for s in sales:
        byfy[s["fy_sold"]][0] += s["qty"]; byfy[s["fy_sold"]][1] += s["proceeds_usd"]
    print(f"{'Indian FY':10} {'qty':>10} {'proceeds USD':>14}")
    for fy in sorted(byfy):
        print(f"{fy:10} {byfy[fy][0]:10.3f} {byfy[fy][1]:14,.2f}")
