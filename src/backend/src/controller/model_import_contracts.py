"""
Physical layer of a model import: plan and apply data contracts (PRD #1718).

Planning (preview, no writes):
  - map the in-scope tables to ODCS drafts (``map_contracts``),
  - resolve each table to an existing UC table asset and compute drift,
  - find the contract an earlier import created for the same group
    (``erwin.modelId`` + ``erwin.groupKey``) and decide the action:
      create       no earlier contract
      unchanged    same fingerprint
      update       earlier contract is a draft: replace its schema in place
      new_version  earlier contract is past draft: clone a new draft version
  - list earlier contracts whose group is gone from the model (removed).

Applying goes through ``DataContractsManager`` (create_from_upload,
clone_contract_for_new_version, update_contract_with_relations), so contract
import rules, semantic links and change logs apply as for any upload.
"""

from __future__ import annotations

import json
import threading
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional

from sqlalchemy import func
from sqlalchemy.orm import Session

from src.common.logging import get_logger
from src.model_import.erwin.ir import ErwinModel
from src.model_import.erwin.map_contracts import (
    CP_FINGERPRINT,
    CP_GROUP_KEY,
    CP_MODEL_ID,
    CP_REMOVED,
    ContractDraft,
    group_entities,
    map_contracts,
    table_name,
)
from src.model_import.erwin.match_uc import UcColumn, candidate_fqn, table_drift
from src.model_import.erwin.types import normalize_dbms
from src.models.model_import import ModelImportOptions

logger = get_logger(__name__)

PREVIEW_LIST_LIMIT = 200


@dataclass
class ExistingContract:
    id: str
    name: str
    version: str
    status: str
    group_key: str
    fingerprint: Optional[str]


@dataclass
class ContractAction:
    draft: ContractDraft
    action: str  # create | unchanged | update | new_version
    existing: Optional[ExistingContract] = None
    diff: Optional[Dict[str, Any]] = None


@dataclass
class ContractPlan:
    actions: List[ContractAction]
    removed: List[ExistingContract]
    resolution: List[Dict[str, Any]]
    warnings: List[str] = field(default_factory=list)

    def as_preview(self) -> Dict[str, Any]:
        resolved = [r for r in self.resolution if r["asset_id"]]
        unresolved = [r for r in self.resolution if not r["asset_id"]]
        counts: Dict[str, int] = {"create": 0, "unchanged": 0, "update": 0, "new_version": 0}
        for a in self.actions:
            counts[a.action] += 1
        return {
            "counts": {**counts, "removed": len(self.removed),
                       "tables": sum(len(a.draft.entity_ids) for a in self.actions)},
            "contracts": [
                {
                    "group_key": a.draft.group_key,
                    "group_label": a.draft.group_label,
                    "name": a.draft.name,
                    "action": a.action,
                    "tables": [o["name"] for o in a.draft.odcs["schema"]][:PREVIEW_LIST_LIMIT],
                    "table_count": len(a.draft.odcs["schema"]),
                    "existing_contract_id": a.existing.id if a.existing else None,
                    "existing_status": a.existing.status if a.existing else None,
                    "existing_version": a.existing.version if a.existing else None,
                    "diff": a.diff,
                    "warnings": a.draft.warnings,
                }
                for a in self.actions
            ],
            "removed": [
                {"contract_id": c.id, "name": c.name, "status": c.status, "group_key": c.group_key}
                for c in self.removed
            ],
            "uc": {
                "resolved": len(resolved),
                "unresolved": len(unresolved),
                "tables": self.resolution[:PREVIEW_LIST_LIMIT * 5],
            },
        }


# ----------------------------------------------------------------------
# UC resolution
# ----------------------------------------------------------------------

def _resolve_assets(db: Session, fqns: List[str]) -> Dict[str, Any]:
    """lower(FQN) → table/view asset, one query."""
    from src.controller.model_lineage import PHYSICAL_TABLE_TYPES
    from src.db_models.assets import AssetDb, AssetTypeDb
    if not fqns:
        return {}
    rows = (
        db.query(AssetDb)
        .join(AssetTypeDb, AssetDb.asset_type_id == AssetTypeDb.id)
        .filter(AssetTypeDb.name.in_(PHYSICAL_TABLE_TYPES))
        .filter(func.lower(AssetDb.location).in_(fqns))
        .all()
    )
    return {(r.location or "").lower(): r for r in rows}


