"""Build Schedule FA (Table A3, foreign equity) for Adobe holdings, calendar-year basis.

Sources (all authoritative):
  - holdings   : perquisite statements (net_qty, FMV, Adobe vest rate) aggregated by vest date
  - sales      : E*TRADE G&L (qty sold per vest date), to reduce the running position
  - prices     : Yahoo (year peak + Dec-31 close)  -> itr_auto.reference.prices
  - fx         : SBI TT-BUY on peak date / Dec 31   -> SbiAutoSource

Per acquisition (vest) date held at any time in the calendar year:
  InitialValOfInvstmnt = held_qty x FMV x Adobe-vest-rate      (cost of acquisition, Sec 49(2AA))
  PeakBalanceDuringPeriod = held_in_year x peak_price x TTBR(peak date)
  ClosingBalance          = held_at_year_end x close_price x TTBR(Dec 31)
  TotGrossProceeds        = INR proceeds of shares sold during the year
Note: a lot only partly sold shows both a closing balance and proceeds.
"""
from __future__ import annotations

import collections
import datetime as dt
from typing import Any

from itr_auto.parsers.perquisite import parse_all as perq_all
from itr_auto.parsers.gain_loss import parse_all as gl_all
from itr_auto.parsers.vested import schedule_fa_holdings, custodial_account
from itr_auto.reference.prices import year_marks
from itr_auto.reference.fx import SbiAutoSource
from itr_auto.profile import load as load_profile

# foreign employer whose equity (RSU/ESPP) is held - from the active person's profile
ADOBE = load_profile()["fa_equity_entity"]


def _rupees(x: float) -> int:
    return int(round(x))


def _holdings_by_vest() -> dict[str, dict[str, float]]:
    """Aggregate authoritative net holdings by vest date (perquisite + Dec-2023 ESPP gap)."""
    h: dict[str, dict[str, float]] = {}
    for p in perq_all():
        d = p["vest_date"]
        rec = h.setdefault(d, {"net_qty": 0.0, "fmv_usd": p["fmv_usd"],
                               "adobe_forex": p["adobe_forex"]})
        rec["net_qty"] += p["net_qty"]
    # This taxpayer's perquisite statements are missing one Dec-2023 ESPP purchase; supplement it
    # from the .numbers oracle IF that (optional, local-only) source is available. A normal user
    # whose perquisite statements are complete doesn't need this and won't have numbers-parser.
    if "2023-12-29" not in h:
        try:
            from itr_auto.ledger.extract_numbers import extract
            for l in extract()["lots"]:
                if l["purchase_date"] == "2023-12-29" and l["instrument"] == "ESPP":
                    h["2023-12-29"] = {"net_qty": l["sellable_qty"],
                                       "fmv_usd": l["purchase_date_fmv_usd"],
                                       "adobe_forex": l["vest_conversion_rate"]}
        except Exception:  # noqa: BLE001 - numbers-parser / .numbers not present -> skip supplement
            pass
    return h


def _sales_by_vest() -> dict[str, list[dict[str, Any]]]:
    s: dict[str, list[dict[str, Any]]] = collections.defaultdict(list)
    for t in gl_all():
        s[t["vest_date"]].append(t)
    return s


