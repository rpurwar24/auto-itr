"""End-to-end ITR-2 generator, built to conform to the official AY2026-27 schema.

Each schedule starts from a schema-derived skeleton (schema_tools.skeleton_of) so its structure
always matches the current schema, then computed values are overlaid. Personal/meta sections are
seeded from the prior filed return. The output is validated against the official schema; the
loss-adjustment/tax schedules (CYLA/BFLA/CFL) are left schema-valid for the ITD utility to
recompute on import.

Run:  .venv/bin/python -m itr_auto.generate   ->  output/ITR2_AY2026_27.json
"""
from __future__ import annotations

import copy
import json

from itr_auto.workspace import (sources_dir, output_dir, archive_dir,
                                 itr_inputs_json, personal_json)
from itr_auto.profile import load as load_profile
from itr_auto.parsers.itcs import parse_latest as parse_itcs
from itr_auto.parsers.ais import parse_ais
from itr_auto.schedules.schedule_s import build_schedule_s
from itr_auto.schedules.schedule_os import build_schedule_os, compute_ftc
from itr_auto.schedules.schedule_fa import build_schedule_fa
from itr_auto.parsers.vested import custodial_account as vested_custodial_account
from itr_auto.parsers.vested import schedule_fa_holdings as vested_fa_holdings
from itr_auto.compute.loss_setoff import set_off
from itr_auto.compute.tax import compute_tax
from itr_auto.compute.cg_pipeline import current_year_cg
from itr_auto.parsers.zerodha import parse_zerodha
from itr_auto.parsers.zerodha_taxpnl import parse_zerodha_taxpnl
from itr_auto.parsers.bank import parse_bank
from itr_auto.schema_tools import skeleton_of, validate

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


def _deep_merge(base: dict, overlay: dict) -> dict:
    for k, v in overlay.items():
        if isinstance(v, dict) and isinstance(base.get(k), dict):
            _deep_merge(base[k], v)
        else:
            base[k] = v
    return base


