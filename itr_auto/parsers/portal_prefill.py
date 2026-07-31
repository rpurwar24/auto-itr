"""Map the e-Filing portal's raw prefill JSON (camelCase) onto the ITR-2 shapes we need.

The portal's "Download Prefill" file is camelCase (personalInfo / bankAccountDtls / ...), which
is a different format from the ITD offline-Utility export ({"ITR":{"ITR2": ...}}, PascalCase).
This lets a user upload the file they actually download from the portal: we lift identity + bank
details out of it and drop them onto a schema-built ITR-2 skeleton (see generate._load_base).

Field names map almost 1:1 by capitalising the first letter; the handful of exceptions are in
_SPECIAL. We only copy keys the target schema actually has, so stray prefill fields can't produce
an invalid document.
"""
from __future__ import annotations

import base64
from typing import Any


def _aadhaar(v: str) -> str:
    """The portal base64-encodes the Aadhaar number; decode to the raw 12 digits."""
    if isinstance(v, str) and v.isdigit() and len(v) == 12:
        return v
    try:
        dec = base64.b64decode(v).decode()
        if dec.isdigit() and len(dec) == 12:
            return dec
    except Exception:  # noqa: BLE001
        pass
    return ""

# camelCase prefill key -> ITR-2 PascalCase key (exceptions to plain first-letter capitalisation)
_SPECIAL = {"dob": "DOB", "pan": "PAN", "ifsccode": "IFSCCode",
            "emailAddressSecondary": "EmailAddressSec"}


def _pascal(k: str) -> str:
    return _SPECIAL.get(k, k[:1].upper() + k[1:])


def is_portal_prefill(data: Any) -> bool:
    """True for the portal's camelCase prefill (not the {'ITR':{'ITR2'}} Utility export)."""
    return isinstance(data, dict) and "personalInfo" in data and "ITR" not in data


def _pick(src: dict, allowed: set) -> dict:
    """Capitalise keys and keep only those the target schema allows."""
    out = {}
    for k, v in src.items():
        pk = _pascal(k)
        if pk in allowed:
            out[pk] = v
    return out


def personal_info(prefill: dict, skeleton_pi: dict) -> dict:
    """Fill a schema skeleton PersonalInfo from the prefill's personalInfo."""
    src = prefill.get("personalInfo", {})
    pi = dict(skeleton_pi)
    if isinstance(src.get("address"), dict):
        pi["Address"] = {**skeleton_pi.get("Address", {}),
                         **_pick(src["address"], set(skeleton_pi.get("Address", {})))}
    if isinstance(src.get("assesseeName"), dict):
        pi["AssesseeName"] = {**skeleton_pi.get("AssesseeName", {}),
                              **_pick(src["assesseeName"], set(skeleton_pi.get("AssesseeName", {})))}
    for k in ("dob", "pan", "status"):
        if k in src and _pascal(k) in skeleton_pi:
            pi[_pascal(k)] = src[k]
    if "aadhaarCardNo" in src and "AadhaarCardNo" in skeleton_pi:
        aad = _aadhaar(src["aadhaarCardNo"])
        if aad:
            pi["AadhaarCardNo"] = aad
        else:
            pi.pop("AadhaarCardNo", None)
    return pi


def residential_status(prefill: dict) -> str | None:
    return prefill.get("personalInfo", {}).get("filingStatus", {}).get("residentialStatus")


def _deductor(rows: Any) -> dict | None:
    if isinstance(rows, list) and rows:
        d = rows[0].get("employerOrDeductorOrCollectDetl", {}) if isinstance(rows[0], dict) else {}
        if d.get("tan"):
            return {"TAN": d["tan"], "Name": d.get("employerOrDeductorOrCollecterName", "")}
    return None


def salary_deductor(prefill: dict) -> dict | None:
    """Employer TAN + name from the prefill's Form-26AS salary-TDS section."""
    f26 = prefill.get("form26as") or {}
    return _deductor((f26.get("tdsOnSalaries") or {}).get("tdsOnSalary"))


def tcs_collector(prefill: dict) -> dict | None:
    """TCS collector TAN + name from the prefill's Form-26AS TCS section."""
    f26 = prefill.get("form26as") or {}
    return _deductor((f26.get("scheduleTCS") or {}).get("tcs"))


def bank_accounts(prefill: dict) -> list[dict]:
    """AddtnlBankDetails rows (IFSCCode/BankName/BankAccountNo/AccountType/UseForRefund)."""
    out = []
    for grp in prefill.get("bankAccountDtls") or []:
        for r in (grp.get("addtnlBankDetails") if isinstance(grp, dict) else None) or []:
            out.append({
                "IFSCCode": r.get("ifsccode", ""), "BankName": r.get("bankName", ""),
                "BankAccountNo": r.get("bankAccountNo", ""),
                "AccountType": r.get("AccountType", ""),
                "UseForRefund": r.get("useForRefund", "true")})
    return out
