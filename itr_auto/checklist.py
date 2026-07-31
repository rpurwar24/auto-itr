"""Presence detection + upload filing for the app's document checklist.

The list of required documents is owned by the provider plugins (itr_auto/providers/): this
module asks the registry for the slots, checks which are present in the active workspace, and
files uploads into the right place - so the user never learns the folder/naming convention, and
adding a provider (a new bank/broker) is a one-file drop with no edit here.

Paths resolve through `workspace.sources_dir()`, i.e. relative to the ACTIVE workspace
(set the ITR_WORKSPACE env before calling), so this is per-user.
"""
from __future__ import annotations

import re
from typing import Any

from itr_auto.workspace import sources_dir
from itr_auto.providers import registry


def manifest(fy: str = "2025-26") -> list[dict[str, Any]]:
    """Document slots a return needs, assembled from the registered providers."""
    return registry.all_slots(fy)


def _slug_ok(name: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]", "_", name).lstrip(".") or "file"


def status(fy: str = "2025-26") -> list[dict[str, Any]]:
    """Manifest augmented with `present` + the list of `files` found in each slot."""
    out = []
    for s in manifest(fy):
        d = sources_dir() / s["dest"]
        if s["multiple"]:
            files = ([f.name for f in sorted(d.glob("*"))
                      if f.is_file() and not f.name.startswith("~$")] if d.exists() else [])
            present = bool(files)
        else:
            f = d / s["filename"]
            files = [f.name] if f.exists() else []
            present = f.exists()
        out.append({**s, "present": present, "files": files})
    return out


def save_upload(slot_id: str, upload_name: str, data: bytes, fy: str = "2025-26",
                tag: str | None = None) -> dict[str, Any]:
    """Write an uploaded file into the correct slot folder.

    Single-file slots are renamed to the canonical `filename`. Multiple-file slots keep the
    original name; if the slot has a `tag` (e.g. bank), the chosen tag is prefixed to the name
    (`hdfc-<name>`) so the parser can apply the right PDF password - the user need not rename.
    """
    slot = next((s for s in manifest(fy) if s["id"] == slot_id), None)
    if slot is None:
        raise ValueError(f"unknown slot {slot_id!r}")
    d = sources_dir() / slot["dest"]
    d.mkdir(parents=True, exist_ok=True)
    if not slot["multiple"]:
        fname = slot["filename"]
    else:
        fname = _slug_ok(upload_name)
        if slot.get("tag") and tag:
            tag = _slug_ok(tag).lower()
            if not fname.lower().startswith(f"{tag}-"):
                fname = f"{tag}-{fname}"
    dest = d / fname
    dest.write_bytes(data)
    return {"slot": slot_id, "saved": str(dest.relative_to(sources_dir())), "name": fname}
