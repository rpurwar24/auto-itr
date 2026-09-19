"""End-to-end ITR-2 generator, built to conform to the official AY2026-27 schema.

Each schedule starts from a schema-derived skeleton (schema_tools.skeleton_of) so its structure
always matches the current schema, then computed values are overlaid. Personal/meta sections are
seeded from the prior filed return. The output is validated against the official schema; the
loss-adjustment/tax schedules (CYLA/BFLA/CFL) are left schema-valid for the ITD utility to
recompute on import.

Run:  .venv/bin/python -m itr_auto.generate   ->  output/ITR2_AY2026_27.json
"""
from __future__ import annotations

import argparse
import copy
import json
import math
import re
from datetime import date

from itr_auto.workspace import (sources_dir, output_dir, archive_dir,
                                 itr_inputs_json, personal_json)
from itr_auto.profile import load as load_profile
from itr_auto.parsers.itcs import parse_latest as parse_itcs
from itr_auto.parsers.ais import parse_ais
from itr_auto.schedules.schedule_s import build_schedule_s
from itr_auto.schedules.schedule_os import build_schedule_os, compute_ftc
from itr_auto.schedules.schedule_fa import build_schedule_fa
from itr_auto.schedules.schedule_si import (SI_LTCG_112, SI_LTCG_112A, SI_STCG_111A,
                                            build_schedule_si, cross_foot)
from itr_auto.parsers.vested import custodial_account as vested_custodial_account
from itr_auto.parsers.vested import schedule_fa_holdings as vested_fa_holdings
from itr_auto.compute.loss_setoff import set_off
from itr_auto.compute.interest import BUCKET_KEYS, compute_interest, cumulative_advance_tax
from itr_auto.parsers.challan import fy_end, scan_challans
from itr_auto.compute.tax import (SEC_112A_EXEMPTION, SpecialIncome, compute_tax, gross_up,
                                  marginal_slab_rate)
from itr_auto.compute.cg_pipeline import current_year_cg
from itr_auto.parsers.zerodha import parse_zerodha
from itr_auto.parsers.zerodha_taxpnl import parse_zerodha_taxpnl
from itr_auto.parsers.bank import parse_bank
from itr_auto.parsers import portal_prefill
from itr_auto.schema_tools import skeleton_of, skeleton_itr2, validate

# real portal-prefilled JSON (personal/bank/salary/TDS/TCS/OS + valid utility defaults);
# falls back to the prior filed return if the prefill isn't present.
BASE = sources_dir() / "portal" / "2025-26" / "base.json"
if not BASE.exists():
    BASE = archive_dir() / "filed_returns" / "filed_return_data_2025_26.json"
CONFIG = itr_inputs_json()
PERSONAL = personal_json()
OUT = output_dir() / "ITR2_AY2026_27.json"


def _r(x: float) -> int:
    return int(round(x))


def _round10(x: float) -> int:
    """Sec 288A/288B: total income and the final tax payable round to the nearest ten rupees.

    Half rounds UP, away from zero. Python's round() is banker's rounding, which sends
    11,191,265 down to 11,191,260 and costs the return a few rupees of tax.
    """
    return int(math.floor(abs(x) / 10.0 + 0.5) * 10) * (1 if x >= 0 else -1)



def _deep_merge(base: dict, overlay: dict) -> dict:
    for k, v in overlay.items():
        if isinstance(v, dict) and isinstance(base.get(k), dict):
            _deep_merge(base[k], v)
        else:
            base[k] = v
    return base


def _load_base(path):
    """Locate the ITR-2 template dict inside an uploaded prefill/return JSON.

    Accepts the shapes we've seen (ITD offline-Utility export / a prior ITR-2 return):
      {"ITR": {"ITR2": {...}}} | {"ITR2": {...}} | a root-level ITR-2 object.
    Anything else (an ITR-1 prefill, the portal's raw camelCase prefill, or the wrong file)
    gets a clear, actionable error instead of a cryptic KeyError deep in the pipeline.
    """
    data = json.loads(path.read_text())
    itr = data.get("ITR") if isinstance(data, dict) else None
    for cand in (itr.get("ITR2") if isinstance(itr, dict) else None,
                 data.get("ITR2") if isinstance(data, dict) else None,
                 data if isinstance(data, dict) and ("Form_ITR2" in data or "PartA_GEN1" in data) else None):
        if isinstance(cand, dict):
            return cand, {}                      # ITR-2 export/return: no extra prefill metadata
    if portal_prefill.is_portal_prefill(data):
        return _base_from_portal_prefill(data)   # the portal's raw camelCase "Download Prefill"
    if isinstance(itr, dict) and "ITR1" in itr:
        raise ValueError("This looks like an ITR-1 prefill. This tool prepares ITR-2 "
                         "(salary + capital gains + foreign assets). Start an ITR-2 in the "
                         "portal/Utility and use that prefill.")
    keys = list((itr if isinstance(itr, dict) else data).keys())[:10] if isinstance(data, dict) else type(data).__name__
    raise ValueError(
        "The uploaded Prefill JSON is not in a recognised format. "
        f"Top-level keys found: {keys}. Upload either the portal's 'Download Prefill' JSON or "
        "the ITD offline Utility's exported ITR-2 JSON.")


