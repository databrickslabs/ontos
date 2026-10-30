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
    """``[(table, row)]`` in FK-safe insertion order, normalized exactly as the API stores them."""
    from src.controller.access_policies_manager import clean_members, target_fields

    data = yaml.safe_load(source.read_text(encoding="utf-8"))
    ds = data["dataset"]
    out: List[Tuple[str, Dict[str, Any]]] = []
    refs: Dict[str, str] = {}

    for table, section in (("access_audiences", "audiences"), ("access_asset_collections", "asset_collections")):
        for seq, (key, spec) in enumerate((data.get(section) or {}).items(), start=1):
            row = _governed(table, seq, ds, spec, spec.get("status", "active"))
            row["members"] = clean_members(spec.get("members"))
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

    index_seq = 0
    for seq, (key, spec) in enumerate((data.get("policies") or {}).items(), start=1):
        ptype, conflict = spec.get("policy_type", "Set"), spec.get("conflict", odrl.DEFAULT_AUTHORED_CONFLICT)
        row = _governed("access_policies", seq, ds, spec, spec.get("status", "active"))
        subject = spec.get("subject") or {}
        row.update({
            "policy_type": ptype, "conflict": conflict, "inherit_from": [],
            "body": odrl.normalize_rules(ptype, conflict, [], resolve(spec["rules"])),
            "subject_entity_type": subject.get("entity_type"), "subject_entity_id": subject.get("entity_id"),
        })
        out.append(("access_policies", row))
        for kind, role, value in sorted(odrl.index_terms(row["body"])):
            index_seq += 1
            out.append(("access_policy_index", {"id": _id("access_policy_index", index_seq, ds), "policy_id": row["id"],
                                                "rule_kind": kind, "role": role, "value": value}))

    for seq, (key, spec) in enumerate((data.get("targets") or {}).items(), start=1):
        row = _governed("access_targets", seq, ds, spec, spec.get("status", "active"))
        row.update(target_fields({"system": "uc", **spec}, partial=False))
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
        index = table == "access_policy_index"
        head = cols + ([] if index else ["created_at", "updated_at"])
        values = ",\n".join("(" + ", ".join([_literal(r[c]) for c in cols] + ([] if index else ["NOW()", "NOW()"])) + ")"
                            for r in items)
        if index:
            # The index of a policy edited since the demo was loaded was rebuilt with new ids:
            # only seed the index of policies that have none, so a reload never brings back
            # stale terms next to the rebuilt ones.
            pos = {c: f"column{i}" for i, c in enumerate(cols, start=1)}
            lines.append(f"INSERT INTO {table} ({', '.join(cols)})")
            lines.append(f"SELECT {', '.join(pos.values())} FROM (VALUES")
            lines.append(values)
            lines.append(f") AS v WHERE NOT EXISTS (SELECT 1 FROM {table} i WHERE i.policy_id = v.{pos['policy_id']})")
        else:
            lines.append(f"INSERT INTO {table} ({', '.join(head)}) VALUES")
            lines.append(values)
        lines.append("ON CONFLICT (id) DO NOTHING;")
        lines.append("")
    lines.append(END)
    return "\n".join(lines)


def pack_block(pack: Path = PACK) -> str:
    """The generated block in the pack ('' if there is none); malformed markers raise."""
    text = pack.read_text(encoding="utf-8")
    start, end = text.find(BEGIN), text.find(END)
    if start < 0 and end < 0:
        return ""
    if start < 0 or end < start or text.count(BEGIN) != 1 or text.count(END) != 1:
        raise ValueError(f"{pack.name}: expected exactly one '{BEGIN}' followed by one '{END}'")
    return text[start:end + len(END)]


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
