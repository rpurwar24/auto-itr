"""Parse Adobe's ITCS (Income Tax Computation Statement) - the salary breakup.

Form 16 gives 17(1) salary and 17(2) perquisite as lump sums; the ITCS breaks 17(1)
into components (Basic, HRA, LTA, bonuses, conveyance) - which Schedule S needs.
The document lists component LABELS, then an Actual block, a Projected block, and a
Total block (Total = Actual + Projected). We read the Total block.
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from pypdf import PdfReader

from itr_auto.workspace import sources_dir, workspace_root
ITCS_DIR = sources_dir() / "adobe"

# the 10 rows of "Heads of Income" -> Total block, in document order
COMPONENT_LABELS = [
    "Basic", "House Rent Allowance", "Leave Travel Allowance", "Aip Bonus",
    "Wellness Reimbursement", "Patent Issued Bonus", "Conveyance Allowance",
    "Perquisites", "Profits in lieu of Salary", "Previous Employer Income",
]
_NUM = re.compile(r"-?\d+(?:\.\d+)?$")


def _lines(path: Path) -> list[str]:
    text = PdfReader(str(path)).pages[0].extract_text() or ""
    return [ln.strip() for ln in text.splitlines() if ln.strip()]


def _first_number_after(lines: list[str], label: str) -> float | None:
    """First numeric line at/after the line containing `label`.

    The ITCS lists a block of labels then a block of values, so we skip
    intervening non-numeric (label) lines rather than stopping at them.
    """
    for i, ln in enumerate(lines):
        if label in ln:
            m = re.search(r"-?\d[\d,]*\.\d+", ln.replace(label, ""))
            if m:
                return float(m.group().replace(",", ""))
            for nxt in lines[i + 1:]:
                if _NUM.match(nxt):
                    return float(nxt)
    return None


def parse_file(path: str | Path) -> dict[str, Any]:
    path = Path(path)
    lines = _lines(path)
    joined = "\n".join(lines)

    # component Total block: numbers between the "Total" that follows "Projected"
    # and the "Gross Salary" row
    idx_proj = next((i for i, l in enumerate(lines) if l == "Projected"), None)
    idx_total = next((i for i, l in enumerate(lines[idx_proj:], idx_proj) if l == "Total"),
                     None) if idx_proj is not None else None
    totals: list[float] = []
    if idx_total is not None:
        for ln in lines[idx_total + 1:]:
            if "Gross Salary" in ln:
                break
            if _NUM.match(ln):
                totals.append(float(ln))
    components = {lbl: totals[i] for i, lbl in enumerate(COMPONENT_LABELS) if i < len(totals)}

    regime = "New" if re.search(r"New Regime", joined) else ("Old" if "Old Regime" in joined else None)
    ay = (re.search(r"Assessment Year\s+(\d{4}-\d{4})", joined) or [None, None])[1]
    fy = (re.search(r"Financial Year\s+(\d{4}-\d{4})", joined) or [None, None])[1]

    # the 17(1) salary components are the rows before Perquisites/Profits/Previous-employer.
    # expose them explicitly so Schedule S groups EVERY one (a component the profile doesn't
    # map by name must fall to "OTH", never be dropped - see build_schedule_s).
    salary_components = {k: components.get(k, 0.0) for k in COMPONENT_LABELS[:7]
                         if k in components}
    salary_17_1 = sum(salary_components.values())
    perquisite_17_2 = components.get("Perquisites", 0.0)
    gross_salary = salary_17_1 + perquisite_17_2
    net_taxable = _first_number_after(lines, "Net Taxable Salary") or gross_salary
    std_ded = round(gross_salary - net_taxable, 2)   # 16(ia) standard deduction

    return {
        "source": str(path.relative_to(workspace_root())),
        "assessment_year": ay,
        "financial_year": fy,
        "regime": regime,
        "components": components,             # per-component breakup of 17(1) + perquisite
        "salary_components": salary_components,  # ONLY the 17(1) rows (excl perquisite/profits/prev)
        "salary_17_1": salary_17_1,           # sum of the 7 salary components
        "perquisite_17_2": perquisite_17_2,   # ESOP
        "gross_salary": gross_salary,
        "standard_deduction_16ia": std_ded,
        "income_under_salary": net_taxable,
    }


def parse_latest(itcs_dir: str | Path = ITCS_DIR) -> dict[str, Any]:
    files = sorted(Path(itcs_dir).glob("*/itcs*.pdf"))
    if not files:
        raise FileNotFoundError(f"no ITCS pdf in {itcs_dir}")
    return parse_file(files[-1])


if __name__ == "__main__":
    import json
    print(json.dumps(parse_latest(), indent=2))
