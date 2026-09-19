"""Parse an ITD "Challan Receipt" PDF - the receipt e-Pay Tax issues for a tax payment.

The receipt is the only evidence the department will match a credit against, and every field
the return needs is printed on it: BSR code, challan serial, date of deposit, amount, the
CIN, and the head the money was paid under.

What the return does with it
----------------------------
Schedule IT lists every payment. It has NO minor-head field (see the schema's `TaxPayment`:
BSRCode / DateDep / SrlNoOfChaln / Amt), so what separates advance tax from self-assessment
tax is the DATE: paid on or before 31 March of the financial year it is advance tax, paid
after it is self-assessment tax. The receipt's "Minor Head" line is used only to cross-check
that, and to reject a demand payment (400) that does not belong in a fresh return.

Why it is worth parsing rather than typing
------------------------------------------
Four fields, hand-copied, that the department matches EXACTLY. A wrong BSR code or serial is
an unmatched credit and a demand notice for tax you have already paid.

Run:  .venv/bin/python -m itr_auto.parsers.challan
"""
from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path

from pypdf import PdfReader

from itr_auto.workspace import personal_json, sources_dir

# Receipts are downloaded from the portal, so they live with the other portal documents.
CHALLAN_DIR = sources_dir() / "portal"

# The header the ITD puts on every e-Pay Tax receipt. Anything without it is not a challan.
_MARKER = re.compile(r"challan\s+receipt", re.I)

# Minor heads that are a PRE-PAID tax for the return being filed. 400 (tax on regular
# assessment) is paid against a raised demand and is claimed in response to that demand,
# not as a payment in a fresh return.
ADVANCE_TAX, SELF_ASSESSMENT_TAX = 100, 300
_CLAIMABLE = {ADVANCE_TAX, SELF_ASSESSMENT_TAX}


@dataclass(frozen=True)
class Challan:
    bsr_code: str
    serial: int
    date: date                 # date of deposit
    amount: int
    cin: str
    major_head: int            # 21 = income tax other than companies
    minor_head: int            # 100 advance, 300 self-assessment
    assessment_year: str       # "2026-27"
    pan: str
    # the receipt's own breakup of what the payment covered
    tax: int = 0
    surcharge: int = 0
    cess: int = 0
    interest: int = 0
    penalty: int = 0
    others: int = 0
    source: str = ""

    def is_advance_tax(self, fy: str) -> bool:
        """Advance tax is tax paid INSIDE the financial year; after 31 March it is
        self-assessment tax however the challan was labelled."""
        return self.date <= fy_end(fy)

    def as_tax_payment(self) -> dict:
        """One Schedule IT row."""
        return {"BSRCode": self.bsr_code, "DateDep": self.date.isoformat(),
                "SrlNoOfChaln": self.serial, "Amt": self.amount}

    def as_dict(self) -> dict:
        """The shape generate.build(challans=[...]) and config's `challans` block use."""
        return {"bsr_code": self.bsr_code, "serial": f"{self.serial:05d}",
                "date": self.date.isoformat(), "amount": self.amount, "_cin": self.cin}


def fy_end(fy: str) -> date:
    """Last day of the financial year: "2025-26" -> 2026-03-31."""
    return date(int(fy.split("-")[0]) + 1, 3, 31)


def _num(text: str, label: str) -> int | None:
    m = re.search(rf"{label}\s*:?\s*(?:Rs\.?|₹)?\s*([\d,]+)", text, re.I)
    return int(m.group(1).replace(",", "")) if m else None


def _breakup(text: str, letter: str, label: str) -> int:
    """One line of the receipt's "Tax Breakup Details" table, e.g. "D Interest ₹ 1,234".

    Anchored at the start of a line: an unanchored "A Tax" happily matches inside other
    wording on the receipt and would silently pick up the wrong number.
    """
    m = re.search(rf"^{letter}\s+{label}\s*(?:Rs\.?|₹)?\s*([\d,]+)", text, re.I | re.M)
    return int(m.group(1).replace(",", "")) if m else 0


def _head(text: str, label: str) -> int | None:
    """Heads print as "Self-Assessment Tax (300)" - the code is what matters."""
    m = re.search(rf"{label}\s*:\s*(.*)", text, re.I)
    if not m:
        return None
    code = re.search(r"\((\d{3,4})\)", m.group(1))
    return int(code.group(1)) if code else None


def _date(text: str) -> date | None:
    m = re.search(r"Date of Deposit\s*:?\s*(\d{1,2})[-/](\w{3,})[-/](\d{4})", text, re.I)
    if m:
        return datetime.strptime(f"{m.group(1)} {m.group(2)[:3]} {m.group(3)}", "%d %b %Y").date()
    m = re.search(r"Date of Deposit\s*:?\s*(\d{1,2})[-/](\d{1,2})[-/](\d{4})", text)
    return date(int(m.group(3)), int(m.group(2)), int(m.group(1))) if m else None