def build() -> tuple[dict, dict]:
    cfg = json.loads(CONFIG.read_text())
    fy, ay = cfg["fy"], cfg["assessment_year"]
    us_tin = json.loads(PERSONAL.read_text())["us_tin"]
    prof = load_profile()                        # employer / TCS collector / foreign country
    ais = parse_ais()                            # AIS = authoritative for TDS/TCS/interest/dividend
    salary_tds, lrs_tcs = ais["salary_tds"], ais["lrs_tcs"]
    savings_interest = ais["savings_bank_interest"]
    term_deposit_interest = ais["term_deposit_interest"]
    domestic_dividend = ais["domestic_dividend"]
    cgp = current_year_cg(fy)                    # auto-computed foreign STCG / LTCG (no hardcoding)
    # Derive gains as (rounded consideration - rounded cost) so our BalanceCG / set-off / accrual match
    # how the Utility recomputes them (it does FullConsideration - TotalDedn; summing per-lot rounded
    # gains drifts by ~Re1 and re-triggers the "Table F != BFLA 3vii" validation).
    stcg = _r(cgp["st_proceeds"]) - _r(cgp["st_cost"])
    ltcg_gross = _r(cgp["lt_proceeds"]) - _r(cgp["lt_cost"])
    dom = parse_zerodha_taxpnl()                 # domestic equity-MF: STCG 111A + LTCG 112A
    d_stcg_sale = _r(dom["stcg_111A"]["sale"]); d_stcg_cost = _r(dom["stcg_111A"]["cost"]); d_stcg = d_stcg_sale - d_stcg_cost
    d_ltcg_sale = _r(dom["ltcg_112A"]["sale"]); d_ltcg_cost = _r(dom["ltcg_112A"]["cost"]); d_ltcg = d_ltcg_sale - d_ltcg_cost

    prior = json.loads(BASE.read_text())["ITR"]["ITR2"]
    itr = copy.deepcopy(prior)                 # start from the real prefill (keeps personal/bank/defaults)
    itr["Form_ITR2"]["AssessmentYear"] = ay
    itr["CreationInfo"]["JSONCreationDate"] = "2026-07-30"
    itr["PartA_GEN1"]["FilingStatus"]["ItrFilingDueDate"] = "2026-07-31"

    # ---- income schedules ----
    itcs = parse_itcs()
    itr["ScheduleS"] = build_schedule_s(itcs)
    os_built = build_schedule_os(fy, savings_interest, domestic_dividend, term_deposit_interest)
    os_built.pop("_notes", None)
    os_sk = skeleton_of("ScheduleOS", required_only=False)      # full -> all required fields
    os_sk.get("IncOthThanOwnRaceHorse", {}).pop("IncChargblSplRateOS", None)  # optional NRI block
    itr["ScheduleOS"] = _deep_merge(os_sk, os_built)
    # 234C: dividend quarterly breakup (DividendIncUs115BBDA) must sum to DividendGross.
    # os_built carries the foreign-dividend quarters (from Vested dates); add domestic dividend.
    itr["ScheduleOS"]["DividendIncUs115BBDA"]["DateRange"]["Upto15Of6"] += domestic_dividend
    fa = build_schedule_fa(2025)
    itr["ScheduleFA"] = fa["ScheduleFA"]
    # Table A2 - foreign custodial account (DriveWealth); A3-only builder omits it
    ca = vested_custodial_account()
    vh = vested_fa_holdings()
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

    def _ded(cost):
        return {"AquisitCost": cost, "ImproveCost": 0, "ExpOnTrans": 0, "TotalDedn": cost}

    cg = skeleton_of("ScheduleCGFor23")
    st = cg["ShortTermCapGainFor23"]
    # foreign STCG (net loss) - resident "sale of other assets" (slab/applicable rate).
    # NOTE: FullConsideration is a COMPUTED field (= sum of the Consd sub-fields); the proceeds MUST go
    # into FullValueConsdOthUnqshr or the Utility recomputes FullConsideration=0 and inverts it to a loss.
    st["SaleOnOtherAssets"] = {**st.get("SaleOnOtherAssets", {}),
                               "FullValueConsdRecvUnqshr": 0, "FairMrktValueUnqshr": 0, "FullValueConsdSec50CA": 0,
                               "FullValueConsdOthUnqshr": cgp["st_proceeds"], "FullConsideration": cgp["st_proceeds"],
                               "DeductSec48": _ded(cgp["st_cost"]), "BalanceCG": _r(stcg), "CapgainonAssets": _r(stcg)}
    # domestic equity-MF STCG u/s 111A (20%)
    st["EquityMFonSTT"] = [{"MFSectionCode": "1A", "EquityMFonSTTDtls": {
        "FullConsideration": d_stcg_sale, "DeductSec48": _ded(d_stcg_cost),
        "BalanceCG": d_stcg, "LossSec94of7Or94of8": 0, "CapgainonAssets": d_stcg}}]
    st["TotalSTCG"] = _r(stcg) + d_stcg

    lt = cg["LongTermCapGain23"]
    # foreign shares LTCG u/s 112 @12.5% - resident "sale of asset" block
    lt["SaleofAssetNADtls"] = {"SaleofAssetNA": {
        "FullValueConsdRecvUnqshr": 0, "FairMrktValueUnqshr": 0, "FullValueConsdSec50CA": 0,
        "FullValueConsdOthUnqshr": cgp["lt_proceeds"], "FullConsideration": cgp["lt_proceeds"],
        "DeductSec48": _ded(cgp["lt_cost"]), "BalanceCG": _r(ltcg_gross),
        "DeductionUs54F": 0, "CapgainonAssets": _r(ltcg_gross)}}
    # domestic equity-MF LTCG u/s 112A (12.5%, first 1.25L exempt)
    lt["SaleOfEquityShareUs112A"] = {"BalanceCG": d_ltcg, "DeductionUs54F": 0, "CapgainonAssets": d_ltcg}
    lt["TotalLTCG"] = _r(ltcg_gross) + d_ltcg

    cg["SumOfCGIncm"] = taxable_cg
    cg["TotScheduleCGFor23"] = taxable_cg
    # Table F (234C): LTCG @12.5% accrual must equal BFLA 3vii (= net LTCG after set-off).
    # All foreign LTCG sales fell in Q3 (16/9-15/12); put the net taxable LTCG there.
    cg["AccruOrRecOfCG"]["LongTermUnder12_5Per"]["DateRange"]["Up16Of9To15Of12"] = taxable_cg
    itr["ScheduleCGFor23"] = cg

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

    # ---- foreign tax credit: FSI + TR1 ----
    ftc = compute_ftc(fy, tin=us_tin)
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
        "TaxPaidOutsideIndFlg": "YES", "AssmtYrTaxRelief": ay + "-" + str((int(ay) + 1) % 100).zfill(2)}

    # ---- taxes paid ----
    itr["ScheduleTDS1"] = {"TDSonSalary": [{
        "EmployerOrDeductorOrCollectDetl": {"TAN": prof["employer"]["TANofEmployer"],
            "EmployerOrDeductorOrCollecterName": prof["employer"]["NameOfEmployer"]},
        "IncChrgSal": _r(itcs["income_under_salary"]), "TotalTDSSal": salary_tds}],
        "TotalTDSonSalaries": salary_tds}
    itr["ScheduleTCS"] = {"TCS": [{
        "EmployerOrDeductorOrCollectTAN": prof["tcs_collector_tan"], "TCSCreditOwner": "1",
        "TCSCurrFYDtls": {"TCSAmtCollOwnHand": lrs_tcs, "TCSAmtCollSpouseOrOthrHand": 0},
        "TCSClaimedThisYearDtls": {"TCSAmtCollOwnHand": lrs_tcs, "TCSAmtCollSpouseOrOthrHand": 0},
        "AmtCarriedFwd": 0}], "TotalSchTCS": lrs_tcs}

    # ---- Schedule AL: shares = foreign (FA closing) + Indian (Zerodha); deposits = bank + FD ----
    foreign_shares = sum(r["ClosingBalance"] for r in fa["ScheduleFA"]["DtlsForeignEquityDebtInterest"])
    zh = parse_zerodha()
    bk = parse_bank()
    al = copy.deepcopy(prior["ScheduleAL"])
    al["MovableAsset"]["SharesAndSecurities"] = _r(foreign_shares + zh["holdings_market_value"])
    al["MovableAsset"]["DepositsInBank"] = bk["deposits_for_AL"]   # HDFC savings + FD (+ 4766/SBI: manual)
    al.pop("ImmovableDetails", None)   # "Do you own immovable asset?" is UI-only (no JSON field); user picks "No"
    itr["ScheduleAL"] = al

    # ---- PartB-TI ----
    salary = _r(itcs["income_under_salary"])
    os_inc = itr["ScheduleOS"]["TotOthSrcNoRaceHorse"]
    gti = salary + taxable_ltcg + os_inc
    normal_income = salary + os_inc
    itr["PartB-TI"] = _deep_merge(skeleton_of("PartB-TI"), {
        "Salaries": salary, "IncomeFromHP": 0,
        "CapGain": {"LongTerm": {"LongTerm12_5Per": taxable_ltcg, "LongTermSplRateDTAA": 0,
                                 "TotalLongTerm": taxable_ltcg},
                    "ShortTerm": {"TotalShortTerm": 0}, "TotalCapGains": taxable_ltcg},
        "IncFromOS": {"TotIncFromOS": os_inc, "OtherSrcThanOwnRaceHorse": os_inc},
        "GrossTotalIncome": gti, "TotalIncome": gti,
        "IncChargeableTaxSplRates": taxable_ltcg, "AggregateIncome": normal_income})

    # ---- PartB-TTI (tax) ----
    tr = compute_tax(normal_income, so.taxable_ltcg, 0.125, fy)
    relief = ftc["relief_inr"]
    total_paid = salary_tds + lrs_tcs
    net_liability = _r(tr.gross_tax) - relief
    bal = net_liability - total_paid
    itr["PartB_TTI"] = _deep_merge(skeleton_of("PartB_TTI"), {
        "AssetOutIndiaFlag": "YES",
        "ComputationOfTaxLiability": {
            "TaxPayableOnTI": {"TaxAtNormalRatesOnAggrInc": _r(tr.tax_normal),
                "TaxAtSpecialRates": _r(tr.tax_special), "RebateOnAgriInc": 0,
                "TaxPayableOnTotInc": _r(tr.tax_normal + tr.tax_special)},
            "TaxPayableOnRebate": _r(tr.tax_normal + tr.tax_special), "Rebate87A": 0,
            "TotalSurcharge": _r(tr.surcharge), "SurchargeOnAboveCrore": _r(tr.surcharge),
            "EducationCess": _r(tr.cess), "GrossTaxLiability": _r(tr.gross_tax),
            "GrossTaxPayable": _r(tr.gross_tax), "NetTaxLiability": _r(net_liability),
            "AggregateTaxInterestLiability": _r(net_liability)},
        "TaxPaid": {"TaxesPaid": {"AdvanceTax": 0, "SelfAssessmentTax": 0, "TDS": salary_tds,
            "TCS": lrs_tcs, "TotalTaxesPaid": total_paid}, "BalTaxPayable": max(0, _r(bal))},
        "Refund": {"RefundDue": max(0, -_r(bal)),
                   "BankAccountDtls": prior["PartB_TTI"]["Refund"]["BankAccountDtls"]}})

    summary = {"salary": salary, "capital_gains": taxable_ltcg, "other_sources": os_inc,
               "gross_total_income": gti, "gross_tax": _r(tr.gross_tax), "ftc_relief": relief,
               "tds": salary_tds, "tcs": lrs_tcs, "net_tax_payable": _r(bal),
               "fa_rows": fa["_counts"],
               "GAP_indian_mf_sale_value": ais["indian_mf_sale_value"]}
    return {"ITR": {"ITR2": itr}}, summary


def main() -> None:
    itr, summary = build()
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(itr, indent=2, ensure_ascii=False))
    errors = validate(itr["ITR"]["ITR2"])
    print(f"wrote {OUT}")
    for k, v in summary.items():
        print(f"  {k:20}: {v:,}" if isinstance(v, int) else f"  {k:20}: {v}")
    print(f"\nschema validation errors: {len(errors)}")
    for e in errors[:25]:
        print("  " + e)


if __name__ == "__main__":
    main()
