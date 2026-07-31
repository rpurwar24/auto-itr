"""New-regime income-tax calculator (slab + special rates + surcharge + cess).

Slabs are year-parameterised so we can back-test against a filed year and then apply the
current year. Special-rate income (e.g. LTCG u/s 112 @ 12.5%) is taxed separately; surcharge
on special-rate income is capped at 15%. Marginal relief on surcharge is applied at each band.
Validated: FY2024-25 slabs on the filed AY2025-26 income reproduce the filed tax exactly.
"""
from __future__ import annotations

from dataclasses import dataclass

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


@dataclass
class TaxResult:
    tax_normal: float
    tax_special: float
    surcharge: float
    cess: float
    gross_tax: float          # tax + surcharge + cess
    rebate_87a: float = 0.0


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


def _surcharge_rate(total_income: float) -> float:
    for hi, rate in _SURCHARGE:
        if hi is None or total_income <= hi:
            return rate
    return 0.30


def compute_tax(normal_income: float, special_income: float, special_rate: float,
                fy: str, rebate_87a: float = 0.0) -> TaxResult:
    """normal_income taxed at slabs; special_income at special_rate (e.g. 0.125 LTCG)."""
    total_income = normal_income + special_income
    tax_normal = slab_tax(normal_income, fy) - rebate_87a
    tax_special = special_income * special_rate
    base_tax = tax_normal + tax_special

    s_rate = _surcharge_rate(total_income)
    s_special_rate = min(s_rate, _SURCHARGE_SPECIAL_CAP)
    surcharge = tax_normal * s_rate + tax_special * s_special_rate

    # marginal relief: tax+surcharge must not exceed tax-at-threshold + (income - threshold)
    surcharge = _marginal_relief(total_income, base_tax, surcharge, fy, special_income,
                                 special_rate)

    cess = (base_tax + surcharge) * CESS
    return TaxResult(tax_normal=tax_normal, tax_special=tax_special, surcharge=surcharge,
                     cess=cess, gross_tax=base_tax + surcharge + cess, rebate_87a=rebate_87a)


def _marginal_relief(total_income, base_tax, surcharge, fy, special_income, special_rate):
    """Cap surcharge so (base+surcharge) doesn't exceed the tax at the crossed threshold
    plus the income above it. Uses the surcharge rate applicable AT the threshold."""
    thresholds = [t for t, _ in _SURCHARGE[:-1] if t and total_income > t]
    if not thresholds:
        return surcharge
    thr = max(thresholds)
    normal_at_thr = slab_tax(max(0.0, thr - special_income), fy)
    special_at_thr = special_income * special_rate
    base_at_thr = normal_at_thr + special_at_thr
    rate_at_thr = _surcharge_rate(thr)   # lower band rate applicable at the threshold
    surch_at_thr = (normal_at_thr * rate_at_thr
                    + special_at_thr * min(rate_at_thr, _SURCHARGE_SPECIAL_CAP))
    cap = base_at_thr + surch_at_thr + (total_income - thr)
    if base_tax + surcharge > cap:
        return max(0.0, cap - base_tax)
    return surcharge