def parse_challan_text(text: str, *, pan: str | None = None,
                       assessment_year: str | None = None) -> Challan | None:
    """Parse the text of a receipt. Returns None if this simply isn't a challan receipt.

    `pan` and `assessment_year`, when given, are checked rather than trusted: a receipt for
    someone else's PAN or for another year, left in the folder, would otherwise be claimed
    as a credit in this return.
    """
    if not _MARKER.search(text):
        return None
    text = re.sub(r"[ \t]+", " ", text)

    def need(value, what):
        if value in (None, ""):
            raise ValueError(f"challan receipt is missing its {what}; parsed text:\n{text[:400]}")
        return value

    got_pan = re.search(r"\bPAN\s*:?\s*([A-Z]{5}\d{4}[A-Z])", text)
    got_pan = need(got_pan and got_pan.group(1), "PAN")
    if pan and got_pan != pan:
        raise ValueError(f"challan was paid on PAN {got_pan}, not {pan} - it is not yours to claim")

    ay = re.search(r"Assessment Year\s*:?\s*(\d{4}-\d{2})", text)
    ay = need(ay and ay.group(1), "assessment year")
    if assessment_year and ay != assessment_year:
        raise ValueError(f"challan is for assessment year {ay}, this return is {assessment_year}")

    minor = need(_head(text, "Minor Head"), "minor head")
    if minor not in _CLAIMABLE:
        raise ValueError(
            f"challan minor head {minor} is not a pre-paid tax for this return "
            f"(expected {ADVANCE_TAX} advance tax or {SELF_ASSESSMENT_TAX} self-assessment tax)")

    bsr = re.search(r"BSR\s*code\s*:?\s*(\d{3}[0-9A-Z]{4})", text, re.I)
    serial = re.search(r"Challan\s*No\.?\s*:?\s*(\d{1,5})", text, re.I)
    # CIN as TIN 2.0 issues it: 18 chars, YYMMDD + sequence + bank (e.g. 250401000012345ABCD).
    # (NOT the old OLTAS BSR+DDMMYYYY+serial CIN - we have one sample of the new format, so it
    # is carried for the record and to answer a demand with, and not decomposed.)
    cin = re.search(r"\bCIN\s*:?\s*([0-9A-Z]{14,})", text)
    amount = _num(text, r"Amount \(in Rs\.?\)")
    deposited = _date(text)

    c = Challan(
        bsr_code=need(bsr and bsr.group(1), "BSR code"),
        serial=int(need(serial and serial.group(1), "challan number")),
        date=need(deposited, "date of deposit"),
        amount=need(amount, "amount"),
        cin=need(cin and cin.group(1), "CIN"),
        major_head=need(_head(text, "Major Head"), "major head"),
        minor_head=minor,
        assessment_year=ay,
        pan=got_pan,
        tax=_breakup(text, "A", "Tax"),
        surcharge=_breakup(text, "B", "Surcharge"),
        cess=_breakup(text, "C", "Cess"),
        interest=_breakup(text, "D", "Interest"),
        penalty=_breakup(text, "E", "Penalty"),
        others=_breakup(text, "F", "Others"),
    )
    _cross_foot(c)
    return c


def _cross_foot(c: Challan) -> None:
    """The receipt states the same payment twice - as a total, and as a breakup into tax /
    surcharge / cess / interest / penalty / others. They must agree, or a line has been read
    off the wrong row and the credit we claim will not be the credit that was paid."""
    parts = c.tax + c.surcharge + c.cess + c.interest + c.penalty + c.others
    if parts and parts != c.amount:
        raise ValueError(f"challan {c.cin}: breakup sums to {parts:,} but the amount paid is "
                         f"{c.amount:,} - a line has been misread")


def parse_challan(path: str | Path, *, pan: str | None = None,
                  assessment_year: str | None = None) -> Challan | None:
    """Parse one receipt PDF. None if the file is a PDF but not a challan receipt."""
    path = Path(path)
    text = "\n".join((p.extract_text() or "") for p in PdfReader(str(path)).pages)
    c = parse_challan_text(text, pan=pan, assessment_year=assessment_year)
    return c and Challan(**{**c.__dict__, "source": path.name})


def _my_pan() -> str | None:
    try:
        return json.loads(personal_json().read_text()).get("pan")
    except (OSError, ValueError):
        return None


def scan_challans(fy: str, *, assessment_year: str | None = None,
                  pan: str | None = None) -> list[Challan]:
    """Every challan receipt dropped into sources/portal/<fy>/, oldest first.

    Challans are recognised by their CONTENT, so any filename works and the other documents
    that share that folder (the filing acknowledgement, for one) are simply not challans.
    A file we cannot read AS a PDF is skipped for the same reason - it is not a receipt.
    A file that IS a challan but fails validation still raises: that one is about the money.
    """
    pan = pan or _my_pan()
    assessment_year = assessment_year or f"{int(fy.split('-')[0]) + 1}-{int(fy.split('-')[1]) + 1:02d}"
    found: list[Challan] = []
    # We are PROBING files that may not be receipts at all, so pypdf's complaints about the
    # ones that aren't are expected noise rather than news. Real problems still raise.
    quiet = logging.getLogger("pypdf")
    was = quiet.level
    quiet.setLevel(logging.CRITICAL)
    try:
        for p in sorted((CHALLAN_DIR / fy).glob("*.pdf")):
            try:
                c = parse_challan(p, pan=pan, assessment_year=assessment_year)
            except ValueError:
                raise                                   # a challan we cannot trust: stop
            except Exception:                           # noqa: BLE001 - see docstring
                continue                                # unreadable file: not a receipt
            if c:
                found.append(c)
    finally:
        quiet.setLevel(was)
    return sorted(found, key=lambda c: (c.date, c.serial))


if __name__ == "__main__":                                        # pragma: no cover
    for c in scan_challans("2025-26"):
        kind = "advance" if c.is_advance_tax("2025-26") else "self-assessment"
        print(f"{c.date}  {c.amount:>10,}  {kind:<15} BSR {c.bsr_code} challan {c.serial:05d} "
              f"CIN {c.cin}  ({c.source})")
