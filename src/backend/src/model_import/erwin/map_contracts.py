"""Physical layer of an erwin model → draft ODCS v3.1 contracts.

| erwin                      | ODCS                                                          |
|----------------------------|---------------------------------------------------------------|
| Table / view               | schema object (name = table, physicalName = UC FQN)           |
| Column                     | property (physicalType, logicalType, required, businessName)  |
| PK                         | primaryKey + primaryKeyPosition                               |
| Single-column AK           | unique                                                        |
| Multi-column AK            | customProperties erwin.alternateKeys                          |
| FK (relationship)          | schema-level relationships[] (composite keys as arrays)       |
| Default, domain, valid set | customProperties erwin.*                                      |
| UDPs                       | per mapping: classification, criticalDataElement, tags, or    |
|                            | customProperties erwin.udp.<name> (default)                   |
| Entity / attribute concept | authoritativeDefinitions semantic assignment → semantic link  |

Tables are grouped into contracts by subject area (default), owner/schema,
table, or one contract for the whole model. A contract carries
``erwin.modelId`` and ``erwin.groupKey``, which re-imports use to find it,
and ``erwin.fingerprint``, a hash of the generated content that tells an
unchanged contract from a changed one.
"""
from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

from src.model_import.erwin.builder import entities_in
from src.model_import.erwin.ir import ErwinAttribute, ErwinEntity, ErwinModel, KeyKind, RelationshipKind
from src.model_import.erwin.map_concepts import semantic_iri_for_attribute
from src.model_import.erwin.types import (
    databricks_type_for,
    migration_warning,
    normalize_dbms,
    odcs_logical_type,
)
from src.models.model_import import ModelImportOptions

# Same value as src.utils.semantic_helpers.SEMANTIC_ASSIGNMENT_TYPE; contract
# import turns these authoritative definitions into semantic links.
SEMANTIC_ASSIGNMENT_TYPE = "http://databricks.com/ontology/uc/semanticAssignment"

CP_MODEL_ID = "erwin.modelId"
CP_GROUP_KEY = "erwin.groupKey"
CP_FINGERPRINT = "erwin.fingerprint"
CP_RUN_ID = "erwin.runId"
CP_OBJECT_ID = "erwin.id"
CP_REMOVED = "erwin.removedInSource"

_TRUE = {"true", "yes", "y", "1", "x"}
UNASSIGNED = "__unassigned__"


@dataclass
class ContractDraft:
    group_key: str
    group_label: str
    name: str
    odcs: Dict[str, Any]
    entity_ids: List[str]
    fingerprint: str
    warnings: List[str] = field(default_factory=list)


def _slug(text: str) -> str:
    return re.sub(r"[^A-Za-z0-9]+", "-", text).strip("-").lower() or "x"


def _cp(name: str, value: Any) -> Dict[str, Any]:
    return {"property": name, "value": value}


def group_entities(model: ErwinModel, options: ModelImportOptions) -> List[Tuple[str, str, List[ErwinEntity]]]:
    """(group key, label, entities) in a stable order."""
    entities = [e for e in entities_in(model, options.subject_area_ids) if not e.logical_only]
    grouping = options.contract_grouping
    groups: Dict[str, Tuple[str, List[ErwinEntity]]] = {}

    def put(key: str, label: str, e: ErwinEntity) -> None:
        groups.setdefault(key, (label, []))[1].append(e)

    if grouping == "model":
        for e in entities:
            put("model", model.name, e)
    elif grouping == "table":
        for e in entities:
            put(f"table:{e.id}", e.physical_name or e.name, e)
    elif grouping == "schema":
        for e in entities:
            schema = e.schema_name or ""
            put(f"schema:{schema.lower()}", schema or UNASSIGNED, e)
    else:
        order = options.subject_area_ids or [s.id for s in model.subject_areas]
        by_id = {s.id: s for s in model.subject_areas}
        ordered = [by_id[i] for i in order if i in by_id]
        for e in entities:
            sa = next((s for s in ordered if e.id in s.entity_ids), None)
            if sa is None:
                put(f"sa:{UNASSIGNED}", UNASSIGNED, e)
            else:
                put(f"sa:{sa.id}", sa.name, e)
    return [(k, label, ents) for k, (label, ents) in groups.items()]


def _udp_targets(options: ModelImportOptions) -> Dict[str, str]:
    return {m.udp.strip().lower(): m.target for m in options.udp_mappings}


def _apply_udps(udps: Dict[str, str], targets: Dict[str, str], target: Dict[str, Any],
                tags: List[str], custom: List[Dict[str, Any]], is_property: bool,
                warnings: List[str], where: str) -> None:
    for name, value in udps.items():
        how = targets.get(name.lower(), "custom_property")
        if how == "ignore":
            continue
        if how == "classification" and is_property:
            target["classification"] = value
        elif how == "critical_data_element" and is_property:
            target["criticalDataElement"] = value.strip().lower() in _TRUE
        elif how == "tag":
            tags.append(f"{name}:{value}")
        else:
            if how not in ("custom_property",):
                warnings.append(f"UDP '{name}' on {where}: '{how}' applies to columns only; kept as a custom property.")
            custom.append(_cp(f"erwin.udp.{name}", value))


