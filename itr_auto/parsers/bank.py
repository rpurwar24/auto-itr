"""Parse bank documents (sources/bank/<bank>/) - interest income + year-end balances + PPF.

Per-bank folders, each PDF password-protected (passwords in config/personal.json bank_passwords:
hdfc = customer ID, sbi = mobile-last5 + dob-ddmmyy). Interest income is already authoritative
from AIS; this parser's value is (a) confirming it, (b) Mar-31 balances + FD principal for
Schedule AL, and (c) PPF interest, which is EXEMPT (Schedule EI), not taxable.

Bank PDF layouts vary a lot, so extraction is label-driven and best-effort; anything not found is
returned as None and flagged rather than guessed.
"""
from __future__ import annotations

import glob
import json
import re
from pathlib import Path
from typing import Any

from pypdf import PdfReader

from itr_auto.workspace import sources_dir, personal_json
from itr_auto import vault
BANK_DIR = sources_dir() / "bank"
PERSONAL = personal_json()


def _pw(bank: str) -> str:
    # stored encrypted (enc:...) by the app; vault.decrypt passes plaintext through unchanged
    return vault.decrypt(json.loads(PERSONAL.read_text())["bank_passwords"].get(bank, ""))


def _text(path: str, bank: str) -> str:
    r = PdfReader(path)
    if r.is_encrypted:
        r.decrypt(_pw(bank))
    return re.sub(r"[ \t]+", " ", "\n".join((p.extract_text() or "") for p in r.pages))


def _amt(pattern: str, text: str) -> float | None:
    m = re.search(pattern, text, re.I)
    return float(m.group(1).replace(",", "")) if m else None


def _statement_closing(text: str) -> float | None:
    """Closing balance from a statement summary row (HDFC and SBI layouts)."""
    # HDFC: "Opening Balance Dr Count Cr Count Debits Credits Closing Bal\n<op> <c> <c> <d> <cr> <close>"
    m = re.search(r"Closing Bal[a-z]*\s+[\d,]+\.\d{2}\s+\d+\s+\d+\s+[\d,]+\.\d{2}\s+"
                  r"[\d,]+\.\d{2}\s+([\d,]+\.\d{2})", text)
    if m:
        return float(m.group(1).replace(",", ""))
    # SBI: after "Closing Balance", the last "<amount>CR" is the closing balance
    if "Closing Balance" in text:
        crs = re.findall(r"([\d,]+\.\d{2})CR", text[text.index("Closing Balance"):])
        if crs:
            return float(crs[-1].replace(",", ""))
    return None


def _acct_key(bank: str, name: str) -> str:
    m = re.match(r"(?:hdfc|sbi)-([a-z0-9]+)", name, re.I)
    tok = m.group(1) if m else ""
    return tok if (tok.isdigit() and len(tok) == 4 and not tok.startswith("20")) else bank


def parse_bank() -> dict[str, Any]:
    accounts, fds, ppf = [], [], []
    for path in sorted(glob.glob(str(BANK_DIR / "*" / "*.pdf"))):
        bank = Path(path).name.split("-")[0].lower()
        name = Path(path).name
        t = _text(path, bank)

        if re.search(r"Deposit\(s\)/ ?Recurring", t):                 # FD / term-deposit certificate
            # "Total <principal> <> <interest> <>"
            m = re.search(r"Total\s+([\d,]+\.\d{2})\s+[\d,.]+\s+([\d,]+\.\d{2})", t)
            if m:
                fds.append({"bank": bank, "principal": float(m.group(1).replace(",", "")),
                            "interest": float(m.group(2).replace(",", ""))})
        elif "Interest Certificate" in t:                              # savings interest certificate
            accounts.append({
                "bank": bank, "file": name, "key": _acct_key(bank, name), "is_cert": True,
                "savings_interest": _amt(r"Credit Interest\s*:\s*INR\s*([\d,]+\.?\d*)", t),
                "balance_mar31": _amt(r"Balance as of 31/03/2026\s*:\s*INR\s*([\d,]+\.?\d*)", t),
            })
        else:                                                          # passbook / statement
            accounts.append({"bank": bank, "file": name, "key": _acct_key(bank, name),
                             "is_cert": False, "savings_interest": None,
                             "balance_mar31": _statement_closing(t)})
        if re.search(r"\bPPF\b", t):
            ppf.append({"bank": bank, "file": name})

    # merge cert + statement for the same account key: balance from whichever has it,
    # savings interest from the certificate
    by_key: dict[str, dict] = {}
    for a in accounts:
        cur = by_key.setdefault(a["key"], {"key": a["key"], "bank": a["bank"],
                                           "balance_mar31": None, "savings_interest": None})
        if a["balance_mar31"] is not None and cur["balance_mar31"] is None:
            cur["balance_mar31"] = a["balance_mar31"]
        if a["is_cert"] and a["savings_interest"] is not None:
            cur["savings_interest"] = a["savings_interest"]
    unique = list(by_key.values())

    savings_interest = round(sum(a["savings_interest"] or 0 for a in accounts if a["is_cert"]))
    term_interest = round(sum(f["interest"] for f in fds))
    deposits_for_al = round(sum(a["balance_mar31"] or 0 for a in unique)
                            + sum(f["principal"] for f in fds))
    return {
        "accounts": accounts, "fixed_deposits": fds, "ppf_files": ppf,
        "savings_interest": savings_interest,          # reconcile vs AIS 13,801
        "term_deposit_interest": term_interest,        # FD interest (AIS 2,032)
        "deposits_for_AL": deposits_for_al,            # Schedule AL DepositsInBank
        "account_balances": {a["key"]: a["balance_mar31"] for a in unique},
        "balances_missing": [a["key"] for a in unique if not a["balance_mar31"]],
        "note": "PPF interest is EXEMPT -> Schedule EI (not OS). Interest income taken from AIS.",
    }


if __name__ == "__main__":
    b = parse_bank()
    print(json.dumps({k: v for k, v in b.items() if k != "accounts"}, indent=2))
    print("\naccounts:")
    for a in b["accounts"]:
        print(f"  {a['bank']:4} {a['file'][:40]:40} int={a['savings_interest']} bal={a['balance_mar31']}")
