"""Local web app for the ITR-2 utility - workspace picker, document checklist/upload, run,
download. Local-only, no auth (single operator). Each person is a gitignored workspace under
.users/<name>/; the active workspace is selected per-request via the ITR_WORKSPACE env.

Run:  .venv/bin/python -m app.server      (serves http://127.0.0.1:8000)
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, UploadFile, Form, Body
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles

from itr_auto.workspace import repo_root
from itr_auto import checklist, vault

REPO = repo_root()
USERS_DIR = REPO / ".users"
STATIC = Path(__file__).resolve().parent / "static"

DEFAULT_INPUTS = {
    "_README": "Manual inputs / data gaps. Edit in the UI or here; the rest is auto-parsed.",
    "fy": "2025-26", "assessment_year": "2026",
    "savings_bank_interest": 0, "domestic_dividend": 0,
    "domestic_stcg": 0, "domestic_ltcg_112A": 0,
    "us_tin": "", "shares_value_mar31": None, "salary_tds": 0, "lrs_tcs": 0,
}

app = FastAPI(title="ITR-2 Utility")


# ---------- helpers ----------
def _slug(name: str) -> str:
    s = re.sub(r"[^a-z0-9_-]", "-", name.strip().lower()).strip("-")
    if not s:
        raise HTTPException(400, "invalid name")
    return s


def _ws(name: str) -> Path:
    d = USERS_DIR / _slug(name)
    if not d.exists():
        raise HTTPException(404, f"no workspace '{name}'")
    return d


def _activate(name: str) -> Path:
    """Point the pipeline's path resolver at this user's workspace (per-request)."""
    d = _ws(name)
    os.environ["ITR_WORKSPACE"] = str(d)
    return d


def _read_json(p: Path, default: Any) -> Any:
    return json.loads(p.read_text()) if p.exists() else default


def _fy(name: str) -> str:
    inp = _read_json(_ws(name) / "config" / "itr_inputs.json", DEFAULT_INPUTS)
    return inp.get("fy", "2025-26")


# ---------- users ----------
@app.get("/api/users")
def list_users() -> list[str]:
    if not USERS_DIR.exists():
        return []
    return sorted(d.name for d in USERS_DIR.iterdir() if d.is_dir())


@app.post("/api/users")
def create_user(payload: dict = Body(...)) -> dict:
    name = payload.get("name", "")
    slug = _slug(name)
    d = USERS_DIR / slug
    if d.exists():
        raise HTTPException(409, f"workspace '{slug}' already exists")
    (d / "config").mkdir(parents=True)
    (d / "sources").mkdir()
    (d / "output").mkdir()
    pan = (payload.get("pan") or "").upper().strip()
    personal = {"pan": pan, "dob_ddmmyyyy": (payload.get("dob_ddmmyyyy") or "").strip(),
                "us_tin": pan, "bank_passwords": {},
                "_README": "AIS PDF password = pan(lower)+dob_ddmmyyyy; bank_passwords keyed by hdfc/sbi."}
    (d / "config" / "personal.json").write_text(json.dumps(personal, indent=2))
    inp = dict(DEFAULT_INPUTS, us_tin=pan)
    (d / "config" / "itr_inputs.json").write_text(json.dumps(inp, indent=2))
    return {"name": slug}


# ---------- config ----------
@app.get("/api/users/{name}/config")
def get_config(name: str) -> dict:
    c = _ws(name) / "config"
    personal = _read_json(c / "personal.json", {})
    # decrypt stored bank passwords for display in the local UI
    personal["bank_passwords"] = {k: vault.decrypt(v)
                                  for k, v in (personal.get("bank_passwords") or {}).items()}
    return {"personal": personal,
            "itr_inputs": _read_json(c / "itr_inputs.json", DEFAULT_INPUTS),
            "profile": _read_json(c / "profile.json", {})}


@app.put("/api/users/{name}/config")
def put_config(name: str, payload: dict = Body(...)) -> dict:
    c = _ws(name) / "config"
    for key, fname in (("personal", "personal.json"), ("itr_inputs", "itr_inputs.json"),
                       ("profile", "profile.json")):
        if key in payload and payload[key] is not None:
            # keep us_tin in sync with PAN when the user hasn't set a separate TIN
            if key == "personal":
                p = payload[key]
                if p.get("pan") and not p.get("us_tin"):
                    p["us_tin"] = p["pan"]
                # encrypt bank passwords at rest (key lives outside the repo)
                p["bank_passwords"] = {k: vault.encrypt(v)
                                       for k, v in (p.get("bank_passwords") or {}).items()}
            (c / fname).write_text(json.dumps(payload[key], indent=2))
    return {"ok": True}


# ---------- checklist + upload ----------
@app.get("/api/users/{name}/checklist")
def get_checklist(name: str) -> dict:
    _activate(name)
    fy = _fy(name)
    return {"fy": fy, "slots": checklist.status(fy)}


@app.post("/api/users/{name}/upload")
async def upload(name: str, slot_id: str = Form(...), tag: str = Form(None),
                 files: list[UploadFile] = None) -> dict:
    _activate(name)
    fy = _fy(name)
    saved = []
    for f in (files or []):
        saved.append(checklist.save_upload(slot_id, f.filename, await f.read(), fy, tag=tag))
    return {"saved": saved}


@app.delete("/api/users/{name}/file")
def delete_file(name: str, dest: str, filename: str) -> dict:
    _activate(name)
    from itr_auto.workspace import sources_dir
    target = (sources_dir() / dest / filename).resolve()
    if sources_dir().resolve() not in target.parents:
        raise HTTPException(400, "path escapes workspace")
    if target.exists():
        target.unlink()
    return {"ok": True}


@app.post("/api/users/{name}/import-old-itr")
async def import_old_itr(name: str, file: UploadFile) -> dict:
    """Prefill PAN/DOB (and AIS password basis) from a previous year's ITR JSON."""
    d = _ws(name)
    try:
        data = json.loads((await file.read()).decode("utf-8", "ignore"))
        itr2 = data["ITR"]["ITR2"]
        pi = itr2["PartA_GEN1"]["PersonalInfo"]
        pan = pi.get("PAN", "")
        dob_iso = pi.get("DOB", "")            # YYYY-MM-DD
        y, m, dd = dob_iso.split("-")
        dob = f"{dd}{m}{y}"
    except Exception as e:  # noqa: BLE001
        raise HTTPException(400, f"could not read identity from ITR JSON: {e}")
    pfile = d / "config" / "personal.json"
    personal = _read_json(pfile, {})
    personal.update({"pan": pan, "dob_ddmmyyyy": dob, "us_tin": personal.get("us_tin") or pan})
    pfile.write_text(json.dumps(personal, indent=2))
    return {"pan": pan, "dob_ddmmyyyy": dob,
            "name": pi.get("AssesseeName", {}).get("FirstName", "") if isinstance(pi.get("AssesseeName"), dict) else ""}


