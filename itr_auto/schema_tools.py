"""Schema-driven tooling: build a minimal valid ITR-2 instance + validate against the schema.

The official ITR-2 JSON schema (data/schema/ITR2_AY2026-27_schema.json, Draft-4) is the source
of truth. `skeleton()` produces a minimal schema-valid instance (required fields with
type-appropriate defaults); the generator overlays computed schedules onto it. This adapts
automatically when the schema changes year to year (e.g. the CG 12.5% regime restructure).
"""
from __future__ import annotations

import json
from typing import Any

from jsonschema import Draft4Validator

from itr_auto.workspace import schema_path

SCHEMA_PATH = schema_path()   # shared across users (same schema for an assessment year)


def load_schema() -> dict:
    return json.loads(SCHEMA_PATH.read_text())


class _Skeleton:
    def __init__(self, schema: dict):
        self.defs = schema.get("definitions", {})
        self.root = schema

    def _resolve(self, node: dict) -> dict:
        seen = 0
        while "$ref" in node and seen < 50:
            node = self.defs[node["$ref"].split("/")[-1]]
            seen += 1
        return node

    def build(self, node: dict, required_only: bool = True) -> Any:
        node = self._resolve(node)
        if "enum" in node:
            return node["enum"][0]
        t = node.get("type")
        if isinstance(t, list):
            t = next((x for x in t if x != "null"), t[0])
        if t == "object":
            props = node.get("properties", {})
            req = set(node.get("required", []))
            keep = req if required_only else set(props)
            return {k: self.build(v, required_only) for k, v in props.items() if k in keep}
        if t == "array":
            if node.get("minItems", 0) > 0 and "items" in node:
                return [self.build(node["items"], required_only)
                        for _ in range(node["minItems"])]
            return []
        if t in ("number", "integer"):
            return 0
        if t == "boolean":
            return False
        if t == "string":
            if node.get("format") == "date":
                return "2025-04-01"
            pat = node.get("pattern", "")
            if "2026-27" in pat or node.get("maxLength") == 7 and "-" in pat:
                return "2026-27"
            return ""
        return None


def skeleton_itr2(schema: dict | None = None) -> dict:
    schema = schema or load_schema()
    sk = _Skeleton(schema)
    root = sk._resolve(schema)
    itr = sk._resolve(root["properties"]["ITR"])
    itr2_schema = itr["properties"]["ITR2"]
    return sk.build(itr2_schema, required_only=True)


def skeleton_of(*path: str, required_only: bool = True, schema: dict | None = None) -> Any:
    """Full (all-field) skeleton for a named ITR2 schedule/sub-path, e.g.
    skeleton_of('ScheduleCGFor23') or skeleton_of('PartB-TI', 'CapGain')."""
    schema = schema or load_schema()
    sk = _Skeleton(schema)
    node = sk._resolve(schema)
    node = sk._resolve(node["properties"]["ITR"])
    node = sk._resolve(node["properties"]["ITR2"])
    for p in path:
        node = sk._resolve(node)
        if "properties" not in node and "items" in node:
            node = sk._resolve(node["items"])
        node = node["properties"][p]
    return sk.build(node, required_only=required_only)


def validate(instance_itr2: dict, schema: dict | None = None) -> list[str]:
    """Return human-readable validation errors for {'ITR': {'ITR2': ...}}."""
    schema = schema or load_schema()
    doc = {"ITR": {"ITR2": instance_itr2}}
    errs = sorted(Draft4Validator(schema).iter_errors(doc), key=lambda e: list(map(str, e.path)))
    out, seen = [], set()
    for e in errs:
        loc = ".".join(str(p) for p in e.path)
        key = (loc, e.message[:50])
        if key in seen:
            continue
        seen.add(key)
        out.append(f"[{loc}] {e.message[:150]}")
    return out


if __name__ == "__main__":
    sk = skeleton_itr2()
    print("skeleton top-level keys:", sorted(sk.keys()))
    errs = validate(sk)
    print(f"\nskeleton self-validation errors: {len(errs)}")
    for e in errs[:20]:
        print("  " + e)
