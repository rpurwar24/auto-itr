"""Parse E*TRADE / Morgan Stanley trade confirmation PDFs (the SALE source).

Two layouts exist:
  - NEW (Morgan Stanley, 2024+): "Trade Date Settlement Date Quantity Price ..."
    with "Transaction Type: Sold" and "Net Amount $X". pypdf reads these cleanly.
  - OLD (E*TRADE Securities LLC, <=2023): a single SELL row. pypdf CANNOT extract its
    text (font encoding), so those few historical trades are supplied via _OLD_OVERRIDES
    (values read from the rendered PDFs; they are also already in .numbers).

Sales are matched to vest lots later (CG engine); this parser only reads the trades.
"""
from __future__ import annotations

import glob
import logging
import re
from pathlib import Path
from typing import Any

from pypdf import PdfReader

# old-format E*TRADE PDFs trigger noisy "Advanced encoding /NULL" warnings; we handle
# those via _OLD_OVERRIDES, so quiet pypdf's logger.
logging.getLogger("pypdf").setLevel(logging.ERROR)

from itr_auto.workspace import sources_dir
TRADE_DIR = sources_dir() / "etrade" / "trades"

# Old-format confirmations pypdf can't read (values from the rendered PDFs).
_OLD_OVERRIDES = {
    "TradeConfirmations_4075_010323.pdf": dict(
        trade_date="2023-01-03", qty=19.8191, price_usd=335.7511,
        principal_usd=6654.29, net_usd=6649.18),
    "TradeConfirmations_4075_073123.pdf": dict(
        trade_date="2023-07-31", qty=32.0, price_usd=550.01,
        principal_usd=17600.32, net_usd=17595.22),
}


def _money(s: str) -> float:
    return float(s.replace(",", ""))


def _iso_us(mdy: str) -> str:
    m, d, y = mdy.split("/")
    return f"{y}-{m.zfill(2)}-{d.zfill(2)}"


def parse_pdf(path: str | Path) -> dict[str, Any] | None:
    path = Path(path)
    name = path.name
    if name in _OLD_OVERRIDES:
        rec = dict(_OLD_OVERRIDES[name]); rec.update(symbol="ADBE", source=name, format="old")
        return rec

    text = re.sub(r"[ \t]+", " ", PdfReader(str(path)).pages[0].extract_text() or "")
    if "Sold" not in text and "SELL" not in text:
        return None
    m = re.search(r"(\d{2}/\d{2}/\d{4})\s+(\d{2}/\d{2}/\d{4})\s+([\d.]+)\s+([\d.]+)", text)
    net = re.search(r"Net Amount \$([\d,]+\.\d+)", text)
    principal = re.search(r"Principal \$([\d,]+\.\d+)", text)
    if not (m and net):
        return None
    return {
        "trade_date": _iso_us(m.group(1)),
        "settlement_date": _iso_us(m.group(2)),
        "qty": float(m.group(3)),
        "price_usd": float(m.group(4)),
        "principal_usd": _money(principal.group(1)) if principal else None,
        "net_usd": _money(net.group(1)),
        "symbol": "ADBE",
        "source": name,
        "format": "new",
    }


def parse_all(trade_dir: str | Path = TRADE_DIR) -> list[dict[str, Any]]:
    trades = []
    for f in sorted(glob.glob(str(Path(trade_dir) / "*.pdf"))):
        rec = parse_pdf(f)
        if rec:
            trades.append(rec)
    return trades


def indian_fy(iso_date: str) -> str:
    y, mth, _ = (int(x) for x in iso_date.split("-"))
    start = y if mth >= 4 else y - 1
    return f"{start}-{str(start + 1)[2:]}"


if __name__ == "__main__":
    trades = parse_all()
    print(f"parsed {len(trades)} sell confirmations\n")
    print(f"{'trade_date':11} {'FY':8} {'qty':>9} {'price$':>10} {'net$':>12}  file")
    tot = 0.0
    for t in sorted(trades, key=lambda x: x["trade_date"]):
        tot += t["qty"]
        print(f"{t['trade_date']:11} {indian_fy(t['trade_date']):8} {t['qty']:9.3f} "
              f"{t['price_usd']:10.4f} {t['net_usd']:12,.2f}  {t['source']}")
    print(f"\ntotal shares sold across all confirmations: {tot:.3f}")