def _uc_columns(db: Session, asset) -> List[UcColumn]:
    props = asset.properties or {}
    cols = ((props.get("schema") or {}).get("columns")) if isinstance(props, dict) else None
    if cols:
        return [UcColumn(name=c.get("name", ""), data_type=c.get("data_type"), nullable=c.get("nullable"))
                for c in cols if c.get("name")]
    from src.db_models.assets import AssetDb
    from src.db_models.entity_relationships import EntityRelationshipDb
    ids = [r.target_id for r in db.query(EntityRelationshipDb.target_id).filter(
        EntityRelationshipDb.source_id == str(asset.id),
        EntityRelationshipDb.relationship_type == "hasColumn",
    ).all()]
    out = []
    for row in db.query(AssetDb).filter(AssetDb.id.in_(ids)).all() if ids else []:
        p = row.properties or {}
        out.append(UcColumn(name=row.name, data_type=p.get("data_type"), nullable=p.get("nullable")))
    return out


def resolve_tables(db: Session, model: ErwinModel, options: ModelImportOptions) -> List[Dict[str, Any]]:
    dbms = options.dbms or normalize_dbms(model.target_dbms)
    entities = [e for _, _, ents in group_entities(model, options) for e in ents]
    fqn_by_entity = {e.id: candidate_fqn(e, options) for e in entities}
    assets = _resolve_assets(db, sorted({f for f in fqn_by_entity.values() if f}))
    out = []
    for e in entities:
        fqn = fqn_by_entity[e.id]
        asset = assets.get(fqn) if fqn else None
        entry: Dict[str, Any] = {
            "entity_id": e.id,
            "table": table_name(e),
            "owner": e.schema_name,
            "fqn": fqn,
            "asset_id": str(asset.id) if asset else None,
            "drift": None,
        }
        if asset is not None:
            drift = table_drift(e, _uc_columns(db, asset), dbms, model=model)
            entry["drift"] = None if drift.is_clean() else drift.as_dict()
        out.append(entry)
    return out


# ----------------------------------------------------------------------
# Existing contracts
# ----------------------------------------------------------------------

def _existing_contracts(db: Session, model_id: str) -> Dict[str, ExistingContract]:
    """group key → the latest contract an earlier import created for it."""
    from src.db_models.data_contracts import DataContractCustomPropertyDb, DataContractDb
    ids = [r.contract_id for r in db.query(DataContractCustomPropertyDb.contract_id).filter(
        DataContractCustomPropertyDb.property == CP_MODEL_ID,
        DataContractCustomPropertyDb.value == model_id,
    ).all()]
    if not ids:
        return {}
    props: Dict[str, Dict[str, str]] = {}
    for r in db.query(DataContractCustomPropertyDb).filter(
        DataContractCustomPropertyDb.contract_id.in_(ids),
        DataContractCustomPropertyDb.property.in_((CP_GROUP_KEY, CP_FINGERPRINT, CP_REMOVED)),
    ).all():
        props.setdefault(r.contract_id, {})[r.property] = r.value
    by_key: Dict[str, List[Any]] = {}
    for c in db.query(DataContractDb).filter(DataContractDb.id.in_(ids)).all():
        key = props.get(c.id, {}).get(CP_GROUP_KEY)
        if key:
            by_key.setdefault(key, []).append(c)
    latest: Dict[str, Any] = {}
    for key, cands in by_key.items():
        # The newest version: one no other candidate was cloned from.
        parents = {c.parent_contract_id for c in cands if c.parent_contract_id}
        heads = [c for c in cands if c.id not in parents] or cands
        latest[key] = max(heads, key=lambda c: (c.created_at is not None, c.created_at or 0, c.version or ""))
    return {
        key: ExistingContract(
            id=c.id, name=c.name, version=c.version, status=(c.status or "draft").lower(),
            group_key=key, fingerprint=props.get(c.id, {}).get(CP_FINGERPRINT),
        )
        for key, c in latest.items()
    }