def _base_from_portal_prefill(prefill: dict) -> dict:
    """Build a schema-valid ITR-2 base from the portal's camelCase prefill (identity + bank).

    The bare schema skeleton leaves the non-computed metadata blocks empty, so we populate them
    with valid values here (form + software metadata are non-personal; the ITD Utility re-signs
    the Digest on Option-3 import, so ours is only a placeholder).
    """
    src = prefill.get("personalInfo", {})
    itr2 = skeleton_itr2()

    itr2["Form_ITR2"] = {
        "AssessmentYear": "2026", "SchemaVer": "Ver1.0", "FormVer": "Ver1.0", "FormName": "ITR-2",
        "Description": "For Individuals and HUFs not having income from profits and gains of "
                       "business or profession"}
    itr2["CreationInfo"] = {
        "SWVersionNo": "R1", "SWCreatedBy": "SW10000000", "JSONCreatedBy": "SW10000000",
        "JSONCreationDate": "2026-07-30", "IntermediaryCity": "Delhi", "Digest": "A" * 43 + "="}

    # ---- PersonalInfo from the prefill; prune the optional blocks the skeleton can't fill ----
    pi = portal_prefill.personal_info(prefill, skeleton_of("PartA_GEN1", "PersonalInfo", required_only=False))
    pi["SecondaryAdd"] = "N"
    pi.pop("AlternateAddress", None)                     # only when SecondaryAdd == Y
    name = pi.setdefault("AssesseeName", {})
    if name.get("MiddleName") is None:
        name["MiddleName"] = ""
    addr = pi.get("Address", {})
    addr.pop("Phone", None)                              # optional; skeleton leaves it incomplete
    for k in [k for k, v in addr.items() if v in (None, "")]:
        addr.pop(k)                                      # drop optional address fields not prefilled
    itr2["PartA_GEN1"]["PersonalInfo"] = pi

    # ---- FilingStatus: regime + residential status ----
    fs = itr2["PartA_GEN1"].setdefault("FilingStatus", {})
    fs["OptOutNewTaxRegime"] = "N"                       # new regime (default); user can change
    fs["SeventhProvisio139"] = "N"
    fs["ItrFilingDueDate"] = "2026-07-31"                # generate overwrites with the live date
    rs = portal_prefill.residential_status(prefill)
    if rs:
        fs["ResidentialStatus"] = rs

    # ---- Verification names (from the prefill) ----
    decl = itr2.setdefault("Verification", {}).setdefault("Declaration", {})
    decl["AssesseeVerName"] = src.get("assesseeVerName") or src.get("assesseeName", {}).get("firstName", "")
    decl["AssesseeVerPAN"] = src.get("assesseVerPan") or src.get("pan", "")
    decl["FatherName"] = src.get("fatherName", "")

    # ---- bank accounts for refund ----
    banks = portal_prefill.bank_accounts(prefill)
    if banks:
        itr2.setdefault("PartB_TTI", {}).setdefault("Refund", {})["BankAccountDtls"] = {
            "BankDtlsFlag": "Y", "AddtnlBankDetails": banks}
    # the prefill's Form-26AS carries the real deductor/collector TANs (for TDS1 / TCS)
    meta = {"employer": portal_prefill.salary_deductor(prefill),
            "tcs": portal_prefill.tcs_collector(prefill)}
    return itr2, meta


def _optional(fn, default):
    """Run an optional provider's producer; if its documents aren't present, contribute nothing.

    A missing file raises FileNotFoundError (most parsers) or IndexError (glob[0]); anything else
    (a present-but-corrupt file) propagates as a real error rather than being silently dropped.
    """
    try:
        return fn()
    except (FileNotFoundError, IndexError):
        return default


def _challan_rows(challans: list[dict] | None, cfg: dict, fy: str) -> list[dict]:
    """Every tax payment to claim, normalised and oldest first.

    Sources, in order of authority: what the caller passed; the receipts sitting in
    sources/portal/<fy>/; the hand-keyed `challans` block in config. The receipt wins - it is
    the department's own document - but a config entry that no receipt matches is kept, so a
    payment whose PDF was never saved is still claimed.
    """
    if challans is None:
        scanned = _optional(lambda: [c.as_dict() for c in scan_challans(fy)], [])
        keys = {(str(c["bsr_code"]), int(c["serial"]), c["date"]) for c in scanned}
        extra = [c for c in (cfg.get("challans") or [])
                 if (str(c["bsr_code"]), int(c["serial"]), c["date"]) not in keys]
        challans = scanned + extra
    rows, seen = [], set()
    for c in challans:
        row = {"bsr_code": str(c["bsr_code"]), "serial": int(c["serial"]),
               "date": date.fromisoformat(c["date"]), "amount": _r(c["amount"])}
        key = (row["bsr_code"], row["serial"], row["date"])
        if key in seen:
            raise ValueError(f"challan {row['bsr_code']}/{row['serial']:05d} of "
                             f"{row['date']} is listed twice - it would be claimed as a "
                             f"duplicate credit the department cannot match")
        seen.add(key)
        rows.append(row)
    return sorted(rows, key=lambda r: (r["date"], r["serial"]))


