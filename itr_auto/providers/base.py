"""The provider-plugin contract.

A `Provider` describes one integration (a portal, employer, bank, broker, custodian, or tax
authority). It declares:

  1. the DOCUMENTS it needs (`slots`) - these drive the app's upload checklist and where each
     file is stored; and
  2. optionally, how to PARSE those documents into a normalized `ProviderResult` (`parse`) -
     the contribution the return-assembler can consume without knowing anything provider-specific.

To add a provider, drop a new module in itr_auto/providers/ that sets `PROVIDER = Provider(...)`.
The registry auto-discovers it; its slots appear in the checklist immediately.

`ProviderResult` is the normalization boundary: every field is optional, and the assembler merges
whatever providers supply. This is what lets a new bank/broker be a single self-contained file
instead of edits scattered across the pipeline.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Optional


@dataclass(frozen=True)
class DocSlot:
    """One document the return needs. `dest` may contain '{fy}' (filled per financial year)."""
    id: str
    label: str
    desc: str
    dest: str
    multiple: bool
    required: bool
    accept: str
    filename: Optional[str] = None          # canonical name for single-file slots
    tag: Optional[dict] = None              # {"label","options"} -> UI dropdown + filename prefix


@dataclass
class ProviderResult:
    """Normalized contribution from one provider. All optional; the assembler takes what's set."""
    salary: Optional[dict] = None
    capital_gains_lots: list = field(default_factory=list)
    foreign_assets: list = field(default_factory=list)
    dividends: list = field(default_factory=list)
    interest: Optional[dict] = None         # {"savings":.., "term_deposit":..}
    bank_balances: Optional[dict] = None     # {account_key: closing_balance}
    tds: Optional[dict] = None
    tcs: Optional[dict] = None
    ftc: Optional[dict] = None
    notes: list = field(default_factory=list)


@dataclass(frozen=True)
class Provider:
    id: str
    name: str
    category: str                            # portal|employer|tax-authority|bank|broker|custodian
    slots: Callable[[str], list[DocSlot]]    # fy -> the documents this provider needs
    order: int = 100                         # checklist ordering (lower first)
    parse: Optional[Callable[[str], ProviderResult]] = None   # fy -> normalized contribution

    def slot_dicts(self, fy: str) -> list[dict[str, Any]]:
        """Render this provider's slots as the plain dicts the checklist/UI consume."""
        out = []
        for s in self.slots(fy):
            d = {"id": s.id, "provider": self.name, "label": s.label, "desc": s.desc,
                 "dest": s.dest.format(fy=fy), "filename": s.filename,
                 "multiple": s.multiple, "required": s.required, "accept": s.accept}
            if s.tag:
                d["tag"] = s.tag
            out.append(d)
        return out