def _norm(value: Any) -> Any:
    """Defaults the export writes (False, -1, "") compare equal to absent."""
    return None if value in (None, False, -1, "", [], {}) else value


def schema_diff(old_schema: List[Dict[str, Any]], new_schema: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Tables and columns added, removed and changed between two ODCS schemas."""
    def by_name(items):
        return {(i.get("name") or "").lower(): i for i in items or []}

    keys = ("physicalType", "logicalType", "required", "unique", "primaryKey", "primaryKeyPosition",
            "description", "businessName")
    old_t, new_t = by_name(old_schema), by_name(new_schema)
    changed = []
    for name in sorted(set(old_t) & set(new_t)):
        o_cols, n_cols = by_name(old_t[name].get("properties")), by_name(new_t[name].get("properties"))
        col_changes = []
        for c in sorted(set(o_cols) & set(n_cols)):
            fields = [k for k in keys if _norm(o_cols[c].get(k)) != _norm(n_cols[c].get(k))]
            if fields:
                col_changes.append({"column": n_cols[c].get("name"), "fields": fields})
        table_fields = [k for k in ("description", "businessName", "physicalName")
                        if _norm(old_t[name].get(k)) != _norm(new_t[name].get(k))]
        added = [n_cols[c].get("name") for c in sorted(set(n_cols) - set(o_cols))]
        removed = [o_cols[c].get("name") for c in sorted(set(o_cols) - set(n_cols))]
        if col_changes or added or removed or table_fields:
            changed.append({
                "table": new_t[name].get("name"), "columns_added": added, "columns_removed": removed,
                "columns_changed": col_changes, "fields": table_fields,
            })
    return {
        "tables_added": [new_t[n].get("name") for n in sorted(set(new_t) - set(old_t))],
        "tables_removed": [old_t[n].get("name") for n in sorted(set(old_t) - set(new_t))],
        "tables_changed": changed,
    }


def plan_contracts(db: Session, contracts_manager, model: ErwinModel, options: ModelImportOptions,
                   iri_by_id: Dict[str, str], run_id: Optional[str]) -> ContractPlan:
    resolution = resolve_tables(db, model, options)
    fqn_by_entity = {r["entity_id"]: r["fqn"] if r["asset_id"] else None for r in resolution}
    drafts = map_contracts(model, options, iri_by_id, fqn_by_entity, run_id=run_id)
    existing = _existing_contracts(db, model.id)
    actions: List[ContractAction] = []
    for d in drafts:
        ex = existing.get(d.group_key)
        if ex is None:
            actions.append(ContractAction(draft=d, action="create"))
            continue
        if ex.fingerprint == d.fingerprint:
            actions.append(ContractAction(draft=d, action="unchanged", existing=ex))
            continue
        diff = None
        if contracts_manager is not None:
            from src.db_models.data_contracts import DataContractDb
            db_obj = db.query(DataContractDb).filter(DataContractDb.id == ex.id).first()
            if db_obj is not None:
                diff = schema_diff(contracts_manager.build_odcs_from_db(db_obj, db).get("schema", []),
                                   d.odcs["schema"])
        actions.append(ContractAction(
            draft=d, action="update" if ex.status == "draft" else "new_version", existing=ex, diff=diff,
        ))

    produced = {d.group_key for d in drafts}
    removed: List[ExistingContract] = []
    if not options.subject_area_ids:
        # Only a full-model run can tell that a group left the model.
        removed = [c for k, c in existing.items() if k not in produced]

    unresolved = sum(1 for r in resolution if not r["asset_id"])
    warnings = []
    if unresolved:
        warnings.append(
            f"{unresolved} table(s) did not resolve to a Unity Catalog table; their contracts get no physical name."
        )
    drifted = sum(1 for r in resolution if r["drift"])
    if drifted:
        warnings.append(f"{drifted} table(s) differ from their Unity Catalog table (see drift).")
    return ContractPlan(actions=actions, removed=removed, resolution=resolution, warnings=warnings)


# ----------------------------------------------------------------------
# Apply
# ----------------------------------------------------------------------

def _merge_custom_properties(existing_odcs: Dict[str, Any], new_props: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """The import's erwin.* properties plus every other custom property the contract has."""
    managed = {p["property"] for p in new_props}
    kept = [p for p in (existing_odcs.get("customProperties") or [])
            if isinstance(p, dict) and p.get("property") not in managed
            and not str(p.get("property", "")).startswith("erwin.")]
    return kept + new_props


def _set_removed_flag(db: Session, contract_id: str, removed: bool) -> None:
    from src.db_models.data_contracts import DataContractCustomPropertyDb
    row = db.query(DataContractCustomPropertyDb).filter(
        DataContractCustomPropertyDb.contract_id == contract_id,
        DataContractCustomPropertyDb.property == CP_REMOVED,
    ).first()
    if removed and row is None:
        db.add(DataContractCustomPropertyDb(contract_id=contract_id, property=CP_REMOVED, value="true"))
    elif not removed and row is not None:
        db.delete(row)


def _notify_removed(notifications_manager, db: Session, contract, run_model: str) -> None:
    if not notifications_manager:
        return
    recipient = contract.draft_owner_id or contract.created_by
    if not recipient:
        return
    try:
        from datetime import datetime, timezone
        from uuid import uuid4
        from src.models.notifications import Notification, NotificationType
        notifications_manager.create_notification(Notification(
            id=str(uuid4()),
            type=NotificationType.INFO,
            title="Contract removed from its erwin model",
            subtitle=contract.name,
            message=(f"The tables of '{contract.name}' are no longer in the erwin model '{run_model}'. "
                     "Review whether to deprecate the contract."),
            link=f"/data-contracts/{contract.id}",
            recipient=recipient,
            created_at=datetime.now(timezone.utc),
        ), db=db)
    except Exception as exc:
        logger.warning("Could not notify about removed contract %s: %s", contract.id, exc)


DRIFT_NOTE_TITLE = "erwin model drift"


def drift_markdown(model_name: str, entries: List[Dict[str, Any]]) -> str:
    lines = [
        f"Differences between the erwin model **{model_name}** and the Unity Catalog tables "
        "of this contract, as of the last import.", "",
    ]
    for r in entries:
        d = r["drift"]
        lines.append(f"### {r['table']} → `{r['fqn']}`")
        if d["missing_in_uc"]:
            lines.append(f"- Modeled, missing in UC: {', '.join(d['missing_in_uc'])}")
        if d["extra_in_uc"]:
            lines.append(f"- In UC, not modeled: {', '.join(d['extra_in_uc'])}")
        for m in d["type_mismatches"]:
            lines.append(f"- Type of {m['column']}: modeled {m['modeled']}, UC {m['actual']}")
        for m in d["nullability_mismatches"]:
            modeled = "NOT NULL" if m["modeled_required"] else "NULL"
            actual = "NULL" if m["uc_nullable"] else "NOT NULL"
            lines.append(f"- Nullability of {m['column']}: modeled {modeled}, UC {actual}")
        lines.append("")
    return "\n".join(lines)


def _upsert_drift_note(db: Session, contract_id: str, markdown: Optional[str], actor: str) -> None:
    """Keep one drift note per contract: create, refresh, or remove when drift is gone."""
    from src.controller.metadata_manager import MetadataManager
    from src.models.metadata import RichTextCreate, RichTextUpdate
    mm = MetadataManager()
    existing = next((n for n in mm.list_rich_texts(db, entity_type="data_contract", entity_id=contract_id)
                     if n.title == DRIFT_NOTE_TITLE), None)
    if markdown is None:
        if existing is not None:
            mm.delete_rich_text(db, id=str(existing.id), user_email=actor)
        return
    if existing is not None:
        mm.update_rich_text(db, id=str(existing.id), data=RichTextUpdate(content_markdown=markdown), user_email=actor)
    else:
        mm.create_rich_text(db, data=RichTextCreate(
            entity_id=contract_id, entity_type="data_contract", title=DRIFT_NOTE_TITLE,
            short_description="Where the deployed tables differ from the erwin model.",
            content_markdown=markdown, level=40, inheritable=False,
        ), user_email=actor)


def apply_contracts(db: Session, contracts_manager, plan: ContractPlan, actor: str,
                    progress: Callable[[str], None], cancel_event: threading.Event,
                    notifications_manager=None, run_id: Optional[str] = None,
                    model_name: str = "") -> Dict[str, Any]:
    from src.db_models.data_contracts import DataContractDb

    results: List[Dict[str, Any]] = []
    total = len(plan.actions)
    for i, action in enumerate(plan.actions, start=1):
        if cancel_event.is_set():
            break
        d = action.draft
        progress(f"Contract {i}/{total}: {d.name}")
        entry: Dict[str, Any] = {"group_key": d.group_key, "name": d.name, "action": action.action}
        try:
            if action.action == "unchanged":
                entry["contract_id"] = action.existing.id
                _set_removed_flag(db, action.existing.id, False)
                db.commit()
            elif action.action == "create":
                created = contracts_manager.create_from_upload(
                    db, json.loads(json.dumps(d.odcs)), current_user=actor,
                    create_missing_domains=False, adopt_ids=False,
                )
                entry["contract_id"] = created.id
            else:
                target_id = action.existing.id
                if action.action == "new_version":
                    current = db.query(DataContractDb).filter(DataContractDb.id == target_id).first()
                    next_version = contracts_manager._calculate_next_version(current.version or "1.0.0", "minor")
                    clone = contracts_manager.clone_contract_for_new_version(
                        db, target_id, next_version,
                        change_summary=f"Updated from the erwin model '{model_name}' (import run {run_id}).",
                        current_user=actor,
                    )
                    target_id = clone.id
                    entry["previous_contract_id"] = action.existing.id
                target = db.query(DataContractDb).filter(DataContractDb.id == target_id).first()
                existing_odcs = contracts_manager.build_odcs_from_db(target, db)
                contracts_manager.update_contract_with_relations(
                    db, target_id,
                    {
                        "schema": json.loads(json.dumps(d.odcs["schema"])),
                        "description": d.odcs["description"],
                        "customProperties": _merge_custom_properties(existing_odcs, d.odcs["customProperties"]),
                    },
                    current_user=actor,
                )
                entry["contract_id"] = target_id
            drifted = [r for r in plan.resolution if r["drift"] and r["entity_id"] in set(d.entity_ids)]
            try:
                _upsert_drift_note(db, entry["contract_id"],
                                   drift_markdown(model_name, drifted) if drifted else None, actor)
            except Exception as exc:
                logger.warning("Could not write the drift note for contract %s: %s", entry["contract_id"], exc)
                db.rollback()
            entry["status"] = "ok"
        except Exception as exc:
            logger.exception("Model import: contract '%s' failed", d.name)
            db.rollback()
            entry["status"] = "failed"
            entry["error"] = str(exc)
        results.append(entry)

    flagged = []
    for c in plan.removed:
        if cancel_event.is_set():
            break
        try:
            _set_removed_flag(db, c.id, True)
            db.commit()
            contract = db.query(DataContractDb).filter(DataContractDb.id == c.id).first()
            if contract is not None:
                _notify_removed(notifications_manager, db, contract, model_name)
                db.commit()
            flagged.append({"contract_id": c.id, "name": c.name})
        except Exception as exc:
            logger.warning("Could not flag removed contract %s: %s", c.id, exc)
            db.rollback()

    return {
        "contracts": results,
        "removed": flagged,
        "uc": {
            "resolved": sum(1 for r in plan.resolution if r["asset_id"]),
            "unresolved": sum(1 for r in plan.resolution if not r["asset_id"]),
            "drift": [r for r in plan.resolution if r["drift"]][:PREVIEW_LIST_LIMIT],
        },
        "failed": sum(1 for r in results if r["status"] == "failed"),
    }
