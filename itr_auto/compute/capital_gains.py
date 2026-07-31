"""Capital-gains engine for foreign (Adobe) shares - specific-identification.

A sale is matched to specific vest lots (the taxpayer's actual method, confirmed from
.numbers: 2021 lots were sold while older lots were held - NOT FIFO). Each matched
lot-portion is classified and gained independently.

Tax rules encoded (foreign / unlisted-equity treatment in India):
  - Holding period: LONG-term if held > 24 months, else SHORT-term.
  - Indexation: LTCG on transfers BEFORE 23-Jul-2024 uses indexed cost (CII);
    transfers on/after 23-Jul-2024 use plain cost (Finance Act 2024, 12.5% no indexation).
  - STCG: always plain cost.
Cost of a partially-sold lot is prorated: cost_basis x sold_qty / sellable_qty.

The engine is source-agnostic: it takes proceeds_inr + cost_inr already in rupees, so
back-tests can feed .numbers' own figures and the live path can feed
perquisite-cost + SBI-TTBR proceeds.
"""
from __future__ import annotations

import calendar
import datetime as dt
from dataclasses import dataclass

INDEXATION_ABOLISHED = dt.date(2024, 7, 23)  # transfers on/after: no indexation, 12.5%
LTCG_MONTHS = 24


def _as_date(d: str | dt.date) -> dt.date:
    return d if isinstance(d, dt.date) else dt.date.fromisoformat(d)


def add_months(d: dt.date, n: int) -> dt.date:
    m = d.month - 1 + n
    year = d.year + m // 12
    month = m % 12 + 1
    day = min(d.day, calendar.monthrange(year, month)[1])
    return dt.date(year, month, day)


def is_long_term(purchase: str | dt.date, sale: str | dt.date) -> bool:
    """Foreign/unlisted shares: long-term if held MORE than 24 months."""
    return _as_date(sale) > add_months(_as_date(purchase), LTCG_MONTHS)


def cii_fy(d: str | dt.date) -> str:
    """Indian financial year in CII-table form 'YYYY-YYYY'."""
    d = _as_date(d)
    start = d.year if d.month >= 4 else d.year - 1
    return f"{start}-{start + 1}"


@dataclass
class GainResult:
    term: str            # "LTCG" | "STCG"
    indexed: bool
    proceeds_inr: float
    cost_inr: float      # cost actually used (indexed if applicable)
    plain_cost_inr: float
    gain_inr: float


def compute_gain(proceeds_inr: float, plain_cost_inr: float,
                 purchase_date: str | dt.date, sale_date: str | dt.date,
                 cii: dict[str, float]) -> GainResult:
    sale = _as_date(sale_date)
    long_term = is_long_term(purchase_date, sale)
    term = "LTCG" if long_term else "STCG"
    use_indexation = long_term and sale < INDEXATION_ABOLISHED
    cost = plain_cost_inr
    if use_indexation:
        p_fy, s_fy = cii_fy(purchase_date), cii_fy(sale)
        if p_fy in cii and s_fy in cii:
            cost = plain_cost_inr * cii[s_fy] / cii[p_fy]
        else:
            raise KeyError(f"CII missing for {p_fy} or {s_fy}")
    return GainResult(term=term, indexed=use_indexation, proceeds_inr=proceeds_inr,
                      cost_inr=cost, plain_cost_inr=plain_cost_inr,
                      gain_inr=proceeds_inr - cost)


def prorated_cost(lot_cost_basis: float, sold_qty: float, sellable_qty: float) -> float:
    """Cost of the sold portion of a lot (lots are often only partly sold)."""
    if not sellable_qty:
        return 0.0
    return lot_cost_basis * sold_qty / sellable_qty
