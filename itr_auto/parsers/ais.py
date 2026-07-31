"""Parse the AIS (Annual Information Statement) PDF - the department's master record.

The AIS PDF is password-protected: password = PAN(lowercase) + DOB(ddmmyyyy), taken from
config/personal.json. We extract the figures that fill the manual gaps: savings-bank interest,
term-deposit interest, domestic dividends, LRS TCS, salary TDS, and flag Indian MF sales
(which imply domestic capital gains needing a cost-basis statement).

The encrypted AIS *.json download uses a non-standard salted cipher we don't reverse; the PDF
is the reliable source.
"""
from __future__ import annotations

import glob
import json
import re
from pathlib import Path
from typing import Any

from pypdf import PdfReader

from itr_auto.workspace import sources_dir, personal_json
AIS_DIR = sources_dir() / "ais"
PERSONAL = personal_json()


def _password() -> str:
    p = json.loads(PERSONAL.read_text())
    return p["pan"].lower() + p["dob_ddmmyyyy"]


def _pdf_text(kind: str) -> str:
    hits = [f for f in glob.glob(str(AIS_DIR / "**" / "*.pdf"), recursive=True)
            if kind.lower() in Path(f).name.lower()]
    if not hits:
        raise FileNotFoundError(f"no {kind} pdf in ais/")
    r = PdfReader(hits[0])
    if r.is_encrypted:
        r.decrypt(_password())
    return re.sub(r"[ \t]+", " ", "\n".join((p.extract_text() or "") for p in r.pages))


def _text() -> str:
    return _pdf_text("AIS")


def _tis_amount(label: str) -> float | None:
    """Department's processed aggregate from the TIS (authoritative, de-duplicated)."""
    try:
        t = _pdf_text("TIS")
    except FileNotFoundError:
        return None
    m = re.search(rf"\b{re.escape(label)}\s+([\d,]+)\s+[\d,]+", t)
    return float(m.group(1).replace(",", "")) if m else None


def _nums(s: str) -> list[float]:
    return [float(x.replace(",", "")) for x in re.findall(r"\d[\d,]*\.?\d*", s)]


def _sum_lastnum(text: str, code_pat: str) -> float:
    """Sum the trailing AMOUNT on each info-code summary line matching code_pat."""
    total = 0.0
    for line in re.findall(rf"{code_pat}[^\n]*", text):
        nums = _nums(line)
        if nums:
            total += nums[-1]        # summary line ends with the AMOUNT
    return total


def _section(t: str, start: str, ends: list[str]) -> str:
    i = t.find(start)
    if i < 0:
        return ""
    j = len(t)
    for e in ends:
        k = t.find(e, i + len(start))
        if k >= 0:
            j = min(j, k)
    return t[i:j]


def _sum_q_deducted(block: str) -> float:
    """Sum the 2nd amount (TDS/TCS deducted/collected) of each quarterly sub-row."""
    total = 0.0
    for m in re.finditer(r"Q[1-4]\([^)]*\) \d{2}/\d{2}/\d{4} (\d[\d,]+) (\d[\d,]+) (\d[\d,]+)", block):
        total += float(m.group(2).replace(",", ""))
    return total


def parse_ais() -> dict[str, Any]:
    t = _text()
    savings = _sum_lastnum(t, r"SFT-016\(SB\)")
    term_dep = _sum_lastnum(t, r"SFT-016\(TD\)")
    # prefer the TIS processed dividend total (de-duplicated; handles PDF line-wraps like IRCTC)
    dividends = _tis_amount("Dividend") or _sum_lastnum(t, r"SFT-015")
    mf_sale_value = _sum_lastnum(t, r"SFT-1[78]-EMF")

    # scope each sum to its own info-code section so rows don't leak across codes
    tcs = _sum_q_deducted(_section(t, "TCS-206CQ", ["SFT-", "Note -", "TDS-Ann"]))
    salary_tds = _sum_q_deducted(
        _section(t, "TDS-192", ["TDS-194", "TCS-206", "TDS-Ann", "SFT-"]))

    return {
        "savings_bank_interest": round(savings),
        "term_deposit_interest": round(term_dep),
        "domestic_dividend": round(dividends),
        "lrs_tcs": round(tcs),
        "salary_tds": round(salary_tds),
        "indian_mf_sale_value": round(mf_sale_value),   # >0 => domestic CG to report (need cost basis)
    }


if __name__ == "__main__":
    print(json.dumps(parse_ais(), indent=2))