def build(as_of: date | None = None, filing_date: date | None = None,
          challans: list[dict] | None = None, revises: dict | None = None) -> tuple[dict, dict]:
    """`as_of` is the date the tax is taken to be PAID on: 234B runs to it, so the balance
    payable the generator reports is the balance payable if you pay that day. Defaults to today.

    `filing_date` is when the return is/was FILED, which is what 234A keys off. It falls back
    to config's `filed_on` and then to `as_of` (a return generated today is a return filed
    today). Once the return has actually gone in, set `filed_on` - otherwise re-running this
    after the due date invents a 234A that is not owed.

    `challans` are self-assessment tax payments already made, each
    {bsr_code, serial, date, amount}; they fall back to config's `challans`. They are CLAIMED
    in Schedule IT and credited in PartB-TTI, which a return filed before paying cannot do.

    `revises` makes this a return u/s 139(5): {acknowledgement, original_filed_on} from the
    ORIGINAL return. It is NOT read from config by default - intent has to be stated by the
    caller (the CLI's --revised), so a stale config block can never quietly turn an original
    filing into a revision of something.
    """
    as_of = as_of or date.today()
    cfg = json.loads(CONFIG.read_text())
    if filing_date is None:
        filing_date = date.fromisoformat(cfg["filed_on"]) if cfg.get("filed_on") else as_of
    fy = cfg["fy"]
    challan_rows = _challan_rows(challans, cfg, fy)
    # assessment year is the year the FY ends in ("2025-26" -> "2026"); derive it so the
    # config need not carry it (the UI form doesn't, and it must never be a required field).
    ay = str(cfg.get("assessment_year") or (int(fy.split("-")[0]) + 1))
    us_tin = json.loads(PERSONAL.read_text())["us_tin"]
    prof = load_profile()                        # employer / TCS collector / foreign country
    ais = parse_ais()                            # AIS = authoritative for TDS/TCS/interest/dividend
    salary_tds, lrs_tcs = ais["salary_tds"], ais["lrs_tcs"]
    savings_interest = ais["savings_bank_interest"]
    term_deposit_interest = ais["term_deposit_interest"]
    domestic_dividend = ais["domestic_dividend"]
    # foreign RSU/ESPP sales (E*TRADE G&L + ESOP statements) - absent for a user with no RSUs
    _ZERO_CG = {"stcg": 0, "ltcg": 0, "lt_proceeds": 0, "lt_cost": 0,
                "st_proceeds": 0, "st_cost": 0, "lots": []}
    cgp = _optional(lambda: current_year_cg(fy), _ZERO_CG)
    # Derive gains as (rounded consideration - rounded cost) so our BalanceCG / set-off / accrual match
    # how the Utility recomputes them (it does FullConsideration - TotalDedn; summing per-lot rounded
    # gains drifts by ~Re1 and re-triggers the "Table F != BFLA 3vii" validation).
    stcg = _r(cgp["st_proceeds"]) - _r(cgp["st_cost"])
    ltcg_gross = _r(cgp["lt_proceeds"]) - _r(cgp["lt_cost"])
    # domestic equity-MF (Zerodha Tax P&L) - absent for a user with no Zerodha account
    _ZERO_DOM = {"stcg_111A": {"sale": 0, "cost": 0}, "ltcg_112A": {"sale": 0, "cost": 0}}
    dom = _optional(parse_zerodha_taxpnl, _ZERO_DOM)
    d_stcg_sale = _r(dom["stcg_111A"]["sale"]); d_stcg_cost = _r(dom["stcg_111A"]["cost"]); d_stcg = d_stcg_sale - d_stcg_cost
    d_ltcg_sale = _r(dom["ltcg_112A"]["sale"]); d_ltcg_cost = _r(dom["ltcg_112A"]["cost"]); d_ltcg = d_ltcg_sale - d_ltcg_cost

    prior, pmeta = _load_base(BASE)
    itr = copy.deepcopy(prior)                 # start from the real prefill (keeps personal/bank/defaults)
    itr["Form_ITR2"]["AssessmentYear"] = ay
    itr.setdefault("CreationInfo", {})["JSONCreationDate"] = "2026-07-30"
    itr["PartA_GEN1"]["FilingStatus"]["ItrFilingDueDate"] = "2026-07-31"

    # Revising: declare it in the JSON itself, so the Utility imports it as a revised return
    # instead of a fresh 139(1) that then has to be re-pointed by hand.
    if revises:
        itr["PartA_GEN1"]["FilingStatus"].update({
            "ReturnFileSec": 17,                       # 17 = 139(5) revised
            "ReceiptNo": str(revises["acknowledgement"]),
            "OrigRetFiledDate": revises["original_filed_on"]})

    # employer + TCS collector: prefer the prefill's real Form-26AS TANs, else the profile.
    # (the profile defaults are non-real placeholders, so we won't emit a schedule with a fake TAN.)
    _PLACEHOLDER_TANS = {"AAAA00000A", "BBBB00000B"}
    employer = dict(prof["employer"])
    if pmeta.get("employer"):
        employer["TANofEmployer"] = pmeta["employer"]["TAN"]
        employer["NameOfEmployer"] = pmeta["employer"]["Name"] or employer["NameOfEmployer"]
    tcs_tan = (pmeta.get("tcs") or {}).get("TAN") or prof["tcs_collector_tan"]

    # ---- income schedules ----
    itcs = parse_itcs()
    itr["ScheduleS"] = build_schedule_s(itcs, employer=employer)
    os_built = build_schedule_os(fy, savings_interest, domestic_dividend, term_deposit_interest)
    os_built.pop("_notes", None)
    os_sk = skeleton_of("ScheduleOS", required_only=False)      # full -> all required fields
    os_sk.get("IncOthThanOwnRaceHorse", {}).pop("IncChargblSplRateOS", None)  # optional NRI block
    itr["ScheduleOS"] = _deep_merge(os_sk, os_built)
    # 234C: dividend quarterly breakup (DividendIncUs115BBDA) must sum to DividendGross.
    # os_built carries the foreign-dividend quarters (from Vested dates); add domestic dividend.
    itr["ScheduleOS"]["DividendIncUs115BBDA"]["DateRange"]["Upto15Of6"] += domestic_dividend
    # Schedule FA is on a CALENDAR-year basis: the return for FY YYYY-(YY+1) discloses the calendar
    # year ending inside it (FY2025-26 -> CY2025). Derive it from fy so this isn't pinned to one year.
    fa_cy = int(fy.split("-")[0])
    fa = build_schedule_fa(fa_cy, vested_fy=fy)
    itr["ScheduleFA"] = fa["ScheduleFA"]
    # Table A2 - foreign custodial account (only if the user has a Vested/DriveWealth account)
    ca = _optional(vested_custodial_account, None)
    vh = _optional(vested_fa_holdings, [])
    if ca and vh:
        itr["ScheduleFA"]["DtlsForeignCustodialAcc"] = [{
            "CountryName": prof["foreign_custodial_country_name"],
            "CountryCodeExcludingIndia": prof["foreign_country_code"],
            "FinancialInstName": ca["institution"], "FinancialInstAddress": ca["address"],
            "ZipCode": ca["zip"], "AccountNumber": ca["account_number"], "Status": "OWNER",
            "AccOpenDate": ca["opened"],
            "PeakBalanceDuringPeriod": _r(sum(h["peak_inr"] for h in vh)),
            "ClosingBalance": _r(sum(h["closing_inr"] for h in vh)),
            "GrossAmtPaidCredited": _r(sum(h.get("gross_paid_inr", 0) for h in vh)),
            "NatureOfAmount": "D"}]

    # Set-off (Sec 70/74): net STCG (foreign loss + domestic 111A) sets off against net LTCG.
    so = set_off(stcg=stcg + d_stcg, ltcg=ltcg_gross + d_ltcg)
    taxable_cg = _r(so.taxable_ltcg)                 # net CG after intra-head set-off
    taxable_ltcg = _r(so.taxable_ltcg)

    has_f_st = bool(_r(cgp["st_proceeds"]) or _r(cgp["st_cost"]))   # foreign STCG present
    has_f_lt = bool(_r(cgp["lt_proceeds"]) or _r(cgp["lt_cost"]))   # foreign LTCG present
    has_d_st = bool(d_stcg_sale or d_stcg_cost)                     # domestic 111A present
    has_d_lt = bool(d_ltcg_sale or d_ltcg_cost)                     # domestic 112A present

    def _ded(cost):
        return {"AquisitCost": cost, "ImproveCost": 0, "ExpOnTrans": 0, "TotalDedn": cost}

    if has_f_st or has_f_lt or has_d_st or has_d_lt:
        cg = skeleton_of("ScheduleCGFor23")
        st = cg["ShortTermCapGainFor23"]
        if has_f_st:
            # foreign STCG - resident "sale of other assets" (slab). FullConsideration is COMPUTED
            # (= sum of the Consd sub-fields); proceeds MUST go into FullValueConsdOthUnqshr or the
            # Utility recomputes FullConsideration=0 and inverts it to a loss.
            st["SaleOnOtherAssets"] = {**st.get("SaleOnOtherAssets", {}),
                                       "FullValueConsdRecvUnqshr": 0, "FairMrktValueUnqshr": 0, "FullValueConsdSec50CA": 0,
                                       "FullValueConsdOthUnqshr": cgp["st_proceeds"], "FullConsideration": cgp["st_proceeds"],
                                       "DeductSec48": _ded(cgp["st_cost"]), "BalanceCG": _r(stcg), "CapgainonAssets": _r(stcg)}
        if has_d_st:
            # domestic equity-MF STCG u/s 111A (20%)
            st["EquityMFonSTT"] = [{"MFSectionCode": "1A", "EquityMFonSTTDtls": {
                "FullConsideration": d_stcg_sale, "DeductSec48": _ded(d_stcg_cost),
                "BalanceCG": d_stcg, "LossSec94of7Or94of8": 0, "CapgainonAssets": d_stcg}}]
        st["TotalSTCG"] = (_r(stcg) if has_f_st else 0) + (d_stcg if has_d_st else 0)

        lt = cg["LongTermCapGain23"]
        if has_f_lt:
            # foreign shares LTCG u/s 112 @12.5% - resident "sale of asset" block
            lt["SaleofAssetNADtls"] = {"SaleofAssetNA": {
                "FullValueConsdRecvUnqshr": 0, "FairMrktValueUnqshr": 0, "FullValueConsdSec50CA": 0,
                "FullValueConsdOthUnqshr": cgp["lt_proceeds"], "FullConsideration": cgp["lt_proceeds"],
                "DeductSec48": _ded(cgp["lt_cost"]), "BalanceCG": _r(ltcg_gross),
                "DeductionUs54F": 0, "CapgainonAssets": _r(ltcg_gross)}}
        if has_d_lt:
            # domestic equity-MF LTCG u/s 112A (12.5%, first 1.25L exempt)
            lt["SaleOfEquityShareUs112A"] = {"BalanceCG": d_ltcg, "DeductionUs54F": 0, "CapgainonAssets": d_ltcg}
        lt["TotalLTCG"] = (_r(ltcg_gross) if has_f_lt else 0) + (d_ltcg if has_d_lt else 0)

        cg["SumOfCGIncm"] = taxable_cg
        cg["TotScheduleCGFor23"] = taxable_cg
        # Table F (234C): LTCG @12.5% accrual must equal BFLA 3vii (= net LTCG after set-off).
        cg["AccruOrRecOfCG"]["LongTermUnder12_5Per"]["DateRange"]["Up16Of9To15Of12"] = taxable_cg
        itr["ScheduleCGFor23"] = cg

        if has_d_lt:
            # Schedule 112A (domestic equity-MF LTCG line items)
            itr["Schedule112A"] = {
                "SaleValue112A": d_ltcg_sale, "CostAcqWithoutIndx112A": d_ltcg_cost, "AcquisitionCost112A": d_ltcg_cost,
                "LTCGBeforelowerB1B2112A": d_ltcg, "FairMktValueCapAst112A": 0, "ExpExclCnctTransfer112A": 0,
                "Deductions112A": d_ltcg_cost, "Balance112A": d_ltcg, "TotalBalance112A": d_ltcg,
                "Schedule112ADtls": [{
                    "ShareOnOrBefore": "AE", "ISINCode": "INNOTREQUIRD", "ShareUnitName": "CONSOLIDATED",
                    "NumSharesUnits": 0, "SalePricePerShareUnit": 0, "TotSaleValue": d_ltcg_sale,
                    "CostAcqWithoutIndx": d_ltcg_cost, "AcquisitionCost": d_ltcg_cost, "LTCGBeforelowerB1B2": d_ltcg,
                    "FairMktValuePerShareunit": 0, "TotFairMktValueCapAst": 0, "ExpExclCnctTransfer": 0,
                    "TotalDeductions": d_ltcg_cost, "Balance": d_ltcg}]}
        else:
            itr.pop("Schedule112A", None)
    else:
        itr.pop("ScheduleCGFor23", None)   # no capital gains at all
        itr.pop("Schedule112A", None)

    # ---- foreign tax credit: FSI + TR1 (only if there is foreign income to claim credit on) ----
    ftc = compute_ftc(fy, tin=us_tin)            # returns zeros if no Vested/foreign workbook
    if ftc["income_inr"] > 0:
        othsrc = {"IncFrmOutsideInd": ftc["income_inr"], "TaxPaidOutsideInd": ftc["tax_paid_outside_inr"],
                  "TaxPayableinInd": ftc["tax_payable_india_inr"], "TaxReliefinInd": ftc["relief_inr"],
                  "DTAAReliefUs90or90A": "90"}
        zero_head = {"IncFrmOutsideInd": 0, "TaxPaidOutsideInd": 0, "TaxPayableinInd": 0,
                     "TaxReliefinInd": 0, "DTAAReliefUs90or90A": "90"}
        total = {k: v for k, v in othsrc.items() if k != "DTAAReliefUs90or90A"}
        itr["ScheduleFSI"] = {"ScheduleFSIDtls": [{
            "CountryName": prof["foreign_country_name"],
            "CountryCodeExcludingIndia": prof["foreign_country_code"],
            "TaxIdentificationNo": us_tin, "IncFromSal": dict(zero_head),
            "IncFromHP": dict(zero_head), "IncCapGain": dict(zero_head),
            "IncOthSrc": othsrc, "TotalCountryWise": total}]}
        itr["ScheduleTR1"] = {
            "ScheduleTR": [{"CountryName": prof["foreign_country_name"],
                            "CountryCodeExcludingIndia": prof["foreign_country_code"],
                            "TaxIdentificationNo": us_tin,
                            "TaxPaidOutsideIndia": ftc["tax_paid_outside_inr"],
                            "TaxReliefOutsideIndia": ftc["relief_inr"],
                            "ReliefClaimedUsSection": "90"}],
            "TotalTaxPaidOutsideIndia": ftc["tax_paid_outside_inr"],
            "TotalTaxReliefOutsideIndia": ftc["relief_inr"],
            "TaxReliefOutsideIndiaDTAA": ftc["relief_inr"], "TaxReliefOutsideIndiaNotDTAA": 0,
            # Q4: was the foreign tax (on which relief is claimed) REFUNDED/credited back by the
            # foreign authority during the year? It was not - the US 15% WHT stays withheld. So "NO",
            # and the refund sub-fields (AmtTaxRefunded / AssmtYrTaxRelief) don't apply.
            "TaxPaidOutsideIndFlg": "NO"}
    else:
        itr.pop("ScheduleFSI", None)
        itr.pop("ScheduleTR1", None)

    # ---- taxes paid ---- (emit only with a real deductor/collector TAN, never a placeholder)
    if salary_tds and employer["TANofEmployer"] not in _PLACEHOLDER_TANS:
        itr["ScheduleTDS1"] = {"TDSonSalary": [{
            "EmployerOrDeductorOrCollectDetl": {"TAN": employer["TANofEmployer"],
                "EmployerOrDeductorOrCollecterName": employer["NameOfEmployer"]},
            "IncChrgSal": _r(itcs["income_under_salary"]), "TotalTDSSal": salary_tds}],
            "TotalTDSonSalaries": salary_tds}
    else:
        itr.pop("ScheduleTDS1", None)
    if lrs_tcs and tcs_tan not in _PLACEHOLDER_TANS:
        itr["ScheduleTCS"] = {"TCS": [{
            "EmployerOrDeductorOrCollectTAN": tcs_tan, "TCSCreditOwner": "1",
            "TCSCurrFYDtls": {"TCSAmtCollOwnHand": lrs_tcs, "TCSAmtCollSpouseOrOthrHand": 0},
            "TCSClaimedThisYearDtls": {"TCSAmtCollOwnHand": lrs_tcs, "TCSAmtCollSpouseOrOthrHand": 0},
            "AmtCarriedFwd": 0}], "TotalSchTCS": lrs_tcs}
    else:
        itr.pop("ScheduleTCS", None)          # no LRS remittance / no real collector TAN -> no TCS

    # ---- Schedule AL: shares = foreign (FA closing) + Indian (Zerodha); deposits = bank + FD ----
    # (AL is only mandatory when total income > 50L; build it only if the prefill carries it)
    foreign_shares = sum(r["ClosingBalance"] for r in fa["ScheduleFA"]["DtlsForeignEquityDebtInterest"])
    zh = _optional(parse_zerodha, {"holdings_market_value": 0})
    bk = parse_bank()
    if "ScheduleAL" in prior:
        al = copy.deepcopy(prior["ScheduleAL"])
        al["MovableAsset"]["SharesAndSecurities"] = _r(foreign_shares + zh["holdings_market_value"])
        al["MovableAsset"]["DepositsInBank"] = bk["deposits_for_AL"]   # HDFC savings + FD (+ 4766/SBI: manual)
        al.pop("ImmovableDetails", None)   # "Do you own immovable asset?" is UI-only; user picks "No"
        itr["ScheduleAL"] = al

    # foreign-asset question: YES only if there are foreign assets/income (drop empty FA otherwise)
    fa_rows = itr.get("ScheduleFA", {}).get("DtlsForeignEquityDebtInterest", [])
    has_foreign = bool(fa_rows) or ftc["income_inr"] > 0 or bool(ca and vh)
    if not has_foreign:
        itr.pop("ScheduleFA", None)

    # ---- PartB-TI ----
    salary = _r(itcs["income_under_salary"])
    os_inc = itr["ScheduleOS"]["TotOthSrcNoRaceHorse"]
    taxable_stcg = _r(so.taxable_stcg)

    # Split the post-set-off gains by the rate they actually bear. A single blended CG number
    # over-taxes: sec 112A carries a 1.25L exemption that sec 112 does not, and STCG u/s 111A
    # is 20% while foreign STCG is slab. The set-off is applied to the dearer bucket first
    # (fully-taxable 112 before 112A, slab-rate STCG before 111A) so relief is not wasted on
    # income that would not have been taxed anyway - which is also what the Utility does.
    lt_112 = max(0, taxable_ltcg - _r(d_ltcg))
    lt_112a = taxable_ltcg - lt_112
    st_slab = max(0, taxable_stcg - _r(d_stcg))
    st_111a = taxable_stcg - st_slab

    special = [s for s in (
        SpecialIncome(code=SI_LTCG_112, income=lt_112, rate=0.125),
        SpecialIncome(code=SI_LTCG_112A, income=lt_112a, rate=0.125,
                      exempt=SEC_112A_EXEMPTION[fy]),
        SpecialIncome(code=SI_STCG_111A, income=st_111a, rate=0.20),
    ) if s.income > 0]
    special_income = sum(s.income for s in special)

    gti = salary + taxable_ltcg + taxable_stcg + os_inc
    total_income = _round10(gti)                      # sec 288A
    normal_income = total_income - special_income     # slab-rate part carries the rounding
    itr["PartB-TI"] = _deep_merge(skeleton_of("PartB-TI"), {
        "Salaries": salary, "IncomeFromHP": 0,
        "CapGain": {"LongTerm": {"LongTerm12_5Per": taxable_ltcg, "LongTermSplRateDTAA": 0,
                                 "TotalLongTerm": taxable_ltcg},
                    "ShortTerm": {"ShortTerm20Per": st_111a, "ShortTermAppRate": st_slab,
                                  "TotalShortTerm": taxable_stcg},
                    "ShortTermLongTermTotal": taxable_ltcg + taxable_stcg,
                    "TotalCapGains": taxable_ltcg + taxable_stcg},
        "IncFromOS": {"TotIncFromOS": os_inc, "OtherSrcThanOwnRaceHorse": os_inc},
        # TotalTI / BalanceAfterSetoffLosses / IncChargeTaxSplRate111A112 were left at the
        # skeleton's zero while GrossTotalIncome carried the real figure - internally
        # inconsistent, and only invisible because the Utility refills them on import.
        "TotalTI": gti, "BalanceAfterSetoffLosses": gti, "BroughtFwdLossesSetoff": 0,
        "GrossTotalIncome": gti, "TotalIncome": total_income,
        "IncChargeTaxSplRate111A112": special_income,
        "IncChargeableTaxSplRates": special_income, "AggregateIncome": normal_income})

    # ---- PartB-TTI (tax) ----
    tr = compute_tax(normal_income, special, fy)
    relief = ftc["relief_inr"]
    total_paid = salary_tds + lrs_tcs
    net_liability = tr.gross_tax - relief

    # ScheduleSI is built from the very rows that produced the tax, then cross-footed against
    # PartB-TI and PartB-TTI. Emitting it empty (as we used to) let a special-rate mistake ship.
    itr["ScheduleSI"] = build_schedule_si(tr.special_rows, base=prior.get("ScheduleSI"))
    cross_foot(itr["ScheduleSI"], special_income=special_income, tax_special=tr.tax_special)

    # ---- tax already paid: advance tax, and self-assessment tax ----
    # Schedule IT is ONE table for both (the schema's TaxPayment has no minor-head field), so
    # what separates them is the date: inside the financial year it is advance tax, after
    # 31 March it is self-assessment tax. They are not interchangeable to the interest below.
    advance_rows = [r for r in challan_rows if r["date"] <= fy_end(fy)]
    sa_rows = [r for r in challan_rows if r["date"] > fy_end(fy)]
    advance_tax = sum(r["amount"] for r in advance_rows)
    self_assessment = sum(r["amount"] for r in sa_rows)
    if len(sa_rows) > 1:
        raise ValueError(
            f"more than one self-assessment payment ({len(sa_rows)}). Sec 234B(2) recomputes "
            "the interest at each one, on the amount then outstanding; that slab calculation "
            "has never been checked against the Utility, so it is refused rather than guessed.")

    # ---- interest u/s 234A/B/C ----
    # Assessed tax: tax on the returned income after relief, less TDS and TCS - and BEFORE
    # advance tax, which each section then applies differently (see compute_interest).
    assessed_tax = net_liability - total_paid
    gu_special, gu_normal = gross_up(total_income, fy, special=True), gross_up(total_income, fy)
    marginal = marginal_slab_rate(normal_income, fy)
    # 234C's proviso prices WHEN the capital gain and dividend income arose, so attribute the
    # tax on each to the quarterly accrual buckets the CG and OS schedules already declare.
    cg_accrual = (itr.get("ScheduleCGFor23", {}).get("AccruOrRecOfCG", {})
                     .get("LongTermUnder12_5Per", {}).get("DateRange", {}))
    dividends = itr["ScheduleOS"]["DividendIncUs115BBDA"]["DateRange"]
    deferrable = {}
    for bucket, key in enumerate(BUCKET_KEYS, start=1):
        cg_tax = (tr.tax_special * cg_accrual.get(key, 0) / special_income) if special_income else 0
        deferrable[bucket] = cg_tax * gu_special + dividends.get(key, 0) * marginal * gu_normal
    due_date = date.fromisoformat(itr["PartA_GEN1"]["FilingStatus"]["ItrFilingDueDate"])
    interest = compute_interest(
        assessed_tax, ay_start_year=int(ay), as_of=as_of,
        due_date=due_date,
        filing_date=filing_date,
        deferrable_tax=deferrable,
        advance_tax=advance_tax,
        advance_paid=cumulative_advance_tax([(r["date"], r["amount"]) for r in advance_rows], fy),
        # proviso to sec 234A(1): tax paid u/s 140A before the due date reduces that base too
        paid_before_due_date=sum(r["amount"] for r in sa_rows if r["date"] <= due_date))

    aggregate = net_liability + interest.total

    # ---- Schedule IT ----
    if challan_rows:
        itr["ScheduleIT"] = {
            "TaxPayment": [{"BSRCode": r["bsr_code"], "DateDep": r["date"].isoformat(),
                            "SrlNoOfChaln": r["serial"], "Amt": r["amount"]}
                           for r in challan_rows],
            "TotalTaxPayments": _r(advance_tax + self_assessment)}
        # cross-foot: the schedule's detail and PartB-TTI's two credit lines are built from
        # the same rows, so they must agree. (The Utility recomputes the split from the dates
        # on import - if ours disagreed, one of the two would silently lose a payment.)
        if itr["ScheduleIT"]["TotalTaxPayments"] != advance_tax + self_assessment:
            raise ValueError("Schedule IT does not foot to the advance / self-assessment split")
    else:
        itr.pop("ScheduleIT", None)

    credits = total_paid + advance_tax + self_assessment
    bal = _round10(aggregate - credits)                # sec 288B
    itr["PartB_TTI"] = _deep_merge(skeleton_of("PartB_TTI"), {
        "AssetOutIndiaFlag": "YES" if has_foreign else "NO",
        "ComputationOfTaxLiability": {
            "TaxPayableOnTI": {"TaxAtNormalRatesOnAggrInc": tr.tax_normal,
                "TaxAtSpecialRates": tr.tax_special, "RebateOnAgriInc": 0,
                "TaxPayableOnTotInc": tr.tax_normal + tr.tax_special},
            "TaxPayableOnRebate": tr.tax_normal + tr.tax_special, "Rebate87A": 0,
            "TotalSurcharge": tr.surcharge, "SurchargeOnAboveCrore": tr.surcharge,
            "EducationCess": tr.cess, "GrossTaxLiability": tr.gross_tax,
            "GrossTaxPayable": tr.gross_tax, "TaxPayAfterCreditUs115JD": tr.gross_tax,
            "TaxRelief": {"Section89": 0, "Section90": relief, "Section91": 0,
                          "TotTaxRelief": relief},
            "NetTaxLiability": net_liability,
            "IntrstPay": {"IntrstPayUs234A": interest.us_234a,
                          "IntrstPayUs234B": interest.us_234b,
                          "IntrstPayUs234C": interest.us_234c, "LateFilingFee234F": 0,
                          "TotalIntrstPay": interest.total},
            "AggregateTaxInterestLiability": aggregate},
        "TaxPaid": {"TaxesPaid": {"AdvanceTax": advance_tax, "SelfAssessmentTax": self_assessment,
            "TDS": salary_tds, "TCS": lrs_tcs, "TotalTaxesPaid": credits},
            "BalTaxPayable": max(0, bal)},
        "Refund": {"RefundDue": max(0, -bal),
                   "BankAccountDtls": prior.get("PartB_TTI", {}).get("Refund", {}).get("BankAccountDtls", [])}})

    summary = {"salary": salary, "capital_gains": taxable_ltcg, "other_sources": os_inc,
               "gross_total_income": gti, "gross_tax": tr.gross_tax, "ftc_relief": relief,
               "tds": salary_tds, "tcs": lrs_tcs, "advance_tax": advance_tax,
               "self_assessment_tax": self_assessment,
               # net_tax_payable is the assessed TAX - after relief, TDS and TCS, but before
               # advance tax and before interest. balance_payable is what you hand over at
               # the counter: that, plus the interest for not having paid it when it fell due,
               # less every challan already paid.
               "net_tax_payable": assessed_tax,
               "interest_234a": interest.us_234a, "interest_234b": interest.us_234b,
               "interest_234c": interest.us_234c,
               "balance_payable": max(0, bal), "payable_as_of": as_of.isoformat(),
               "fa_rows": fa["_counts"],
               "GAP_indian_mf_sale_value": ais["indian_mf_sale_value"]}
    return {"ITR": {"ITR2": itr}}, summary


