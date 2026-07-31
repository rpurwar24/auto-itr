"""Build Schedule OS (Other Sources) + the foreign-tax-credit data (FSI / TR / Form 67).

OS income this year: foreign dividends (Vested, gross) + savings-bank interest + any domestic
dividend. Foreign dividends are taxed at the applicable (slab) rate. The US tax withheld on
them is claimed as Foreign Tax Credit under DTAA sec 90 (Schedule FSI + TR + Form 67).

Data gaps (parameters, default 0 - fill from AIS/bank): savings_interest, domestic_dividend.
"""
from __future__ import annotations

import datetime as dt
from typing import Any

from itr_auto.parsers.vested import dividend_detail, foreign_income_ftc
from itr_auto.profile import load as load_profile

# top marginal rate for this taxpayer (new regime 30% + 15% surcharge + 4% cess).
# used only to cap the FTC; foreign 25% < this, so full credit anyway.
MARGINAL_RATE = load_profile()["marginal_rate"]


def _rupees(x: float) -> int:
    return int(round(x))


def _dividend_daterange(divs: list[dict[str, Any]]) -> dict[str, int]:
    buckets = {k: 0.0 for k in ("Upto15Of6", "Upto15Of9", "Up16Of9To15Of12",
                                "Up16Of12To15Of3", "Up16Of3To31Of3")}
    for d in divs:
        iso = d["date"]
        dd = dt.date.fromisoformat(iso)
        md = (dd.month, dd.day)
        if md <= (3, 15) and dd.month <= 3:
            key = "Up16Of12To15Of3"
        elif md <= (3, 31) and dd.month == 3:
            key = "Up16Of3To31Of3"
        elif md <= (6, 15):
            key = "Upto15Of6"
        elif md <= (9, 15):
            key = "Upto15Of9"
        elif md <= (12, 15):
            key = "Up16Of9To15Of12"
        else:
            key = "Up16Of12To15Of3"
        buckets[key] += d["gross_inr"]
    return {k: _rupees(v) for k, v in buckets.items()}


def build_schedule_os(fy: str = "2025-26", savings_interest: float = 0.0,
                      domestic_dividend: float = 0.0,
                      term_deposit_interest: float = 0.0) -> dict[str, Any]:
    divs = dividend_detail(fy)
    foreign_div = sum(d["gross_inr"] for d in divs)
    dividend_gross = _rupees(foreign_div + domestic_dividend)
    savings = _rupees(savings_interest)
    term_dep = _rupees(term_deposit_interest)
    interest_gross = savings + term_dep
    total = dividend_gross + interest_gross

    return {
        "IncOthThanOwnRaceHorse": {
            "DividendGross": dividend_gross,
            "DividendOthThan22e": dividend_gross,
            "IntrstFrmSavingBank": savings,
            "InterestGross": interest_gross,
            "IntrstFrmTermDeposit": term_dep, "IntrstFrmIncmTaxRefund": 0, "IntrstFrmOthers": 0,
            "OthersGross": 0, "AnyOtherIncome": 0,
            "Deductions": {"Expenses": 0, "Depreciation": 0, "IntExp57": 0,
                           "DeductionUs57iia": 0, "UsrIntExp57": 0, "TotDeductions": 0},
            "GrossIncChrgblTaxAtAppRate": total,
            "IncChargeableSpecialRates": 0,
            "BalanceNoRaceHorse": total,
            "IncChrgblUs115BBE": 0,
        },
        "DividendIncUs115BBDA": {"DateRange": _dividend_daterange(divs)},
        "TotOthSrcNoRaceHorse": total,
        "IncChargeable": total,
        "_notes": {"foreign_dividend_inr": _rupees(foreign_div),
                   "domestic_dividend_inr": _rupees(domestic_dividend),
                   "savings_interest_inr": interest_gross,
                   "GAP": "savings_interest & domestic_dividend from AIS/bank (default 0)"},
    }


def compute_ftc(fy: str = "2025-26", marginal_rate: float = MARGINAL_RATE,
                tin: str = "<US TIN / passport>") -> dict[str, Any]:
    """Foreign Tax Credit (DTAA sec 90) for the Vested dividend -> FSI / TR / Form 67."""
    fi = foreign_income_ftc(fy)
    income = fi["dividend_income_inr"]
    tax_paid = fi["tax_paid_inr"]
    tax_payable_india = round(income * marginal_rate, 2)
    relief = round(min(tax_paid, tax_payable_india), 2)   # sec 90: lower of the two
    return {
        "country_code": "2", "tin": tin, "section": "90",
        "income_inr": _rupees(income), "tax_paid_outside_inr": _rupees(tax_paid),
        "tax_payable_india_inr": _rupees(tax_payable_india), "relief_inr": _rupees(relief),
        "head": "Other Sources (dividend)",
        "_note": "Form 67 must be filed online BEFORE the ITR. FSI/TR exact JSON keys to confirm "
                 "vs ITR-2 schema; TIN is a data gap.",
    }


if __name__ == "__main__":
    import json
    print("Schedule OS:", json.dumps(build_schedule_os(savings_interest=0, domestic_dividend=0), indent=2))
    print("FTC:", json.dumps(compute_ftc(), indent=2))
