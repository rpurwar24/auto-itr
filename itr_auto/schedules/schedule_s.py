"""Build Schedule S (Salaries) JSON from the ITCS salary breakup.

Nature-of-salary codes (ITR-2 Schedule S dropdown; derived from filed returns +
the standard component order). NOTE: under the NEW regime none of these allowances
are exempt, so the code split is disclosure only - zero tax impact. Adjust freely.
  1 = Basic Salary, 3 = Conveyance Allowance, 4 = House Rent Allowance,
  5 = Leave Travel Allowance, 17 = Perquisites u/s 17(2), 18 = Profits in lieu.
Adobe-specific bonuses (AIP/Wellness/Patent) have no dedicated code -> "OTH" + text,
matching how the prior-year return grouped them.
"""
from __future__ import annotations

from typing import Any

from itr_auto.profile import load as load_profile


def _rupees(x: float) -> int:
    return int(round(x))


def build_schedule_s(itcs: dict[str, Any], employer: dict[str, Any] | None = None) -> dict[str, Any]:
    prof = load_profile()
    employer = employer or prof["employer"]
    component_code = prof["salary_component_codes"]  # label -> code (missing/None => group under OTH)
    oth_label = prof["salary_oth_label"]             # alphanumeric+spaces only (utility rejects "/")
    # iterate the ACTUAL 17(1) salary components (not the profile's code map): any component the
    # profile doesn't map by name falls to "OTH" so nothing is ever dropped. The utility recomputes
    # GrossSalary from these NatureOfSalary lines, so this sum MUST equal salary_17_1.
    salary_comps = itcs.get("salary_components", itcs["components"])

    nature_of_salary = []
    oth_total = 0.0
    for label, amt in salary_comps.items():
        if not amt:
            continue
        code = component_code.get(label)
        if code is None:
            oth_total += amt
        else:
            nature_of_salary.append({"NatureDesc": code, "OthAmount": _rupees(amt)})
    if oth_total:
        nature_of_salary.append({"NatureDesc": "OTH", "OthNatOfInc": oth_label,
                                 "OthAmount": _rupees(oth_total)})

    salary_17_1 = _rupees(itcs["salary_17_1"])
    perquisite = _rupees(itcs["perquisite_17_2"])
    gross = _rupees(itcs["gross_salary"])
    std_ded = _rupees(itcs["standard_deduction_16ia"])
    net_under_salary = _rupees(itcs["income_under_salary"])

    salarys = {
        "NatureOfSalary": {"OthersIncDtls": nature_of_salary},
        "IncomeNotified89A": 0,
        "Salary": salary_17_1,
        "ValueOfPerquisites": perquisite,
        "ProfitsinLieuOfSalary": 0,
        "GrossSalary": gross,
        "IncomeNotifiedOther89A": 0,
        "IncomeNotifiedPrYr89A": 0,
    }
    if perquisite:
        salarys["NatureOfPerquisites"] = {
            "OthersIncDtls": [{"NatureDesc": "17", "OthAmount": perquisite}]}

    return {
        "EntertainmntalwncUs16ii": 0,
        "ProfessionalTaxUs16iii": 0,
        "DeductionUnderSection16ia": std_ded,
        "Salaries": [{**{k: employer[k] for k in
                         ("TANofEmployer", "AddressDetail", "NameOfEmployer")},
                      "Salarys": salarys,
                      "NatureOfEmployment": employer["NatureOfEmployment"]}],
        "TotalGrossSalary": gross,
        "AllwncExtentExemptUs10": 0,          # new regime: no s.10 exemptions
        "NetSalary": gross,
        "DeductionUS16": std_ded,
        "TotIncUnderHeadSalaries": net_under_salary,
        "Increliefus89A": 0,
    }


if __name__ == "__main__":
    import json
    from itr_auto.parsers.itcs import parse_latest
    print(json.dumps(build_schedule_s(parse_latest()), indent=2, ensure_ascii=False))