def _column_name(a: ErwinAttribute) -> str:
    return a.physical_name or a.name.replace(" ", "_")


def table_name(e: ErwinEntity) -> str:
    return e.physical_name or e.name.replace(" ", "_")


def _property(model: ErwinModel, e: ErwinEntity, a: ErwinAttribute, pk_pos: Dict[str, int],
              unique_ids: set, options: ModelImportOptions, dbms: str, iri_by_id: Dict[str, str],
              udp_targets: Dict[str, str], warnings: List[str]) -> Dict[str, Any]:
    domain = model.domain(a.domain_id) if a.domain_id else None
    physical = a.physical_type or (domain.physical_type if domain else None)
    logical = a.logical_type or (domain.logical_type if domain else None)
    custom: List[Dict[str, Any]] = [_cp(CP_OBJECT_ID, a.id)]
    prop: Dict[str, Any] = {
        "name": _column_name(a),
        "businessName": a.name,
        "logicalType": odcs_logical_type(logical, physical),
    }
    if options.migration_mode and dbms != "databricks":
        mapped = databricks_type_for(physical, dbms, logical)
        if mapped:
            prop["physicalType"] = mapped
            if physical:
                custom.append(_cp("erwin.sourcePhysicalType", physical))
            note = migration_warning(physical, dbms)
            if note:
                warnings.append(f"{table_name(e)}.{_column_name(a)}: {note}")
        elif physical:
            prop["physicalType"] = physical
    elif physical:
        prop["physicalType"] = physical
    if a.definition:
        prop["description"] = a.definition
    if a.id in pk_pos:
        prop["primaryKey"] = True
        prop["primaryKeyPosition"] = pk_pos[a.id]
        prop["required"] = True
    else:
        prop["required"] = a.nullable is False
    if a.id in unique_ids:
        prop["unique"] = True
    if a.default_value:
        custom.append(_cp("erwin.default", a.default_value))
    if domain is not None and not domain.is_builtin:
        custom.append(_cp("erwin.domain", domain.name))
    valid = a.valid_values or (domain.valid_values if domain else [])
    if valid:
        custom.append(_cp("erwin.validValues", list(valid)))
    tags: List[str] = []
    _apply_udps(a.udps, udp_targets, prop, tags, custom, True, warnings, f"{table_name(e)}.{_column_name(a)}")
    if tags:
        # Column-level tags have no ODCS home in Ontos; keep them visible.
        custom.append(_cp("erwin.tags", tags))
    iri = semantic_iri_for_attribute(model, a, iri_by_id)
    if iri:
        prop["authoritativeDefinitions"] = [{"type": SEMANTIC_ASSIGNMENT_TYPE, "url": iri}]
    prop["customProperties"] = custom
    return prop


def _schema_object(model: ErwinModel, e: ErwinEntity, options: ModelImportOptions, dbms: str,
                   fqn: Optional[str], iri_by_id: Dict[str, str], udp_targets: Dict[str, str],
                   warnings: List[str]) -> Dict[str, Any]:
    pk = e.primary_key()
    pk_pos = {aid: i + 1 for i, aid in enumerate(pk.attribute_ids)} if pk else {}
    unique_ids = set()
    multi_aks: List[List[str]] = []
    attr_by_id = {a.id: a for a in e.attributes}
    for k in e.key_groups:
        if k.kind != KeyKind.ALTERNATE or not k.attribute_ids:
            continue
        if len(k.attribute_ids) == 1:
            unique_ids.add(k.attribute_ids[0])
        else:
            multi_aks.append([_column_name(attr_by_id[i]) for i in k.attribute_ids if i in attr_by_id])

    obj: Dict[str, Any] = {
        "name": table_name(e),
        "physicalType": "view" if e.is_view else "table",
        "businessName": e.name,
    }
    if fqn:
        obj["physicalName"] = fqn
    if e.definition:
        obj["description"] = e.definition
    custom: List[Dict[str, Any]] = [_cp(CP_OBJECT_ID, e.id)]
    if e.schema_name:
        custom.append(_cp("erwin.owner", e.schema_name))
    if e.note:
        custom.append(_cp("erwin.note", e.note))
    if e.view_sql:
        custom.append(_cp("erwin.viewSql", e.view_sql))
    if multi_aks:
        custom.append(_cp("erwin.alternateKeys", multi_aks))
    tags: List[str] = []
    _apply_udps(e.udps, udp_targets, obj, tags, custom, False, warnings, table_name(e))
    if tags:
        obj["tags"] = tags
    obj["properties"] = [
        _property(model, e, a, pk_pos, unique_ids, options, dbms, iri_by_id, udp_targets, warnings)
        for a in e.attributes if not a.logical_only
    ]
    iri = iri_by_id.get(e.id)
    if iri:
        obj["authoritativeDefinitions"] = [{"type": SEMANTIC_ASSIGNMENT_TYPE, "url": iri}]
    obj["customProperties"] = custom
    return obj


