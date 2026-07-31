"""Parse Vested/DriveWealth ITR helper workbooks (vested/<fy>/*.xlsx).

Vested pre-computes Schedule FA (their US portfolio, calendar-year basis) plus the foreign
dividend / FTC figures. openpyxl chokes on their malformed style XML, so we read the sheets
raw via zip + XML. We transcribe their computed values (they're the custodian's authoritative
numbers) rather than recompute. NOTE: Vested converts at RBI reference rates, not SBI TTBR.
"""
from __future__ import annotations

import glob
import re
import zipfile
from pathlib import Path
from typing import Any
from xml.etree import ElementTree as ET

from itr_auto.workspace import sources_dir
VESTED_DIR = sources_dir() / "vested"
_NS = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"


def _read_sheets(path: str | Path) -> list[list[list[str]]]:
    """Return each worksheet as a list of non-empty rows (list of cell strings)."""
    z = zipfile.ZipFile(path)
    shared: list[str] = []
    if "xl/sharedStrings.xml" in z.namelist():
        for si in ET.fromstring(z.read("xl/sharedStrings.xml")).findall(f"{_NS}si"):
            shared.append("".join(t.text or "" for t in si.iter(f"{_NS}t")))
    sheets = []
    for name in sorted(n for n in z.namelist()
                       if re.match(r"xl/worksheets/sheet\d+\.xml", n)):
        rows = []
        for row in ET.fromstring(z.read(name)).iter(f"{_NS}row"):
            cells = []
            for c in row.findall(f"{_NS}c"):
                v = c.find(f"{_NS}v")
                cells.append("" if v is None else
                             (shared[int(v.text)] if c.get("t") == "s" else v.text))
            if any(x != "" for x in cells):
                rows.append(cells)
        sheets.append(rows)
    return sheets


def _iso(d: str) -> str:
    dd, mm, yy = re.split(r"[-/]", d.strip())
    return f"{yy}-{mm.zfill(2)}-{dd.zfill(2)}"


def _xlsx(pattern: str) -> list[str]:
    """glob .xlsx, skipping Excel lock/temp files (~$...) left behind by opening files."""
    return [h for h in glob.glob(pattern) if not Path(h).name.startswith("~$")]


def _find(fy: str, suffix: str) -> Path:
    hits = _xlsx(str(VESTED_DIR / fy / f"*{suffix}*.xlsx"))
    if not hits:
        raise FileNotFoundError(f"no Vested '{suffix}' workbook for {fy}")
    return Path(hits[0])


def schedule_fa_holdings(fy: str = "2025-26") -> list[dict[str, Any]]:
    """Table A3 rows (foreign equity/ETF) as Vested computed them (INR)."""
    rows = _read_sheets(_find(fy, "Schedule FA"))[0]
    out = []
    for r in rows:
        # data rows have a numeric Sr No in column index 1
        if len(r) < 13 or not str(r[1]).strip().isdigit():
            continue
        out.append({
            "sr": int(r[1]), "country": r[2], "entity": r[3], "address": r[4],
            "zip": str(r[5]), "nature": r[6], "acquired": _iso(r[7]),
            "initial_inr": float(r[8]), "peak_inr": float(r[9]),
            "closing_inr": float(r[10]), "gross_paid_inr": float(r[11] or 0),
            "gross_proceeds_inr": float(r[12] or 0),
        })
    return out


def custodial_account(fy: str = "2025-26") -> dict[str, Any] | None:
    """Table A2 - foreign custodial account (DriveWealth)."""
    for sheet in _read_sheets(_find(fy, "Schedule FA")):
        header_i = next((i for i, r in enumerate(sheet)
                         if any("financial institution" in str(c).lower() for c in r)), None)
        if header_i is None:
            continue
        for r in sheet[header_i + 1:]:
            if len(r) >= 8 and str(r[1]).strip() and "DriveWealth" in " ".join(map(str, r)):
                return {"country": r[1], "institution": r[2], "address": r[3],
                        "zip": str(r[4]), "account_number": str(r[5]),
                        "status": r[6], "opened": _iso(r[7])}
    return None


def _main_summary(fy: str) -> Path:
    for f in _xlsx(str(VESTED_DIR / fy / "*.xlsx")):
        if not re.search(r"Schedule|Form 67", f):
            return Path(f)
    raise FileNotFoundError(f"no Vested main summary for {fy}")


def dividend_detail(fy: str = "2025-26") -> list[dict[str, Any]]:
    """Per-dividend rows (gross INR + date) for Schedule OS + its quarterly 234C split."""
    rows = _read_sheets(_main_summary(fy))[0]
    grab, out = False, []
    for r in rows:
        joined = " | ".join(map(str, r))
        if "Dividend Per Share" in joined:
            grab = True
            continue
        if grab:
            if not r or str(r[0]).strip() in ("Interest Income", "Summary", "Interest",
                                              "Proceeds from Transactions") or "Note:" in joined:
                break
            if len(r) >= 7 and re.fullmatch(r"\d{4}-\d{2}-\d{2}", str(r[1]).strip()):
                gross_usd, rate = float(r[3]), float(r[6])
                out.append({"security": r[0], "date": r[1],
                            "gross_usd": gross_usd, "rate": rate,
                            "gross_inr": round(gross_usd * rate, 2),
                            "tax_usd": abs(float(r[4]))})
    return out


def foreign_income_ftc(fy: str = "2025-26") -> dict[str, Any]:
    """Foreign dividend income + tax paid abroad (for Schedule OS / FSI / TR / Form 67)."""
    rows = _read_sheets(_find(fy, "Form 67"))[0]
    div_income = div_tax = 0.0
    for r in rows:
        # a data row like: [Sr, Country, "Dividend", income, tax_paid, ...]
        di = next((i for i, c in enumerate(r) if str(c).strip() == "Dividend"), None)
        if di is None:
            continue
        nums = [float(c) for c in r[di + 1:] if re.fullmatch(r"-?\d+\.?\d*", str(c).strip() or "x")]
        if len(nums) >= 2:
            div_income, div_tax = nums[0], nums[1]
    return {"country": "USA", "dividend_income_inr": div_income, "tax_paid_inr": div_tax}


if __name__ == "__main__":
    import json
    print("A3 holdings:", json.dumps(schedule_fa_holdings(), indent=2))
    print("A2 account:", json.dumps(custodial_account(), indent=2))
    print("FTC/dividend:", json.dumps(foreign_income_ftc(), indent=2))