_ACK_RE = re.compile(r"^\d{15}$")


def _revision_from(args, cfg: dict) -> dict:
    """Resolve --revised into {acknowledgement, original_filed_on}, or {} for an original.

    The FLAG decides, config only supplies the data. Validated here rather than left to schema
    validation, so a typo'd acknowledgement fails at the command line with a readable message
    instead of 40 lines of Draft4 output.
    """
    if not args.revised:
        return {}
    src = cfg.get("revises") or {}
    ack = str(args.ack or src.get("acknowledgement") or "")
    orig = args.original_filed_on or src.get("original_filed_on") or ""
    if not _ACK_RE.match(ack):
        raise SystemExit(
            f"--revised needs the ORIGINAL return's 15-digit acknowledgement number, got {ack!r}.\n"
            f"Pass --ack, or put it in {CONFIG} under \"revises\".")
    try:
        date.fromisoformat(orig)
    except ValueError:
        raise SystemExit(f"--revised needs the original filing date as YYYY-MM-DD, got {orig!r}")
    return {"acknowledgement": ack, "original_filed_on": orig}


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(
        prog="python -m itr_auto.generate",
        description="Build the ITR-2 JSON. Feed the result to the ITD offline Utility "
                    "(Import Pre-fill Data -> Option 3), which validates and re-signs it; "
                    "the Utility's export is what the portal accepts.")
    mode = ap.add_mutually_exclusive_group()
    mode.add_argument("--original", action="store_true", default=True,
                      help="fresh return u/s 139(1) (default)")
    mode.add_argument("--revised", action="store_true",
                      help="return u/s 139(5) revising an already-filed one")
    ap.add_argument("--ack", help="original return's 15-digit acknowledgement (with --revised)")
    ap.add_argument("--original-filed-on", metavar="YYYY-MM-DD",
                    help="date the original return was filed (with --revised)")
    ap.add_argument("--as-of", metavar="YYYY-MM-DD",
                    help="date the tax is taken to be PAID on; 234B runs to it (default: today)")
    args = ap.parse_args(argv)

    cfg = json.loads(CONFIG.read_text())
    revises = _revision_from(args, cfg)
    as_of = date.fromisoformat(args.as_of) if args.as_of else None

    itr, summary = build(as_of=as_of, revises=revises)
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(itr, indent=2, ensure_ascii=False))
    errors = validate(itr["ITR"]["ITR2"])
    print(f"wrote {OUT}")
    if revises:
        print(f"  MODE                : REVISED u/s 139(5) of ack {revises['acknowledgement']} "
              f"filed {revises['original_filed_on']}")
    else:
        print("  MODE                : ORIGINAL u/s 139(1)")
    for k, v in summary.items():
        print(f"  {k:20}: {v:,}" if isinstance(v, int) else f"  {k:20}: {v}")
    print(f"\nschema validation errors: {len(errors)}")
    for e in errors[:25]:
        print("  " + e)


if __name__ == "__main__":
    main()