def _foreign_keys(model: ErwinModel, child: ErwinEntity, in_contract: set) -> Tuple[List[Dict[str, Any]], int]:
    """Schema-level FKs of ``child``; the count of those pointing outside the contract."""
    rels = []
    external = 0
    for r in model.relationships:
        if r.child_id != child.id or not r.fk_pairs or r.kind == RelationshipKind.MANY_TO_MANY:
            continue
        parent = model.entity(r.parent_id)
        if parent is None:
            continue
        pairs = [(model.attribute(c), model.attribute(p)) for c, p in r.fk_pairs]
        pairs = [(c, p) for c, p in pairs if c is not None and p is not None and not c.logical_only]
        if not pairs:
            continue
        src = [f"{table_name(child)}.{_column_name(c)}" for c, _ in pairs]
        dst = [f"{table_name(parent)}.{_column_name(p)}" for _, p in pairs]
        custom = [_cp(CP_OBJECT_ID, r.id), _cp("erwin.relationshipKind", r.kind.value)]
        if r.name:
            custom.append(_cp("erwin.relationshipName", r.name))
        if r.cardinality:
            custom.append(_cp("cardinality", r.cardinality))
        if r.parent_to_child_phrase:
            custom.append(_cp("description", r.parent_to_child_phrase))
        if parent.id not in in_contract:
            external += 1
        rels.append({
            "type": "foreignKey",
            "from": src[0] if len(src) == 1 else src,
            "to": dst[0] if len(dst) == 1 else dst,
            "customProperties": custom,
        })
    return rels, external


def fingerprint(odcs: Dict[str, Any]) -> str:
    """Hash of the generated content, excluding run bookkeeping (run id, the fingerprint)."""
    def strip(o):
        if isinstance(o, dict):
            return {k: strip(v) for k, v in o.items()}
        if isinstance(o, list):
            return [strip(v) for v in o
                    if not (isinstance(v, dict) and v.get("property") in (CP_RUN_ID, CP_FINGERPRINT))]
        return o
    payload = json.dumps(strip(odcs), sort_keys=True, default=str)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:32]


def map_contracts(
    model: ErwinModel,
    options: ModelImportOptions,
    iri_by_id: Dict[str, str],
    fqn_by_entity: Dict[str, Optional[str]],
    run_id: Optional[str] = None,
) -> List[ContractDraft]:
    dbms = options.dbms or normalize_dbms(model.target_dbms)
    udp_targets = _udp_targets(options)
    drafts: List[ContractDraft] = []
    sa_by_id = {s.id: s for s in model.subject_areas}
    for key, label, entities in group_entities(model, options):
        warnings: List[str] = []
        in_contract = {e.id for e in entities}
        schema = []
        external_fks = 0
        for e in entities:
            obj = _schema_object(model, e, options, dbms, fqn_by_entity.get(e.id), iri_by_id, udp_targets, warnings)
            fks, ext = _foreign_keys(model, e, in_contract)
            if fks:
                obj["relationships"] = fks
            external_fks += ext
            schema.append(obj)
        if external_fks:
            warnings.append(f"{external_fks} foreign key(s) reference tables in another contract.")
        group_label = label if label != UNASSIGNED else "Unassigned"
        name = model.name if key == "model" else f"{model.name} – {group_label}"
        purpose = None
        if key.startswith("sa:") and key[3:] in sa_by_id:
            purpose = sa_by_id[key[3:]].definition
        odcs: Dict[str, Any] = {
            # Stable per model and group; Ontos keeps it as the original id.
            "id": f"urn:erwin:{_slug(model.id)}:{_slug(key)}",
            "apiVersion": "v3.1.0",
            "kind": "DataContract",
            "name": name,
            "version": "1.0.0",
            "status": "draft",
            "description": {"purpose": purpose or f"Imported from the erwin model '{model.name}'."},
            "schema": schema,
            "customProperties": [
                _cp(CP_MODEL_ID, model.id),
                _cp(CP_GROUP_KEY, key),
                _cp("erwin.modelName", model.name),
                _cp("erwin.dbms", dbms),
            ] + ([_cp("erwin.modelVersion", model.version)] if model.version else []),
        }
        domain_id = options.domain_by_group.get(key)
        if domain_id:
            odcs["customProperties"].append(_cp("ontosDomainId", [domain_id]))
        fp = fingerprint(odcs)
        odcs["customProperties"].append(_cp(CP_FINGERPRINT, fp))
        if run_id:
            odcs["customProperties"].append(_cp(CP_RUN_ID, run_id))
        drafts.append(ContractDraft(
            group_key=key, group_label=group_label, name=name, odcs=odcs,
            entity_ids=[e.id for e in entities], fingerprint=fp, warnings=warnings,
        ))
    return drafts
