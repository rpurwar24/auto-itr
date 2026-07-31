"""Parse the Zerodha Console **Tax P&L** report (sources/zerodha/<FY>/Tax P&L*.xlsx).

Unlike the plain P&L (parsers/zerodha.py, which has no dates -> can't split STCG/LTCG), this report
classifies each exit as Short/Long term. The "Mutual Funds" sheet gives the clean equity-oriented
split we need for the ITR:
  - Equity Short Term  -> STCG u/s 111A (20% special rate, post-23Jul24)
  - Equity Long Term   -> LTCG u/s 112A (12.5%; first Rs 1,25,000 aggregate is EXEMPT)
Equity (stocks) sections are empty this year. Amounts are small; this only adds ~Rs 770 of tax
(the 111A STCG); the 112A LTCG is under the 1.25L exemption -> nil.
"""
from __future__ import annotations

import glob
from pathlib import Path
from typing import Any

import openpyxl

from itr_auto.workspace import sources_dir
ZERODHA_DIR = sources_dir() / "zerodha"


def _find() -> str:
    hits = glob.glob(str(ZERODHA_DIR / "**" / "Tax P&L*.xlsx"), recursive=True)
    if not hits:
        raise FileNotFoundError("Zerodha Tax P&L report not found under sources/zerodha/")
    return sorted(hits)[-1]


def _section(rows: list, title: str) -> list[list]:
    """Rows of the detail table under a `title` header, until the next blank-separated block."""
    out, cap = [], False
    for r in rows:
        vals = [c for c in r if c not in (None, "")]
        if not vals:
            if cap and out:
                break
            continue
        head = str(vals[0]).strip()
        if head == title:
            cap = True
            continue
        if cap:
            if head == "Symbol":
                continue
            if head in ("Equity Short Term", "Equity Long Term") and out:
                break
            out.append(vals)          # filtered non-empty cells: [name, qty, buy, sell, pnl, ...]
    return out


def _agg(rows: list[list]) -> dict[str, float]:
    sale = cost = pnl = 0.0
    lots = []
    for r in rows:
        if len(r) >= 5 and isinstance(r[1], (int, float)):
            cost += float(r[2]); sale += float(r[3]); pnl += float(r[4])
            lots.append({"name": str(r[0]).strip(), "qty": float(r[1]),
                         "buy": float(r[2]), "sell": float(r[3]), "pnl": float(r[4])})
    return {"sale": round(sale, 2), "cost": round(cost, 2), "gain": round(pnl, 2), "lots": lots}


def parse_zerodha_taxpnl() -> dict[str, Any]:
    wb = openpyxl.load_workbook(_find(), data_only=True)
    rows = list(wb["Mutual Funds"].iter_rows(values_only=True))
    stcg = _agg(_section(rows, "Equity Short Term"))    # 111A
    ltcg = _agg(_section(rows, "Equity Long Term"))      # 112A
    return {
        "stcg_111A": stcg,          # equity-oriented MF, short term -> 20%
        "ltcg_112A": ltcg,          # equity-oriented MF, long term  -> 12.5%, 1.25L exempt
        "total_gain": round(stcg["gain"] + ltcg["gain"], 2),
    }


if __name__ == "__main__":
    import json
    print(json.dumps(parse_zerodha_taxpnl(), indent=2))
