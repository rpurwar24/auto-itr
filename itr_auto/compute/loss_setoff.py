"""Capital-loss set-off and carry-forward (Sections 70, 74).

Rules:
  - Current-year STCL sets off against STCG and LTCG.
  - Current-year LTCL sets off against LTCG only.
  - Brought-forward STCL: against STCG then LTCG (carry up to 8 AY).
  - Brought-forward LTCL: against LTCG only.
  - Anything unabsorbed carries forward.

Feeds Schedule CYLA (current-year), BFLA (brought-forward) and CFL (carry-forward).
Amounts are net rupees per bucket (negative = loss).
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass
class SetOffResult:
    taxable_stcg: float
    taxable_ltcg: float
    cy_stcl_vs_ltcg: float      # current STCL set off against LTCG (CYLA)
    bf_stcl_used: float         # brought-forward STCL absorbed (BFLA)
    bf_ltcl_used: float         # brought-forward LTCL absorbed (BFLA)
    cf_stcl: float              # short-term loss carried forward
    cf_ltcl: float              # long-term loss carried forward


def set_off(stcg: float, ltcg: float,
            bf_stcl: float = 0.0, bf_ltcl: float = 0.0) -> SetOffResult:
    """stcg/ltcg = current-year net per head (negative = loss). bf_* >= 0."""
    cy_stcl = max(0.0, -stcg)
    cy_ltcl = max(0.0, -ltcg)
    stcg_pos = max(0.0, stcg)
    ltcg_pos = max(0.0, ltcg)

    # 1) current-year STCL -> LTCG (STCG already netted within its bucket)
    a = min(cy_stcl, ltcg_pos)
    ltcg_pos -= a
    cy_stcl -= a
    # current-year LTCL cannot touch STCG -> it just carries forward

    # 2) brought-forward STCL -> STCG then LTCG
    b1 = min(bf_stcl, stcg_pos); stcg_pos -= b1; bf_stcl_rem = bf_stcl - b1
    b2 = min(bf_stcl_rem, ltcg_pos); ltcg_pos -= b2; bf_stcl_rem -= b2

    # 3) brought-forward LTCL -> LTCG only
    c = min(bf_ltcl, ltcg_pos); ltcg_pos -= c; bf_ltcl_rem = bf_ltcl - c

    return SetOffResult(
        taxable_stcg=stcg_pos,
        taxable_ltcg=ltcg_pos,
        cy_stcl_vs_ltcg=a,
        bf_stcl_used=b1 + b2,
        bf_ltcl_used=c,
        cf_stcl=cy_stcl + bf_stcl_rem,     # unabsorbed current + brought-forward STCL
        cf_ltcl=cy_ltcl + bf_ltcl_rem,     # unabsorbed current + brought-forward LTCL
    )
