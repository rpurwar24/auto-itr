"""Auto-discovering provider registry.

Imports every module in itr_auto/providers/ that exposes a `PROVIDER`, so dropping a new
provider file is all it takes to register it (and get its documents into the checklist).
"""
from __future__ import annotations

import importlib
import pkgutil
from typing import Any

from itr_auto import providers as _pkg
from itr_auto.providers.base import Provider, ProviderResult

_SKIP = {"base", "registry"}


def providers() -> list[Provider]:
    found: list[Provider] = []
    for m in pkgutil.iter_modules(_pkg.__path__):
        if m.name in _SKIP:
            continue
        mod = importlib.import_module(f"itr_auto.providers.{m.name}")
        p = getattr(mod, "PROVIDER", None)
        if isinstance(p, Provider):
            found.append(p)
    return sorted(found, key=lambda p: (p.order, p.id))


def all_slots(fy: str) -> list[dict[str, Any]]:
    """Every provider's document slots as plain dicts, in checklist order."""
    out: list[dict[str, Any]] = []
    for p in providers():
        out.extend(p.slot_dicts(fy))
    return out


def collect(fy: str) -> dict[str, ProviderResult]:
    """Run every provider that implements parse() -> {provider_id: ProviderResult}.

    The normalization boundary the assembler can consume. Providers without a parse hook (or
    that raise on missing/partial input) are simply skipped, so this degrades gracefully.
    """
    results: dict[str, ProviderResult] = {}
    for p in providers():
        if p.parse is None:
            continue
        try:
            results[p.id] = p.parse(fy)
        except Exception:  # noqa: BLE001 - a provider with no/partial data just contributes nothing
            continue
    return results
