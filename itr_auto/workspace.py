"""Path resolution for a multi-user, git-shareable app.

The repo (code, schema, shared FX/price caches) is one shared checkout. Each person's
PRIVATE data lives in their own workspace folder that git never tracks:

    .users/<username>/{sources,config,output}/

The active workspace is chosen by the ITR_WORKSPACE env var (absolute, or relative to the
repo root). If it is unset the workspace root IS the repo root - i.e. the original
single-user layout (sources/ config/ output/ at the top level) keeps working unchanged, so
existing runs and the whole test suite behave exactly as before.

Split:
  - per-user (under the workspace root): sources/, config/, output/  -> one person's data
  - shared   (always the repo root):    reference/ (schema + FX/price caches), archive/
"""
from __future__ import annotations

import os
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]   # shared app root


def repo_root() -> Path:
    """Shared app root - code, schema, FX/price caches (same for every user)."""
    return REPO


def workspace_root() -> Path:
    """Active per-user data root. $ITR_WORKSPACE (abs or repo-relative), else the repo root."""
    ws = os.environ.get("ITR_WORKSPACE")
    if not ws:
        return REPO
    p = Path(ws).expanduser()
    return p if p.is_absolute() else (REPO / p)


# ---- per-user directories (under the workspace root) ----
def sources_dir() -> Path:
    return workspace_root() / "sources"


def config_dir() -> Path:
    return workspace_root() / "config"


def output_dir() -> Path:
    return workspace_root() / "output"


def personal_json() -> Path:
    return config_dir() / "personal.json"


def itr_inputs_json() -> Path:
    return config_dir() / "itr_inputs.json"


# ---- shared directories (always the repo root) ----
def reference_dir() -> Path:
    return REPO / "reference"


def archive_dir() -> Path:
    return REPO / "archive"


def schema_path() -> Path:
    return REPO / "reference" / "schema" / "ITR2_AY2026-27_schema.json"
