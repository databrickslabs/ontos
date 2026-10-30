"""Access Policies demo example: ``data/demo_access_policies.yaml`` → rows → demo-pack SQL.

The YAML is the readable source; :func:`render_sql` produces the generated block inside
``demo_data_retail.sql`` (between the BEGIN/END markers) so loading and the demo teardown —
which parses the pack's INSERTs — treat it like every other demo row. :func:`rows` gives the
same rows to tests, which insert them through the ORM and run the end-to-end flow.

Regenerate after editing the YAML::

    hatch -e dev run python -m src.utils.demo_access_policies --write
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Tuple

import yaml

from src.common import odrl

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
SOURCE = DATA_DIR / "demo_access_policies.yaml"
PACK = DATA_DIR / "demo_data_retail.sql"
BEGIN = "-- BEGIN access policies (generated from demo_access_policies.yaml — do not edit by hand)"
END = "-- END access policies"

AUTHOR = "system@demo"
APPROVER = "steward@demo"

_TYPE = {"access_audiences": "1a0", "access_asset_collections": "1a1", "access_policies": "1a2",
         "access_targets": "1a3", "access_policy_index": "1a4"}
_UID = {"access_audiences": "urn:ontos:audience:", "access_asset_collections": "urn:ontos:asset-collection:",
        "access_policies": "urn:ontos:policy:", "access_targets": "urn:ontos:target:"}


def _id(table: str, seq: int, dataset: str) -> str:
    return f"{_TYPE[table]}{seq:05x}-{dataset}-4000-8000-{seq:012d}"


def _governed(table: str, seq: int, dataset: str, spec: Dict[str, Any], status: str) -> Dict[str, Any]:
    rid = _id(table, seq, dataset)
    active_path = status in ("approved", "active")
    return {
        "id": rid, "uid": _UID[table] + rid, "name": spec["name"], "description": spec.get("description"),
        "status": status, "version": "1.0.0", "version_family_id": rid,
        "created_by": AUTHOR, "updated_by": AUTHOR,
        "submitted_by": AUTHOR if active_path else None, "approved_by": APPROVER if active_path else None,
    }


def rows(source: Path = SOURCE) -> List[Tuple[str, Dict[str, Any]]]:
    """``[(table, row)]`` in FK-safe insertion order."""
    from src.controller.access_policies_manager import AccessPoliciesManager

    data = yaml.safe_load(source.read_text(encoding="utf-8"))
    ds = data["dataset"]
    out: List[Tuple[str, Dict[str, Any]]] = []
    refs: Dict[str, str] = {}

    for table, section in (("access_audiences", "audiences"), ("access_asset_collections", "asset_collections")):
        for seq, (key, spec) in enumerate((data.get(section) or {}).items(), start=1):
            row = _governed(table, seq, ds, spec, spec.get("status", "active"))
            row["members"] = list(spec.get("members") or [])
            row["refinement"] = [odrl.normalize_constraint(c) for c in spec.get("refinement") or []]
            refs[key] = row["uid"]
            out.append((table, row))

    def resolve(value: Any) -> Any:
        if isinstance(value, str) and value.startswith("@"):
            return refs[value[1:]]
        if isinstance(value, list):
            return [resolve(v) for v in value]
        if isinstance(value, dict):
            return {k: resolve(v) for k, v in value.items()}
        return value

    manager = AccessPoliciesManager(attribute_sources=[])
    index_seq = 0
    for seq, (key, spec) in enumerate((data.get("policies") or {}).items(), start=1):
        ptype, conflict = spec.get("policy_type", "Set"), spec.get("conflict", odrl.DEFAULT_AUTHORED_CONFLICT)
        row = _governed("access_policies", seq, ds, spec, spec.get("status", "active"))
        subject = spec.get("subject") or {}
        row.update({
            "policy_type": ptype, "conflict": conflict, "inherit_from": [],
            "body": manager._normalize_rules(ptype, conflict, [], resolve(spec["rules"])),
            "subject_entity_type": subject.get("entity_type"), "subject_entity_id": subject.get("entity_id"),
        })
        out.append(("access_policies", row))
        for kind, role, value in sorted(odrl.index_terms(row["body"])):
            index_seq += 1
            out.append(("access_policy_index", {"id": _id("access_policy_index", index_seq, ds), "policy_id": row["id"],
                                                "rule_kind": kind, "role": role, "value": value}))

    for seq, (key, spec) in enumerate((data.get("targets") or {}).items(), start=1):
        row = _governed("access_targets", seq, ds, spec, spec.get("status", "active"))
        row.update({"key": spec["key"], "system": spec.get("system", "uc"), "connection": spec.get("connection") or {},
                    "scope": list(spec.get("scope") or []), "delivery_modes": list(spec.get("delivery_modes") or []),
                    "reconcile_schedule": spec.get("reconcile_schedule"), "drift_policy": "report"})
        out.append(("access_targets", row))
    return out


def _literal(value: Any) -> str:
    if value is None:
        return "NULL"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (dict, list)):
        value = json.dumps(value, sort_keys=True, ensure_ascii=False)
    return "'" + str(value).replace("'", "''") + "'"


def render_sql(source: Path = SOURCE) -> str:
    """The generated pack block: one INSERT per table, ON CONFLICT DO NOTHING (re-runnable)."""
    by_table: Dict[str, List[Dict[str, Any]]] = {}
    for table, row in rows(source):
        by_table.setdefault(table, []).append(row)
    lines = [BEGIN, "-- Audiences, asset collections, policies (+ index) and the UC target of the Access Policies",
             "-- example. Source: data/demo_access_policies.yaml.", ""]
    for table, items in by_table.items():
        cols = list(items[0])
        timestamps = table != "access_policy_index"
        head = cols + (["created_at", "updated_at"] if timestamps else [])
        lines.append(f"INSERT INTO {table} ({', '.join(head)}) VALUES")
        values = []
        for r in items:
            vals = [_literal(r[c]) for c in cols] + (["NOW()", "NOW()"] if timestamps else [])
            values.append("(" + ", ".join(vals) + ")")
        lines.append(",\n".join(values))
        lines.append("ON CONFLICT (id) DO NOTHING;")
        lines.append("")
    lines.append(END)
    return "\n".join(lines)


def pack_block(pack: Path = PACK) -> str:
    text = pack.read_text(encoding="utf-8")
    start, end = text.find(BEGIN), text.find(END)
    return text[start:end + len(END)] if start >= 0 and end >= 0 else ""


def write_pack(pack: Path = PACK) -> None:
    text = pack.read_text(encoding="utf-8")
    block = render_sql()
    current = pack_block(pack)
    text = text.replace(current, block) if current else text.rstrip("\n") + "\n\n" + block + "\n"
    pack.write_text(text, encoding="utf-8")


if __name__ == "__main__":  # pragma: no cover - maintenance entry point
    import sys

    if "--write" in sys.argv:
        write_pack()
        print(f"Updated {PACK.name}")
    else:
        print(render_sql())
