"""New-regime income-tax calculator (slab + special rates + surcharge + cess).

Slabs are year-parameterised so we can back-test against a filed year and then apply the
current year. Surcharge on special-rate income is capped at 15%; marginal relief is applied
at each band.

Special-rate income is modelled as a LIST of blocks, not one blended number, because the
rate is not the only thing that varies: sec 112A carries a 1.25L exemption that sec 112 does
not, so taxing `foreign_LTCG + domestic_112A` at a flat 12.5% over-charges. Each block is
also a ScheduleSI row, which is what lets the schedule and PartB-TTI be built from one object
and cross-foot (see schedules/schedule_si.py).

Rounding follows the ITD Utility: each component is rounded to the rupee and the rounded
value feeds the next. Back-tested to the rupee on the filed AY2025-26 and AY2026-27 returns.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Sequence

# (upper_threshold or None, rate) cumulative slabs, new regime
SLABS = {
    "2024-25": [(300000, 0.0), (700000, 0.05), (1000000, 0.10),
                (1200000, 0.15), (1500000, 0.20), (None, 0.30)],
    "2025-26": [(400000, 0.0), (800000, 0.05), (1200000, 0.10), (1600000, 0.15),
                (2000000, 0.20), (2400000, 0.25), (None, 0.30)],
}
CESS = 0.04
# surcharge bands (total income threshold -> rate); new regime max 25%
_SURCHARGE = [(5_000_000, 0.0), (10_000_000, 0.10), (20_000_000, 0.15), (None, 0.25)]
_SURCHARGE_SPECIAL_CAP = 0.15   # surcharge on 111A/112/112A/dividend capped at 15%

# Sec 112A: LTCG on STT-paid equity / equity MF is exempt up to this much in the year.
# (1L until 22-Jul-2024, 1.25L from AY2025-26.)
SEC_112A_EXEMPTION = {"2024-25": 125000.0, "2025-26": 125000.0}


@dataclass(frozen=True)
class SpecialIncome:
    """One block of income taxed at its own rate = one ScheduleSI row.

    `exempt` is the slice that bears no tax before the rate applies. It stays inside total
    income (it still drives the surcharge band), it simply is not taxed - which is exactly
    why it has to be modelled here rather than netted off upstream.
    """
    code: str                    # ITR ScheduleSI SecCode, e.g. "21", "2A", "1A"
    income: float
    rate: float
    exempt: float = 0.0

    @property
    def taxable(self) -> float:
        return max(0.0, self.income - self.exempt)

    @property
    def tax(self) -> float:
        return self.taxable * self.rate


@dataclass
class TaxResult:
    tax_normal: int
    tax_special: int
    surcharge: int
    cess: int
    gross_tax: int            # tax + surcharge + cess
    rebate_87a: float = 0.0
    special_rows: tuple[SpecialIncome, ...] = ()

    @property
    def special_income(self) -> float:
        """Total special-rate income, INCLUDING any exempt slice (it is part of total income)."""
        return sum(s.income for s in self.special_rows)


def rupee(x: float) -> int:
    """Round to the whole rupee, half UP. Python's round() is banker's rounding, which sends
    a .5 to the nearest EVEN rupee and drifts away from the department's arithmetic."""
    return int(math.floor(abs(x) + 0.5)) * (1 if x >= 0 else -1)


def slab_tax(income: float, fy: str) -> float:
    tax, lo = 0.0, 0.0
    for hi, rate in SLABS[fy]:
        cap = hi if hi is not None else income
        if income > lo:
            tax += (min(income, cap) - lo) * rate
        lo = cap
        if hi is not None and income <= hi:
            break
    return tax


def marginal_slab_rate(income: float, fy: str) -> float:
    """Rate the NEXT rupee of ordinary income bears - used to price dividend income for 234C."""
    rate = 0.0
    for hi, r in SLABS[fy]:
        rate = r
        if hi is not None and income <= hi:
            break
    return rate


def _surcharge_rate(total_income: float) -> float:
    for hi, rate in _SURCHARGE:
        if hi is None or total_income <= hi:
            return rate
    return 0.30


def gross_up(total_income: float, fy: str, special: bool = False) -> float:
    """Multiplier turning base tax into tax + surcharge + cess at this income level.

    Needed wherever we have to attribute the tax on one slice of income (234C's capital-gain
    and dividend proviso), because interest is charged on tax INCLUSIVE of surcharge and cess.
    """
    rate = _surcharge_rate(total_income)
    if special:
        rate = min(rate, _SURCHARGE_SPECIAL_CAP)
    return (1 + rate) * (1 + CESS)


def compute_tax(normal_income: float, special: Sequence[SpecialIncome] = (),
                fy: str = "2025-26", rebate_87a: float = 0.0) -> TaxResult:
    """`normal_income` taxed at slabs; each `special` block at its own rate after its exemption."""
    special = tuple(special)
    special_income = sum(s.income for s in special)
    total_income = normal_income + special_income

    tax_normal = rupee(slab_tax(normal_income, fy) - rebate_87a)
    tax_special = rupee(sum(s.tax for s in special))
    base_tax = tax_normal + tax_special

    s_rate = _surcharge_rate(total_income)
    s_special_rate = min(s_rate, _SURCHARGE_SPECIAL_CAP)
    surcharge = tax_normal * s_rate + tax_special * s_special_rate
    surcharge = _marginal_relief(total_income, base_tax, surcharge, fy, special_income,
                                 tax_special)
    surcharge = rupee(surcharge)

    cess = rupee((base_tax + surcharge) * CESS)
    return TaxResult(tax_normal=tax_normal, tax_special=tax_special, surcharge=surcharge,
                     cess=cess, gross_tax=base_tax + surcharge + cess, rebate_87a=rebate_87a,
                     special_rows=special)


def _marginal_relief(total_income, base_tax, surcharge, fy, special_income, tax_special):
    """Cap surcharge so (base+surcharge) doesn't exceed the tax at the crossed threshold
    plus the income above it. Uses the surcharge rate applicable AT the threshold."""
    thresholds = [t for t, _ in _SURCHARGE[:-1] if t and total_income > t]
    if not thresholds:
        return surcharge
    thr = max(thresholds)
    normal_at_thr = slab_tax(max(0.0, thr - special_income), fy)
    base_at_thr = normal_at_thr + tax_special
    rate_at_thr = _surcharge_rate(thr)   # lower band rate applicable at the threshold
    surch_at_thr = (normal_at_thr * rate_at_thr
                    + tax_special * min(rate_at_thr, _SURCHARGE_SPECIAL_CAP))
    cap = base_at_thr + surch_at_thr + (total_income - thr)
    if base_tax + surcharge > cap:
        return max(0.0, cap - base_tax)
    return surcharge
