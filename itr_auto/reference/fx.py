"""USD->INR conversion for ITR (Rule 115) with pluggable rate sources.

Rule 115 (Income-tax Rules): the value in rupees of income in foreign currency uses
the SBI Telegraphic-Transfer BUYING rate (TTBR) on the "specified date". For capital
gains the specified date is the LAST DAY OF THE MONTH IMMEDIATELY PRECEDING the month
in which the capital asset is transferred.

Why pluggable sources:
  - The already-FILED returns were computed from stocks_computation.numbers, which used
    the taxpayer's own rates (exchangerates.org.uk), NOT SBI TTBR. To reproduce/validate
    those historical INR values we replay with NumbersRateSource.
  - The going-forward return uses SbiTtbrSource (Rule 115) - the user's chosen standard.
The engine (qty x price x rate) is identical; only the rate source changes.
"""
from __future__ import annotations

import calendar
import csv
import datetime as dt
from pathlib import Path
from typing import Protocol

REPO = Path(__file__).resolve().parents[2]
SBI_CSV = REPO / "reference" / "fx" / "sbi_ttbr_monthly.csv"


def _as_date(d: str | dt.date) -> dt.date:
    return d if isinstance(d, dt.date) else dt.date.fromisoformat(d)


def month_end(year: int, month: int) -> dt.date:
    return dt.date(year, month, calendar.monthrange(year, month)[1])


def preceding_month_end(d: str | dt.date) -> dt.date:
    """Last day of the month immediately preceding d's month (the Rule 115 date for CG)."""
    d = _as_date(d)
    first_of_month = d.replace(day=1)
    return first_of_month - dt.timedelta(days=1)


class RateSource(Protocol):
    """Returns TTBR (USD->INR) applicable on a given reference date, or raises KeyError."""
    def rate_on(self, ref_date: dt.date) -> float: ...


class SbiTtbrSource:
    """Month-keyed SBI TTBR from a CSV (columns: month=YYYY-MM, ttbr).

    A month's row holds the SBI TTBR as on that month's last working day, i.e. the value
    Rule 115 refers to when it says "last day of the [preceding] month".
    """
    def __init__(self, csv_path: str | Path = SBI_CSV):
        self.path = Path(csv_path)
        self.rates: dict[str, float] = {}
        if self.path.exists():
            with self.path.open() as fh:
                # skip blank lines and '#' comments before the CSV reader sees them
                lines = [ln for ln in fh if ln.strip() and not ln.lstrip().startswith("#")]
            for row in csv.DictReader(lines):
                month, ttbr = (row.get("month") or "").strip(), (row.get("ttbr") or "").strip()
                if not month or not ttbr:
                    continue
                try:
                    self.rates[month] = float(ttbr)
                except ValueError:
                    continue  # header remnants / stray text

    def rate_on(self, ref_date: dt.date) -> float:
        key = f"{ref_date.year:04d}-{ref_date.month:02d}"
        if key not in self.rates:
            raise KeyError(f"no SBI TTBR for {key} in {self.path.name} "
                           f"(populate data/fx/sbi_ttbr_monthly.csv)")
        return self.rates[key]


class SbiAutoSource:
    """Authoritative source: fetches SBI's own published TT-BUY card for the exact date
    (with weekend/holiday fallback to the last published working day) and caches it.
    Supersedes the hand-maintained monthly CSV.
    """
    def rate_on(self, ref_date: dt.date) -> float:
        from itr_auto.reference.sbi_fetch import ttbr_on
        rate, _resolved = ttbr_on(ref_date)
        return rate


class NumbersRateSource:
    """Replay source: the exact per-date rates the taxpayer used in .numbers.

    Built from the ledger's per-lot vest rates and the reference-price tables, so we can
    reproduce filed INR values and prove the engine independent of FX methodology.
    """
    def __init__(self, by_date: dict[str, float]):
        self.by_date = by_date

    def rate_on(self, ref_date: dt.date) -> float:
        key = ref_date.isoformat()
        if key not in self.by_date:
            raise KeyError(f"no .numbers rate recorded for {key}")
        return self.by_date[key]


class FxService:
    def __init__(self, source: RateSource):
        self.source = source

    def rate_for_sale(self, sale_date: str | dt.date) -> float:
        """Rule 115 rate for sale proceeds = TTBR on last day of preceding month."""
        return self.source.rate_on(preceding_month_end(sale_date))

    def convert_sale_proceeds(self, usd: float, sale_date: str | dt.date) -> float:
        return usd * self.rate_for_sale(sale_date)


if __name__ == "__main__":
    src = SbiTtbrSource()
    print(f"SBI TTBR months loaded: {len(src.rates)} (from {SBI_CSV})")
    for d in ["2025-09-18", "2025-10-20", "2026-01-26"]:
        ref = preceding_month_end(d)
        try:
            print(f"  sale {d} -> Rule115 ref {ref} -> TTBR {src.rate_on(ref)}")
        except KeyError as e:
            print(f"  sale {d} -> Rule115 ref {ref} -> {e}")