# ---------- generate + download ----------
@app.post("/api/users/{name}/generate")
def generate(name: str) -> dict:
    d = _activate(name)
    fy = _fy(name)
    # pre-flight: a clear "add these first" instead of a raw traceback on missing inputs
    missing = [s["label"] for s in checklist.status(fy) if s["required"] and not s["present"]]
    if missing:
        return {"ok": False, "missing": missing,
                "error": "Add these required documents first:\n  - " + "\n  - ".join(missing)}
    env = dict(os.environ, ITR_WORKSPACE=str(d))
    proc = subprocess.run([sys.executable, "-m", "app.run_pipeline"],
                          cwd=str(REPO), env=env, capture_output=True, text=True)
    if proc.returncode != 0:
        tail = (proc.stderr or proc.stdout).strip()[-1500:]
        return {"ok": False,
                "error": ("Could not process the documents - a file may be unreadable, "
                          "password-protected, or in an unexpected format.\n\n"
                          "Technical detail:\n" + tail)}
    try:
        return {"ok": True, **json.loads(proc.stdout.strip().splitlines()[-1])}
    except Exception:  # noqa: BLE001
        return {"ok": False, "error": "pipeline produced no result:\n" + proc.stdout[-2000:]}


@app.get("/api/users/{name}/download")
def download(name: str) -> FileResponse:
    out = _ws(name) / "output" / "ITR2_AY2026_27.json"
    if not out.exists():
        raise HTTPException(404, "no generated JSON yet - run Generate first")
    return FileResponse(out, media_type="application/json", filename=f"ITR2_{name}.json")


# ---------- static frontend ----------
@app.get("/", response_class=HTMLResponse)
def index() -> str:
    return (STATIC / "index.html").read_text()


app.mount("/static", StaticFiles(directory=str(STATIC)), name="static")


if __name__ == "__main__":
    import uvicorn
    USERS_DIR.mkdir(exist_ok=True)
    uvicorn.run(app, host="127.0.0.1", port=8000)
