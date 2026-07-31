"""Emit Schedule FA (Table A3 - foreign equity/debt) as a CSV for the ITD offline Utility's
"Import CSV" on that grid.

WHY THIS EXISTS: the final ITR JSON must be produced BY the Utility (it stamps a secret,
server-verified hash; externally-edited JSON is rejected - see CLAUDE.md CRITICAL CORRECTION).
The Utility's per-grid CSV import is the ONLY way to bulk-load our 63 computed FA rows without
hand-typing. Columns mirror the Utility's DtlsForeignEquityDebtInterest JSON field set (verified
against a real Utility export, <PAN>_upload_*.json).

Header names below are the JSON field names; if the Utility's downloaded CSV template uses
different human-readable headers, replace COLUMNS with the template's exact header row (a mismatch
triggers the Utility's "csv_header_mismatch"). Verify once against the empty template, then it's stable.
"""
from __future__ import annotations

import csv
from pathlib import Path

from itr_auto.schedules.schedule_fa import build_schedule_fa

from itr_auto.workspace import output_dir
OUT = output_dir() / "csv" / "schedule_fa_A3.csv"

# order taken from the Utility export's DtlsForeignEquityDebtInterest rows
COLUMNS = [
    "CountryName", "CountryCodeExcludingIndia", "NameOfEntity", "AddressOfEntity", "ZipCode",
    "NatureOfEntity", "InterestAcquiringDate", "InitialValOfInvstmnt", "PeakBalanceDuringPeriod",
    "ClosingBalance", "TotGrossAmtPaidCredited", "TotGrossProceeds",
]


def write_fa_csv(calendar_year: int = 2025, path: Path = OUT) -> dict:
    rows = build_schedule_fa(calendar_year)["ScheduleFA"]["DtlsForeignEquityDebtInterest"]
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=COLUMNS, extrasaction="ignore")
        w.writeheader()
        for r in rows:
            w.writerow({c: r.get(c, "") for c in COLUMNS})
    return {
        "path": str(path), "rows": len(rows),
        "totals": {
            "initial": round(sum(r.get("InitialValOfInvstmnt", 0) for r in rows)),
            "peak": round(sum(r.get("PeakBalanceDuringPeriod", 0) for r in rows)),
            "closing": round(sum(r.get("ClosingBalance", 0) for r in rows)),
            "proceeds": round(sum(r.get("TotGrossProceeds", 0) for r in rows)),
        },
    }


if __name__ == "__main__":
    import json
    print(json.dumps(write_fa_csv(), indent=2))
