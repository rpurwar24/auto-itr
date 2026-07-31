"""Taxpayer/employer/provider constants that used to be hardcoded in the schedule builders.

`load()` returns the active person's profile: the built-in defaults (the original Adobe
taxpayer) overlaid with the workspace's `config/profile.json` if present. So a new user just
drops a `profile.json` in their workspace to change employer / TCS collector / foreign
country etc. - no code change. With no file present the defaults reproduce today's output
exactly (keeps the test suite green).

Values are kept as the exact strings the ITD schema/utility expects (note the deliberate
upper/lower-case differences between the FSI country name and the FA country name - the
filed JSON uses both, so don't "normalise" them).
"""
from __future__ import annotations

import copy
import json

from itr_auto.workspace import config_dir

# Neutral placeholder defaults. A real taxpayer's values live ONLY in their gitignored
# workspace config/profile.json (see config/profile.example.json) and are merged over these -
# so nothing identifying ships in the code.
DEFAULT_PROFILE = {
    # ---- Schedule S: employer block (also reused for Schedule TDS1) ----
    "employer": {
        "TANofEmployer": "AAAA00000A",
        "NameOfEmployer": "EMPLOYER NAME",
        "AddressDetail": {"CityOrTownOrDistrict": "CITY", "PinCode": 100000,
                          "StateCode": "31", "AddrDetail": "ADDRESS"},
        "NatureOfEmployment": "OTH",
    },
    # payslip component label -> ITR NatureOfSalary code (null => grouped under "OTH")
    "salary_component_codes": {
        "Basic": "1",
        "Conveyance Allowance": "3",
        "House Rent Allowance": "4",
        "Leave Travel Allowance": "5",
    },
    # free-text label for the OTH-grouped components (alphanumeric+spaces only; the ITD utility
    # rejects "/" & other special chars in this "Description" field)
    "salary_oth_label": "Other allowances",

    # ---- Schedule TCS: LRS 206CQ collector (the remitting bank) ----
    "tcs_collector_tan": "BBBB00000B",

    # ---- Schedule FSI / TR1: country where foreign income was taxed (dividend FTC) ----
    "foreign_country_name": "United States of America",
    "foreign_country_code": "2",
    # Schedule FA Table A2 custodial-account country (filed JSON uses upper-case here)
    "foreign_custodial_country_name": "UNITED STATES OF AMERICA",

    # ---- Schedule FA Table A3: the foreign employer whose equity is held (RSUs/ESPP) ----
    "fa_equity_entity": {
        "CountryName": "UNITED STATES OF AMERICA", "CountryCodeExcludingIndia": "2",
        "NameOfEntity": "FOREIGN EMPLOYER INC.", "AddressOfEntity": "City, State, US",
        "ZipCode": "00000", "NatureOfEntity": "COMPANY",
    },

    # top marginal rate used only to cap the foreign-tax credit
    # (new regime 30% + 15% surcharge + 4% cess)
    "marginal_rate": 0.3588,
}


def _deep_merge(base: dict, overlay: dict) -> dict:
    for k, v in overlay.items():
        if isinstance(v, dict) and isinstance(base.get(k), dict):
            _deep_merge(base[k], v)
        else:
            base[k] = v
    return base


def load() -> dict:
    """Active profile = built-in defaults overlaid with the workspace's config/profile.json."""
    p = copy.deepcopy(DEFAULT_PROFILE)
    f = config_dir() / "profile.json"
    if f.exists():
        _deep_merge(p, json.loads(f.read_text()))
    return p
