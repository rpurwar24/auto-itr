"""Parse Zerodha Console P&L statements (sources/zerodha/) - domestic capital gains + holdings.

Two workbooks: equity_*.xlsx and mutual_funds_*.xlsx. Each has a P&L sheet with per-instrument
Realized P&L (sold) and Open positions (held). Feeds:
  - Schedule CG / 112A: realized gains on Indian equity & equity-MF
  - Schedule AL: market value of open holdings as on year-end

NOTE: this P&L sheet has NO buy/sell dates, so it can't split STCG vs LTCG. For the exact split
download Zerodha Console -> Reports -> **Tax P&L** (which classifies STCG/LTCG). Amounts here are
small (realized ~5,248), so tax impact is minor (<=~1,300 even if all short-term; nil if LTCG,
since equity LTCG up to 1.25L is exempt under 112A).
"""
from __future__ import annotations

import glob
import re
from pathlib import Path
from typing import Any

import openpyxl

from itr_auto.workspace import sources_dir
ZERODHA_DIR = sources_dir() / "zerodha"
_ISIN = re.compile(r"^IN[EF][A-Z0-9]{9}$")


def _rows(path: str) -> list[list[Any]]:
    ws = openpyxl.load_workbook(path, data_only=True).active
    return [[("" if c is None else c) for c in r] for r in ws.iter_rows(values_only=True)]


def _num(v: Any) -> float:
    try:
        return float(v)
    except (TypeError, ValueError):
        return 0.0


def _parse_pnl(path: str, kind: str) -> dict[str, Any]:
    rows = _rows(path)
    # column layout (0 is a blank spacer col): 1 Symbol, 2 ISIN, 3 Qty, 4 Buy, 5 Sell,
    # 6 Realized P&L, 11 Open Value, 12 Unrealized P&L
    realized, holdings = [], []
    for r in rows:
        isin = str(r[2]).strip() if len(r) > 2 else ""
        if not _ISIN.match(isin):
            continue
        rec = {"instrument": kind, "symbol": str(r[1]).strip(), "isin": isin,
               "qty_sold": _num(r[3]), "buy_value": _num(r[4]), "sell_value": _num(r[5]),
               "realized_pnl": _num(r[6]),
               "open_value": _num(r[11]) if len(r) > 11 else 0.0,
               "unrealized_pnl": _num(r[12]) if len(r) > 12 else 0.0}
        if abs(rec["realized_pnl"]) > 0.005 or rec["sell_value"] > 0:
            realized.append(rec)
        if rec["open_value"] > 0:
            holdings.append(rec)
    return {"realized": realized, "holdings": holdings}


def parse_zerodha() -> dict[str, Any]:
    eq = _parse_pnl(glob.glob(str(ZERODHA_DIR / "**" / "equity*.xlsx"), recursive=True)[0], "equity")
    mf = _parse_pnl(glob.glob(str(ZERODHA_DIR / "**" / "mutual*.xlsx"), recursive=True)[0], "mf")
    realized = eq["realized"] + mf["realized"]
    holdings = eq["holdings"] + mf["holdings"]
    holdings_value = round(sum(h["open_value"] + h["unrealized_pnl"] for h in holdings))
    return {
        "realized_cg": realized,
        "realized_total": round(sum(x["realized_pnl"] for x in realized), 2),
        "holdings_market_value": holdings_value,   # for Schedule AL (Indian shares/MF)
        "note": "equity-oriented; STCG/LTCG split needs Zerodha Tax P&L (no dates here)",
    }


if __name__ == "__main__":
    import json
    z = parse_zerodha()
    print(f"realized domestic CG total: {z['realized_total']}")
    for r in z["realized_cg"]:
        print(f"  {r['instrument']:6} {r['symbol'][:36]:36} sell {r['sell_value']:>10.0f} "
              f"gain {r['realized_pnl']:>9.2f}")
    print(f"\nIndian holdings market value (Schedule AL): {z['holdings_market_value']:,}")
