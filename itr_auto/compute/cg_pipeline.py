"""Current-year capital-gains pipeline: G&L sales -> per-lot INR gain -> STCG/LTCG totals.

Ties together the authoritative sources so nothing is hardcoded:
  cost  = FMV(USD) x qty x Adobe vest-rate   (Sec 49(2AA), from perquisite statements)
  proceeds = proceeds(USD) x SBI TTBR on sale date (Rule 115, auto-fetched)
  gain, LTCG/STCG classification + indexation via the CG engine.
Returns net STCG and net LTCG (pre set-off) for a given Indian FY.
"""
from __future__ import annotations

import datetime as dt
from typing import Any

from itr_auto.parsers.gain_loss import parse_all as gl_all
from itr_auto.parsers.perquisite import parse_all as perq_all
from itr_auto.reference.fx import FxService, SbiAutoSource
from itr_auto.reference.cii import CII
from itr_auto.compute.capital_gains import compute_gain


def vest_rates(perq_rows: list[dict[str, Any]] | None = None) -> dict[str, float]:
    """Adobe's vest-date forex rate, one per vest date, from the ESOP statements.

    Adobe repeats some grants as ZERO-QUANTITY lines carrying a slightly different rate. Built
    as a plain dict comprehension those phantom rows win by parse order: on 2020-01-24 the real
    grant lines both say 71.3250 while two zero-qty rows say 71.2404, and last-wins took the
    phantom, understating the cost basis of every share from that vest. Skip rows that delivered
    no shares, and refuse to pick when two REAL lines disagree - that is a data problem, not a
    default.
    """
    rates: dict[str, float] = {}
    for p in perq_rows if perq_rows is not None else perq_all():
        if not p["gross_qty"]:
            continue
        seen = rates.setdefault(p["vest_date"], p["adobe_forex"])
        if seen != p["adobe_forex"]:
            raise ValueError(
                f"conflicting Adobe forex rates for vest {p['vest_date']}: {seen} vs "
                f"{p['adobe_forex']} - resolve against the ESOP statement before computing CG")
    return rates


def current_year_cg(fy: str) -> dict[str, Any]:
    vest_fx = vest_rates()
    cii = CII                                   # public CII table (no .numbers dependency)
    fx = FxService(SbiAutoSource())

    stcg = ltcg = 0.0
    lt_proc = lt_cost = st_proc = st_cost = 0.0   # aggregate consideration/cost for Schedule CG detail
    lots = []
    for s in gl_all():
        if s["fy_sold"] != fy:
            continue
        rate = vest_fx.get(s["vest_date"])
        if rate is None:            # e.g. Dec-2023 ESPP missing from perquisite statements
            continue
        cost = s["fmv_usd"] * s["qty"] * rate
        proceeds = fx.convert_sale_proceeds(s["proceeds_usd"],
                                            dt.date.fromisoformat(s["sold_date"]))
        r = compute_gain(proceeds, cost, s["vest_date"], s["sold_date"], cii)
        if r.term == "LTCG":
            ltcg += r.gain_inr; lt_proc += proceeds; lt_cost += cost
        else:
            stcg += r.gain_inr; st_proc += proceeds; st_cost += cost
        lots.append({"vest": s["vest_date"], "sold": s["sold_date"], "qty": s["qty"],
                     "term": r.term, "gain_inr": round(r.gain_inr)})
    return {"fy": fy, "stcg": round(stcg), "ltcg": round(ltcg),
            "lt_proceeds": round(lt_proc), "lt_cost": round(lt_cost),
            "st_proceeds": round(st_proc), "st_cost": round(st_cost), "lots": lots}


if __name__ == "__main__":
    import json
    print(json.dumps(current_year_cg("2025-26"), indent=2))
