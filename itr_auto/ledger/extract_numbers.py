"""Extract stocks_computation.numbers into a structured lot ledger.

This is the foundation (Move 1). The .numbers file is the hand-maintained
manual engine; we reverse-engineer it into JSON so it can serve as both the
ledger the compute layer reads and the ground-truth oracle for back-testing.

Output (output/ledger.json):
  - lots               : normalized RSU/ESPP vest lots (one per acquisition)
  - reference_prices   : per-FY {peak, closing, calendar-year-closing} price/rate/date
                         + bank balances (for Schedule AL)
  - cost_inflation_index : CII per financial year (old-regime indexation)
  - raw_tables         : faithful dump of every table (nothing lost)

Run:  .venv/bin/python -m itr_auto.ledger.extract_numbers
"""
from __future__ import annotations

import datetime as dt
import json
import re
from pathlib import Path
from typing import Any

from numbers_parser import Document

from itr_auto.workspace import archive_dir, output_dir
SRC = archive_dir() / "stocks_computation.numbers"   # shared (legacy ground-truth oracle)
OUT = output_dir() / "ledger.json"

# normalized-header -> canonical field name for lot rows
FIELD_MAP = {
    "purchase date": "purchase_date",
    "purchased qty": "purchased_qty",
    "sellable qty": "sellable_qty",
    "discounted purchase price": "discounted_purchase_price_usd",
    "grant date": "grant_date",
    "transferable date": "transferable_date",
    "grant date fmv": "grant_date_fmv_usd",
    "purchase date fmv": "purchase_date_fmv_usd",
    "conversion rate": "vest_conversion_rate",
    "purchase price": "cost_basis_inr",
    "fy peak": "fy_peak_inr",
    "fy closing": "fy_closing_inr",
    "fy calendar year closing": "fy_cy_closing_inr",
    "sold qty": "sold_qty",
    "sold date": "sold_date",
    "execution price": "execution_price_usd",
    "bank credits": "bank_credits_inr",
    "gain/loss": "gain_loss_inr",
    "price with indexation": "price_with_indexation_inr",
}

NUMERIC_FIELDS = {
    "purchased_qty", "sellable_qty", "discounted_purchase_price_usd",
    "grant_date_fmv_usd", "purchase_date_fmv_usd", "vest_conversion_rate",
    "cost_basis_inr", "fy_peak_inr", "fy_closing_inr", "fy_cy_closing_inr",
    "sold_qty", "execution_price_usd", "bank_credits_inr", "gain_loss_inr",
    "price_with_indexation_inr",
}
DATE_FIELDS = {"purchase_date", "grant_date", "transferable_date", "sold_date"}


def norm(header: Any) -> str:
    """Normalize a header cell: lowercased, whitespace-collapsed, trailing dot stripped."""
    return re.sub(r"\s+", " ", str(header or "").strip().lower()).rstrip(".").strip()


def jsonify(value: Any) -> Any:
    """Make a cell JSON-serializable; datetimes -> ISO date strings."""
    if isinstance(value, dt.datetime):
        return value.date().isoformat()
    if isinstance(value, dt.date):
        return value.isoformat()
    if value == "":
        return None
    return value


def dedup_headers(headers: list[Any]) -> list[str]:
    """Give every column a unique, stable key (blanks -> colN, dups -> name__2)."""
    out, seen = [], {}
    for i, h in enumerate(headers):
        key = str(h).strip() if (h is not None and str(h).strip()) else f"col{i}"
        n = seen.get(key, 0) + 1
        seen[key] = n
        out.append(key if n == 1 else f"{key}__{n}")
    return out


def instrument_of(sheet_name: str, table_name: str) -> str | None:
    blob = f"{sheet_name} {table_name}".upper()
    if "ESPP" in blob:
        return "ESPP"
    if "RSU" in blob:
        return "RSU"
    return None


def cohort_of(table_name: str) -> str | None:
    m = re.search(r"\((\d{4})\)", table_name)
    if m:
        return m.group(1)
    m = re.search(r"\(([^)]+)\)", table_name)
    return m.group(1) if m else None


def coerce(field: str, raw: Any) -> Any:
    val = jsonify(raw)
    if val is None:
        return None
    if field in NUMERIC_FIELDS:
        try:
            return float(val)
        except (TypeError, ValueError):
            return val  # keep non-numeric (e.g. stray text) as-is for inspection
    return val  # dates already ISO strings via jsonify


def is_lot_row(row: dict[str, Any]) -> bool:
    """A real lot has an actual vest date and non-trivial quantity/cost.

    Excludes totals rows (blank purchase date) and zero placeholder rows.
    """
    if not row.get("purchase_date"):
        return False
    qty = row.get("purchased_qty") or 0
    cost = row.get("cost_basis_inr") or 0
    return bool(qty) or bool(cost)


