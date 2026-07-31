"""Indian bank interest certificates + FD (Schedule AL balances; interest reconciled vs AIS).

Reference implementation of the normalized `parse` hook: it wraps parsers/bank.py and returns a
ProviderResult (interest + balances) - the shape a new bank integration would emit.
"""
from itr_auto.providers.base import Provider, DocSlot, ProviderResult


def _slots(fy):
    return [DocSlot(
        id="bank", label="Bank interest certificates + FD",
        desc="Interest certificate and FD cert per account. Pick the bank when you upload - the "
             "app tags the file so its PDF password can be applied (no need to rename). "
             "Add as many files as you have.",
        dest="bank/{fy}", filename=None, multiple=True, required=True, accept=".pdf",
        tag={"label": "Bank", "options": ["hdfc", "sbi"]})]


def _parse(fy: str) -> ProviderResult:
    from itr_auto.parsers.bank import parse_bank
    b = parse_bank()
    return ProviderResult(
        interest={"savings": b["savings_interest"], "term_deposit": b["term_deposit_interest"]},
        bank_balances=b["account_balances"],
        notes=[b["note"]])


PROVIDER = Provider(id="bank", name="Bank", category="bank", order=40, slots=_slots, parse=_parse)
