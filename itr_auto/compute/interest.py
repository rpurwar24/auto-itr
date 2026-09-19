"""Interest for default in payment of tax: sections 234A, 234B and 234C.

The tax engine computes TAX. This module computes what the department adds on top when that
tax was not paid when it was due, which is what turns a "net tax payable" into an amount you
can actually pay at the counter.

  234A  late FILING          1%/month on the unpaid tax, due date -> date of filing
  234B  advance-tax SHORTFALL 1%/month on the unpaid tax, 1 April of the AY -> date of payment
  234C  advance-tax DEFERMENT 1%/month on each instalment you underpaid, within the year

234B is the one that keeps running after the return is filed. 234C is frozen at year end: it
only prices the timing of the four instalments, so it never grows.

Back-tested to the rupee against a filed return, in tests/ (which stay local - they carry
real figures).
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Mapping

RATE = 0.01                       # 1% for every month or PART of a month

# Sec 234B(1) only bites where the advance tax paid is under 90% of the assessed tax. Pay
# 90% or more and the interest is nil outright, not merely small.
SEC_234B_THRESHOLD = 0.90

# Advance-tax instalments for a non-presumptive individual, as cumulative % of tax due.
# 1 -> 15 Jun, 2 -> 15 Sep, 3 -> 15 Dec, 4 -> 15 Mar.
_CUMULATIVE = {1: 0.15, 2: 0.45, 3: 0.75, 4: 1.00}
_MONTHS = {1: 3, 2: 3, 3: 3, 4: 1}

# Accrual buckets used by the ITR's quarterly grids (ScheduleCGFor23 Table F, ScheduleOS
# dividend DateRange). Bucket 5 exists because income arising 16-31 March can only ever be
# covered by a payment made by 31 March, after the last instalment has fallen due.
BUCKETS = (1, 2, 3, 4, 5)
BUCKET_KEYS = ("Upto15Of6", "Upto15Of9", "Up16Of9To15Of12", "Up16Of12To15Of3", "Up16Of3To31Of3")


@dataclass(frozen=True)
class InterestResult:
    us_234a: int
    us_234b: int
    us_234c: int

    @property
    def total(self) -> int:
        return self.us_234a + self.us_234b + self.us_234c


def round_119a(amount: float) -> float:
    """Rule 119A: the amount interest is charged on drops to the lower multiple of 100.

    Why it matters: 50,072 of unpaid tax is charged as 50,000, so a month of 234B is a flat
    500 rather than 500.72. Every figure below inherits this base.
    """
    return max(0.0, float(int(amount // 100) * 100))


def months_since_april(as_of: date, ay_start_year: int) -> int:
    """234B months: 1 April of the assessment year -> `as_of`, part months counting whole."""
    months = (as_of.year - ay_start_year) * 12 + as_of.month - 4 + 1
    return max(0, months)


def interest_234a(tax_due: float, due_date: date, filing_date: date) -> int:
    """Nil if the return went in on or before the due date, which is the usual case."""
    if filing_date <= due_date:
        return 0
    months = ((filing_date.year - due_date.year) * 12 + filing_date.month - due_date.month
              + (1 if filing_date.day > due_date.day else 0))
    return int(round_119a(tax_due) * RATE * max(1, months))


def interest_234b(assessed_tax: float, months: int, advance_tax: float = 0.0) -> int:
    """`assessed_tax` = tax on returned income after relief, less TDS/TCS.

    Two distinct roles for advance tax here, and they are easy to conflate:
      - it is the TEST: no interest at all once it reaches 90% of the assessed tax;
      - it is a DEDUCTION: below that, interest runs on the shortfall it leaves behind.
    Self-assessment tax does NEITHER. It is paid after the year is over, so it cannot cure an
    advance-tax default; it only stops the clock, which the caller does via `months`.
    """
    if assessed_tax <= 0 or advance_tax >= SEC_234B_THRESHOLD * assessed_tax:
        return 0
    return int(round_119a(assessed_tax - advance_tax) * RATE * max(0, months))


def interest_234c(tax_due: float,
                  deferrable_tax: Mapping[int, float] | None = None,
                  advance_paid: Mapping[int, float] | None = None) -> int:
    """Interest for paying each instalment short.

    `deferrable_tax` maps an accrual bucket (1..5) to the tax on the capital-gains and
    dividend income arising in it. The proviso to sec 234C exists because you cannot be
    asked to pre-pay tax on a gain you had not yet made, so tax on income that accrues
    after an instalment's due date is excluded from that instalment's requirement.

    The last instalment gets that relief only if the tax was in fact paid by 31 March, so
    with nothing paid it is charged on the full amount. This reproduces the ITD Utility's
    own figure exactly (locked in tests/).

    `advance_paid` maps an instalment (1..4) to the CUMULATIVE advance tax paid by its date.
    """
    deferrable = dict(deferrable_tax or {})
    paid = dict(advance_paid or {})
    base = round_119a(tax_due)
    total = 0.0
    for q, pct in _CUMULATIVE.items():
        # relief for not-yet-accrued income; unavailable at the final instalment (see above)
        not_yet_accrued = sum(v for b, v in deferrable.items() if b > q) if q < 4 else 0.0
        shortfall = pct * max(0.0, base - not_yet_accrued) - paid.get(q, 0.0)
        if shortfall > 0:
            total += shortfall * RATE * _MONTHS[q]
    return int(total)


def compute_interest(assessed_tax: float, *, ay_start_year: int, as_of: date,
                     due_date: date | None = None, filing_date: date | None = None,
                     deferrable_tax: Mapping[int, float] | None = None,
                     advance_paid: Mapping[int, float] | None = None,
                     advance_tax: float = 0.0,
                     paid_before_due_date: float = 0.0) -> InterestResult:
    """All three, for a return whose self-assessment tax is being paid on `as_of`.

    `assessed_tax` is BEFORE advance tax - tax on the returned income, less relief, TDS and
    TCS. Advance tax then enters each section differently, which is the whole reason it has
    to be passed rather than netted off by the caller:

      234A  reduces the base, and so does self-assessment tax paid before the due date
            (proviso to sec 234A(1))
      234B  is the 90% test AND reduces the base (sec 234B(1))
      234C  is credited instalment by instalment, cumulatively, against what each one
            required - the base itself never moves

    `advance_paid` maps an instalment (1..4) to the CUMULATIVE advance tax paid by its due
    date; `advance_tax` is the total of it.
    """
    a = (interest_234a(max(0.0, assessed_tax - advance_tax - paid_before_due_date),
                       due_date, filing_date)
         if due_date and filing_date else 0)
    return InterestResult(
        us_234a=a,
        us_234b=interest_234b(assessed_tax, months_since_april(as_of, ay_start_year), advance_tax),
        us_234c=interest_234c(assessed_tax, deferrable_tax, advance_paid),
    )


def cumulative_advance_tax(payments, fy: str) -> dict[int, float]:
    """Advance tax paid by each instalment's due date, as sec 234C compares it.

    `payments` is an iterable of (date, amount). Cumulative is the point: money paid by
    15 June is still in the department's hands on 15 September, so crediting it to the June
    instalment alone would charge interest on tax that had already been paid.
    """
    year = int(fy.split("-")[0])
    due = {1: date(year, 6, 15), 2: date(year, 9, 15), 3: date(year, 12, 15),
           4: date(year + 1, 3, 15)}
    return {q: float(sum(a for d, a in payments if d <= by)) for q, by in due.items()}