def build_adobe_fa(year: int, marks: dict[str, Any] | None = None,
                   peak_rate: float | None = None, close_rate: float | None = None,
                   proceeds_rate: float | None = None) -> dict[str, Any]:
    """marks/rates default to live auto-fetch; pass overrides to back-test old years
    (SBI's S3 rate cards don't go back far)."""
    holdings = _holdings_by_vest()
    sales = _sales_by_vest()
    marks = marks or year_marks("ADBE", year)
    fx = SbiAutoSource()
    if peak_rate is None:
        peak_rate = fx.rate_on(dt.date.fromisoformat(marks["peak_date"]))
    if close_rate is None:
        close_rate = fx.rate_on(dt.date(year, 12, 31))
    jan1, dec31 = dt.date(year, 1, 1), dt.date(year, 12, 31)

    rows, totals = [], {"initial": 0, "peak": 0, "closing": 0, "proceeds": 0}
    for vest_date in sorted(holdings):
        if dt.date.fromisoformat(vest_date) > dec31:
            continue  # acquired after the FA year
        h = holdings[vest_date]
        lot_sales = sales.get(vest_date, [])
        sold_before = sum(t["qty"] for t in lot_sales
                          if dt.date.fromisoformat(t["sold_date"]) < jan1)
        sold_in_year = [t for t in lot_sales
                        if jan1 <= dt.date.fromisoformat(t["sold_date"]) <= dec31]
        held_in_year = h["net_qty"] - sold_before
        if held_in_year <= 1e-6:
            continue  # fully disposed before the FA year
        held_at_end = held_in_year - sum(t["qty"] for t in sold_in_year)

        initial = held_in_year * h["fmv_usd"] * h["adobe_forex"]
        peak = held_in_year * marks["peak_price"] * peak_rate
        closing = max(0.0, held_at_end) * marks["close_price"] * close_rate
        proceeds = sum(t["proceeds_usd"] * (proceeds_rate or
                                             fx.rate_on(dt.date.fromisoformat(t["sold_date"])))
                       for t in sold_in_year)

        rows.append({**ADOBE, "InterestAcquiringDate": vest_date,
                     "InitialValOfInvstmnt": _rupees(initial),
                     "PeakBalanceDuringPeriod": _rupees(peak),
                     "ClosingBalance": _rupees(closing),
                     "TotGrossAmtPaidCredited": 0,
                     "TotGrossProceeds": _rupees(proceeds)})
        totals["initial"] += _rupees(initial); totals["peak"] += _rupees(peak)
        totals["closing"] += _rupees(closing); totals["proceeds"] += _rupees(proceeds)

    return {"year": year, "peak_price": marks["peak_price"], "peak_date": marks["peak_date"],
            "peak_rate": peak_rate, "close_price": marks["close_price"], "close_rate": close_rate,
            "rows": rows, "totals": totals}


def _vested_a3_row(h: dict[str, Any]) -> dict[str, Any]:
    """Map a parsed Vested holding to the ITR Table A3 field names (values as Vested computed)."""
    return {"CountryName": "UNITED STATES OF AMERICA", "CountryCodeExcludingIndia": "2",
            "NameOfEntity": h["entity"], "AddressOfEntity": h["address"] or "USA",
            "ZipCode": h["zip"], "NatureOfEntity": h["nature"].upper(),
            "InterestAcquiringDate": h["acquired"],
            "InitialValOfInvstmnt": _rupees(h["initial_inr"]),
            "PeakBalanceDuringPeriod": _rupees(h["peak_inr"]),
            "ClosingBalance": _rupees(h["closing_inr"]),
            "TotGrossAmtPaidCredited": _rupees(h["gross_paid_inr"]),
            "TotGrossProceeds": _rupees(h["gross_proceeds_inr"])}


def build_schedule_fa(year: int = 2025, vested_fy: str = "2025-26",
                      include_vested: bool = True, **adobe_kw: Any) -> dict[str, Any]:
    """Full Schedule FA JSON: Adobe (computed) + Vested (parsed) Table A3, plus the
    Vested custodial account for Table A2. `adobe_kw` forwards marks/rate overrides."""
    adobe = build_adobe_fa(year, **adobe_kw)
    rows = list(adobe["rows"])
    account = None
    if include_vested:
        rows += [_vested_a3_row(h) for h in schedule_fa_holdings(vested_fy)]
        account = custodial_account(vested_fy)
    schedule_fa = {"DtlsForeignEquityDebtInterest": rows}
    return {"ScheduleFA": schedule_fa, "_custodial_account_A2": account,
            "_counts": {"adobe": len(adobe["rows"]),
                        "vested": len(rows) - len(adobe["rows"]), "total": len(rows)}}


if __name__ == "__main__":
    fa = build_adobe_fa(2025)
    print(f"ADBE peak ${fa['peak_price']} @{fa['peak_date']} rate {fa['peak_rate']} | "
          f"close ${fa['close_price']} rate {fa['close_rate']}")
    print(f"Adobe FA rows for CY{fa['year']}: {len(fa['rows'])}")
    print(f"{'acquired':11}{'initialINR':>12}{'peakINR':>12}{'closingINR':>12}{'proceedsINR':>12}")
    for r in fa["rows"]:
        print(f"{r['InterestAcquiringDate']:11}{r['InitialValOfInvstmnt']:12,}{r['PeakBalanceDuringPeriod']:12,}"
              f"{r['ClosingBalance']:12,}{r['TotGrossProceeds']:12,}")
    t = fa["totals"]
    print(f"{'TOTAL':11}{t['initial']:12,}{t['peak']:12,}{t['closing']:12,}{t['proceeds']:12,}")
