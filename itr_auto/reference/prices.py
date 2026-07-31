"""Fetch year-end / peak share prices for Schedule FA (auto, cached).

Source: Yahoo Finance chart JSON API (no key). Results cache to data/prices/<TICKER>_<YEAR>.json
so a filed year is reproducible and we don't refetch. For Schedule FA (US assets, calendar
year Jan-Dec) we need, per calendar year:
  - peak  : highest intraday price during the year (+ its date)
  - close : price on the last trading day (~31 Dec)
INR conversion (peak-date / year-end TTBR) is applied later via the FX service.
"""
from __future__ import annotations

import datetime as dt
import json
from pathlib import Path
from typing import Any

import requests

REPO = Path(__file__).resolve().parents[2]
CACHE_DIR = REPO / "reference" / "prices"
_UA = {"User-Agent": "Mozilla/5.0"}


def _fetch_yahoo(ticker: str, year: int) -> list[dict[str, Any]]:
    p1 = int(dt.datetime(year, 1, 1).timestamp())
    p2 = int(dt.datetime(year, 12, 31, 23, 59).timestamp())
    url = (f"https://query1.finance.yahoo.com/v8/finance/chart/{ticker}"
           f"?period1={p1}&period2={p2}&interval=1d")
    r = requests.get(url, timeout=30, headers=_UA)
    r.raise_for_status()
    res = r.json()["chart"]["result"][0]
    ts = res["timestamp"]
    q = res["indicators"]["quote"][0]
    days = []
    for t, c, h, lo, o in zip(ts, q["close"], q["high"], q["low"], q["open"]):
        if c is None:
            continue
        days.append({"date": dt.date.fromtimestamp(t).isoformat(),
                     "close": round(c, 4), "high": round(h, 4)})
    return days


def daily_series(ticker: str, year: int, refresh: bool = False) -> list[dict[str, Any]]:
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    cache = CACHE_DIR / f"{ticker}_{year}.json"
    if cache.exists() and not refresh:
        return json.loads(cache.read_text())
    days = _fetch_yahoo(ticker, year)
    cache.write_text(json.dumps(days, indent=2))
    return days


def year_marks(ticker: str, year: int, refresh: bool = False) -> dict[str, Any]:
    """Peak (max high + date) and year-end close for a calendar year."""
    days = daily_series(ticker, year, refresh=refresh)
    if not days:
        raise ValueError(f"no price data for {ticker} {year}")
    peak = max(days, key=lambda d: d["high"])
    close = days[-1]
    return {
        "ticker": ticker, "year": year,
        "peak_price": peak["high"], "peak_date": peak["date"],
        "close_price": close["close"], "close_date": close["date"],
        "trading_days": len(days),
    }


if __name__ == "__main__":
    print(json.dumps(year_marks("ADBE", 2025), indent=2))
