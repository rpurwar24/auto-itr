"""Schedule SI - income chargeable at special rates.

Gap this closes: we used to emit the schedule untouched (every SecCode zero) while PartB-TI
declared several lakh of special-rate income. The file was internally inconsistent and
nothing noticed, because the tax was computed from a separate blended number. Building the
schedule from the very rows the tax engine used, and cross-footing the two, makes that class
of bug impossible rather than merely unlikely.
"""
from __future__ import annotations

from typing import Iterable

from itr_auto.compute.tax import SpecialIncome, rupee
from itr_auto.schema_tools import load_schema

SI_STCG_111A = "1A"      # STCG on STT-paid equity / equity MF u/s 111A (20%)
SI_LTCG_112 = "21"       # LTCG u/s 112 - assets other than 112A, incl. foreign shares (12.5%)
SI_LTCG_112A = "2A"      # LTCG u/s 112A - STT-paid equity / equity MF (12.5%, first 1.25L exempt)

_BLANK = {"SplRatePercent": 0, "SplRateInc": 0, "SplRateIncTax": 0}


def sec_codes(schema: dict | None = None) -> list[str]:
    """The SecCodes this assessment year's schema allows, in schema order."""
    s = schema or load_schema()
    return list(s["definitions"]["ScheduleSI"]["properties"]["SplCodeRateTax"]
                 ["items"]["properties"]["SecCode"]["enum"])


def build_schedule_si(rows: Iterable[SpecialIncome], base: dict | None = None) -> dict:
    """Fill the SecCode table from the tax engine's special-rate blocks.

    `base` is the prefill's own ScheduleSI when we have one, so we keep the full code table
    the Utility emits; without it we emit only the heads that carry income. Codes are checked
    against the official schema enum, so a stale code fails loudly at build time instead of
    silently dropping an income head from the return.
    """
    allowed = set(sec_codes())
    rows = tuple(rows)
    for row in rows:
        if row.code not in allowed:
            raise KeyError(f"ScheduleSI SecCode {row.code!r} is not in the AY schema enum")

    table = [dict(r) for r in (base or {}).get("SplCodeRateTax", [])]
    by_code = {r["SecCode"]: r for r in table}
    for row in rows:
        target = by_code.get(row.code)
        if target is None:
            target = {"SecCode": row.code, **_BLANK}
            table.append(target)
            by_code[row.code] = target
        target["SplRatePercent"] = row.rate * 100
        target["SplRateInc"] = rupee(row.income)      # the WHOLE income, exempt slice included
        target["SplRateIncTax"] = rupee(row.tax)      # tax AFTER the exemption -> may be 0

    return {"SplCodeRateTax": table,
            "TotSplRateInc": sum(r["SplRateInc"] for r in table),
            "TotSplRateIncTax": sum(r["SplRateIncTax"] for r in table)}


def cross_foot(si: dict, *, special_income: int, tax_special: int) -> None:
    """Assert ScheduleSI agrees with PartB-TI and PartB-TTI. Raises rather than ships."""
    if si["TotSplRateInc"] != special_income:
        raise AssertionError(
            f"ScheduleSI special-rate income {si['TotSplRateInc']:,} != PartB-TI "
            f"IncChargeableTaxSplRates {special_income:,}")
    if si["TotSplRateIncTax"] != tax_special:
        raise AssertionError(
            f"ScheduleSI tax {si['TotSplRateIncTax']:,} != PartB-TTI TaxAtSpecialRates "
            f"{tax_special:,}")