def parse_reference_table(headers: list[Any], rows: list[list[Any]]) -> dict[str, Any]:
    """Label-in-first-column tables (peak/closing/CY-closing/bank balances)."""
    parsed: dict[str, Any] = {}
    for r in [headers, *rows]:
        if not r or r[0] in (None, ""):
            continue
        label = str(r[0]).strip()
        rest = [jsonify(c) for c in r[1:]]
        parsed[label] = {"value": rest[0] if rest else None,
                         "rate": rest[1] if len(rest) > 1 else None,
                         "date": rest[2] if len(rest) > 2 else None}
    return parsed


def parse_cii(headers: list[Any], rows: list[list[Any]]) -> dict[str, float]:
    cii: dict[str, float] = {}
    for r in rows:
        if not r or r[0] in (None, ""):
            continue
        fy = re.sub(r"\s*-\s*", "-", str(r[0]).strip())
        try:
            cii[fy] = float(r[1])
        except (TypeError, ValueError, IndexError):
            continue
    return cii


def extract(src: Path = SRC) -> dict[str, Any]:
    doc = Document(str(src))
    lots: list[dict[str, Any]] = []
    reference_prices: dict[str, Any] = {}
    cii: dict[str, float] = {}
    raw_tables: dict[str, Any] = {}

    for sheet in doc.sheets:
        # "-KB" sheets belong to a friend (KB); not this taxpayer's data.
        if "KB" in sheet.name.upper():
            continue
        for table in sheet.tables:
            key = f"{sheet.name}::{table.name}"
            rows = table.rows(values_only=True)
            if not rows:
                continue
            headers, body = rows[0], rows[1:]

            # faithful raw dump
            cols = dedup_headers(headers)
            raw_tables[key] = {
                "headers": cols,
                "rows": [{cols[i]: jsonify(c) for i, c in enumerate(r)} for r in body],
            }

            name = table.name
            if norm(name) == "indexation table":
                cii = parse_cii(headers, body)
                continue
            if "SHARE" in name.upper():
                reference_prices[key] = parse_reference_table(headers, body)
                continue

            instrument = instrument_of(sheet.name, name)
            if instrument is None:
                continue

            # map columns by normalized header (first occurrence wins for dups)
            col_field: dict[int, str] = {}
            used: set[str] = set()
            for i, h in enumerate(headers):
                field = FIELD_MAP.get(norm(h))
                if field and field not in used:
                    col_field[i] = field
                    used.add(field)

            for r in body:
                rec = {"instrument": instrument,
                       "cohort": cohort_of(name),
                       "source": key}
                for i, field in col_field.items():
                    if i < len(r):
                        rec[field] = coerce(field, r[i])
                if is_lot_row(rec):
                    rec["is_sold"] = bool(rec.get("sold_qty"))
                    # incomplete = qty present but cost/rate not yet filled in the sheet
                    rec["incomplete"] = not (rec.get("cost_basis_inr")
                                             and rec.get("vest_conversion_rate"))
                    lots.append(rec)

    return {
        "source_file": str(src),
        "generated_at": dt.datetime.now().isoformat(timespec="seconds"),
        "lots": lots,
        "reference_prices": reference_prices,
        "cost_inflation_index": cii,
        "raw_tables": raw_tables,
    }


def summarize(ledger: dict[str, Any]) -> str:
    lots = ledger["lots"]
    by_instr: dict[str, int] = {}
    sold = 0
    tot_purchased = tot_sellable = tot_cost = 0.0
    for lot in lots:
        by_instr[lot["instrument"]] = by_instr.get(lot["instrument"], 0) + 1
        sold += 1 if lot.get("is_sold") else 0
        tot_purchased += lot.get("purchased_qty") or 0
        tot_sellable += lot.get("sellable_qty") or 0
        tot_cost += lot.get("cost_basis_inr") or 0
    lines = [
        f"lots total           : {len(lots)}",
        f"  by instrument      : {by_instr}",
        f"  sold lots          : {sold}",
        f"  sum purchased qty  : {tot_purchased:g}",
        f"  sum sellable qty   : {tot_sellable:g}",
        f"  sum cost basis INR : {tot_cost:,.0f}",
        f"reference price tables: {len(ledger['reference_prices'])}",
        f"CII years            : {len(ledger['cost_inflation_index'])}",
        f"raw tables           : {len(ledger['raw_tables'])}",
    ]
    return "\n".join(lines)


def main() -> None:
    ledger = extract()
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(ledger, indent=2, ensure_ascii=False))
    print(f"wrote {OUT}")
    print(summarize(ledger))


if __name__ == "__main__":
    main()
