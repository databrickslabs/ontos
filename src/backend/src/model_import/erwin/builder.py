"""Build the IR from the raw objects of an erwin XML export.

All erwin-specific property names and codes live here. erwin writes some
properties as names ("Not Null", "Identifying") and others as numeric codes,
depending on the version and the export option. Both are accepted. When a value
is missing or unknown, it is inferred where that is safe (e.g. an identifying
relationship is one whose migrated key is part of the child's primary key) and
a warning is recorded. Inferred values are never silently treated as read.
"""
from __future__ import annotations

import re
from collections import defaultdict
from typing import Dict, Iterable, List, Optional

from src.model_import.erwin.ir import (
    ErwinAttribute,
    ErwinDomain,
    ErwinEntity,
    ErwinKeyGroup,
    ErwinModel,
    ErwinRelationship,
    ErwinSubjectArea,
    ErwinSubtypeGroup,
    KeyKind,
    ModelType,
    RelationshipKind,
)
from src.model_import.erwin.xml_reader import RawModel, RawObject

# Root domains every erwin model carries; never mapped to Ontos.
BUILTIN_DOMAINS = {"<default>", "<unknown>", "blob", "datetime", "number", "string"}

_TRUE = {"true", "yes", "1", "t", "y"}

_UDP_KEY = re.compile(
    r"^(?:UDP:)?(?:Model|Entity|Attribute|Relationship|Subject_Area|Domain|Key_Group)"
    r"\.(?:Logical|Physical)\.(.+)$"
)

_REL_KIND_BY_NAME = {
    "identifying": RelationshipKind.IDENTIFYING,
    "non-identifying": RelationshipKind.NON_IDENTIFYING,
    "non identifying": RelationshipKind.NON_IDENTIFYING,
    "nonidentifying": RelationshipKind.NON_IDENTIFYING,
    "many-to-many": RelationshipKind.MANY_TO_MANY,
    "many to many": RelationshipKind.MANY_TO_MANY,
    "subtype": RelationshipKind.SUBTYPE,
}
# erwin metamodel codes for Relationship.Type
_REL_KIND_BY_CODE = {
    "2": RelationshipKind.IDENTIFYING,
    "7": RelationshipKind.NON_IDENTIFYING,
    "4": RelationshipKind.MANY_TO_MANY,
}
_CARDINALITY_BY_CODE = {
    "-1": "zero_or_more",
    "-2": "one_or_more",
    "-3": "zero_or_one",
}


def _bool(value: Optional[str]) -> Optional[bool]:
    if value is None:
        return None
    return value.strip().lower() in _TRUE


def _nullable(raw: RawObject) -> Optional[bool]:
    """erwin Null_Option: 0 / "Null" = nullable, 1 / "Not Null" = required."""
    value = raw.first("Null_Option_Type", "Null_Option")
    if value is None:
        return None
    v = value.strip().lower().replace("_", " ")
    if v in ("0", "null", "nulls allowed"):
        return True
    if v in ("1", "not null", "no nulls", "notnull"):
        return False
    return None


def _model_type(raw: RawObject, has_logical: bool, has_physical: bool) -> ModelType:
    value = (raw.first("Model_Type", "Type") or "").strip().lower()
    if "logical" in value and "physical" in value:
        return ModelType.LOGICAL_PHYSICAL
    if value == "logical":
        return ModelType.LOGICAL
    if value == "physical":
        return ModelType.PHYSICAL
    if has_logical and has_physical:
        return ModelType.LOGICAL_PHYSICAL
    return ModelType.PHYSICAL if has_physical else ModelType.LOGICAL


_KEY_KIND_BY_NAME = {
    "primary key": KeyKind.PRIMARY, "primary": KeyKind.PRIMARY,
    "alternate key": KeyKind.ALTERNATE, "alternate": KeyKind.ALTERNATE, "unique": KeyKind.ALTERNATE,
    "unique key": KeyKind.ALTERNATE,
    "inversion entry": KeyKind.INVERSION, "inversion": KeyKind.INVERSION, "index": KeyKind.INVERSION,
    "foreign key": KeyKind.FOREIGN, "foreign": KeyKind.FOREIGN,
}


def _key_kind(raw: RawObject) -> Optional[KeyKind]:
    """PK / AK / IE / IF from Key_Group_Type ("PK", "AK1", "Primary Key", ...).

    Falls back to erwin's generated key names (XPK…, XAK…, XIE…, XIF…).
    Numeric type codes are not documented, so they fall through to the name.
    """
    value = (raw.first("Key_Group_Type") or "").strip()
    by_name = _KEY_KIND_BY_NAME.get(value.lower().replace("_", " "))
    if by_name:
        return by_name
    upper = value.upper()
    for kind in (KeyKind.PRIMARY, KeyKind.ALTERNATE, KeyKind.INVERSION, KeyKind.FOREIGN):
        if re.fullmatch(kind.value + r"\d*", upper):
            return kind
    name = (raw.first("Name") or raw.name or "").upper()
    for kind in (KeyKind.PRIMARY, KeyKind.ALTERNATE, KeyKind.INVERSION, KeyKind.FOREIGN):
        if name.startswith("X" + kind.value):
            return kind
    return None


def _cardinality(value: Optional[str]) -> Optional[str]:
    if value is None:
        return None
    v = value.strip()
    if v in _CARDINALITY_BY_CODE:
        return _CARDINALITY_BY_CODE[v]
    if v.isdigit():
        return f"exactly:{v}"
    return v.lower().replace(" ", "_").replace(",", "")


def _udps(raw: RawObject) -> Dict[str, str]:
    out: Dict[str, str] = {}
    for key, values in raw.props.items():
        m = _UDP_KEY.match(key)
        if not m and key.startswith("UDP:"):
            name = key[4:]
        elif m:
            name = m.group(1)
        else:
            continue
        vals = [v for v in values if v]
        if vals:
            out[name.replace("_", " ")] = vals[0] if len(vals) == 1 else ", ".join(vals)
    return out


def _name(raw: RawObject) -> str:
    return raw.first("Name") or raw.name or raw.id


def build_model(raw: RawModel, source_format: str = "erwin_xml") -> ErwinModel:
    """Build the IR from raw objects. Never raises for content problems; they become warnings."""
    warnings: List[str] = []
    by_type: Dict[str, List[RawObject]] = defaultdict(list)
    by_id: Dict[str, RawObject] = {}
    children: Dict[str, List[RawObject]] = defaultdict(list)
    for o in raw.objects:
        by_type[o.type].append(o)
        by_id[o.id] = o
        if o.parent_id:
            children[o.parent_id].append(o)

    model_raw = by_type["Model"][0]

    # Validation rules → valid values
    valid_values_by_rule: Dict[str, List[str]] = {}
    for rule in by_type.get("Validation_Rule", []):
        values = [
            v.first("Value", "Valid_Value", "Name") or v.name
            for v in children.get(rule.id, ())
            if v.type in ("Valid_Value", "Validation_Rule_Valid_Value")
        ]
        values += rule.all("Valid_Values")
        valid_values_by_rule[rule.id] = [v for v in values if v]

    def _valid_values(o: RawObject) -> List[str]:
        out: List[str] = []
        for ref in o.all("Validation_Rule_Ref") + o.all("Attribute_Validation_Rule_Ref"):
            out += valid_values_by_rule.get(ref, [])
        return out

    # Domains
    domains: List[ErwinDomain] = []
    for d in by_type.get("Domain", []):
        name = _name(d)
        domains.append(ErwinDomain(
            id=d.id,
            name=name,
            logical_type=d.first("Logical_Data_Type"),
            physical_type=d.first("Physical_Data_Type", "Datatype"),
            definition=d.first("Definition", "Comment"),
            parent_id=d.first("Parent_Domain_Ref"),
            valid_values=_valid_values(d),
            is_builtin=name.strip().lower() in BUILTIN_DOMAINS,
        ))

    schema_names = {s.id: _name(s) for s in by_type.get("Schema", [])}

    # Entities (tables) and views
    entities: List[ErwinEntity] = []
    has_logical = has_physical = False
    for e in by_type.get("Entity", []) + by_type.get("View", []):
        is_view = e.type == "View"
        attrs: List[ErwinAttribute] = []
        for a in children.get(e.id, ()):
            if a.type not in ("Attribute", "View_Column"):
                continue
            logical_type = a.first("Logical_Data_Type")
            physical_type = a.first("Physical_Data_Type", "Datatype")
            physical_name = a.first("Physical_Name", "Column_Name")
            has_logical = has_logical or bool(logical_type)
            has_physical = has_physical or bool(physical_type)
            attrs.append(ErwinAttribute(
                id=a.id,
                name=_name(a),
                physical_name=physical_name,
                logical_type=logical_type,
                physical_type=physical_type,
                nullable=_nullable(a),
                default_value=a.first("Default_Value", "Default"),
                domain_id=a.first("Parent_Domain_Ref"),
                definition=a.first("Definition", "Comment"),
                parent_attribute_id=a.first("Parent_Attribute_Ref"),
                parent_relationship_id=a.first("Parent_Relationship_Ref"),
                valid_values=_valid_values(a),
                logical_only=bool(_bool(a.first("Logical_Only"))),
                physical_only=bool(_bool(a.first("Physical_Only"))),
                udps=_udps(a),
            ))

        attr_ids = {a.id for a in attrs}
        keys: List[ErwinKeyGroup] = []
        for k in children.get(e.id, ()):
            if k.type != "Key_Group":
                continue
            kind = _key_kind(k)
            if kind is None:
                warnings.append(f"Key group '{_name(k)}' on '{_name(e)}' has an unknown type; skipped.")
                continue
            members: List[tuple] = []
            for i, m in enumerate(children.get(k.id, ())):
                if m.type != "Key_Group_Member":
                    continue
                ref = m.first("Attribute_Ref")
                if ref not in attr_ids:
                    warnings.append(
                        f"Key group '{_name(k)}' on '{_name(e)}' references an unknown attribute; member skipped."
                    )
                    continue
                pos = m.first("Key_Group_Position", "Order")
                members.append((int(pos) if pos and pos.lstrip("-").isdigit() else i, ref))
            members.sort(key=lambda t: t[0])
            keys.append(ErwinKeyGroup(
                id=k.id, name=_name(k), kind=kind, attribute_ids=[r for _, r in members],
            ))

        schema = e.first("Owner", "Name_Qualifier", "Schema_Name")
        schema_ref = e.first("Schema_Ref")
        if not schema and schema_ref:
            schema = schema_names.get(schema_ref)

        entities.append(ErwinEntity(
            id=e.id,
            name=_name(e),
            physical_name=e.first("Physical_Name", "Table_Name"),
            schema_name=schema,
            definition=e.first("Definition", "Comment"),
            note=e.first("Note", "Notes"),
            is_view=is_view,
            view_sql=e.first("View_SQL", "SQL", "Sql", "View_Sql") if is_view else None,
            logical_only=bool(_bool(e.first("Logical_Only"))),
            physical_only=bool(_bool(e.first("Physical_Only"))),
            attributes=attrs,
            key_groups=keys,
            udps=_udps(e),
        ))

    entity_by_id = {e.id: e for e in entities}
    entity_ids = set(entity_by_id)
    pk_attr_ids = {
        e.id: set(e.primary_key().attribute_ids) if e.primary_key() else set()
        for e in entities
    }

    # Subtype symbols → which relationships are subtype relationships
    subtype_rel_ids: Dict[str, str] = {}
    raw_symbols = by_type.get("Subtype_Symbol", [])
    for s in raw_symbols:
        for ref in s.all("Subtype_Relationships_Ref") + s.all("Subtype_Relationship_Ref"):
            subtype_rel_ids[ref] = s.id

    # Relationships
    relationships: List[ErwinRelationship] = []
    for r in by_type.get("Relationship", []):
        parent_id = r.first("Parent_Entity_Ref")
        child_id = r.first("Child_Entity_Ref")
        if parent_id not in entity_ids or child_id not in entity_ids:
            warnings.append(f"Relationship '{_name(r)}' references an unknown entity; skipped.")
            continue
        child = entity_by_id[child_id]
        migrated = [a for a in child.attributes if a.parent_relationship_id == r.id]
        fk_pairs = [[a.id, a.parent_attribute_id] for a in migrated if a.parent_attribute_id]

        type_value = (r.first("Relationship_Type", "Type") or "").strip()
        kind = _REL_KIND_BY_NAME.get(type_value.lower()) or _REL_KIND_BY_CODE.get(type_value)
        inferred = False
        if r.id in subtype_rel_ids:
            kind = RelationshipKind.SUBTYPE
        elif kind is None:
            inferred = True
            if migrated and all(a.id in pk_attr_ids[child_id] for a in migrated):
                kind = RelationshipKind.IDENTIFYING
            else:
                kind = RelationshipKind.NON_IDENTIFYING

        optional = None
        nulls = r.first("Relationship_No_Nulls", "Null_Option_Type")
        if nulls is not None:
            v = nulls.strip().lower()
            if v in ("0", "nulls allowed", "null"):
                optional = True
            elif v in ("1", "no nulls", "not null"):
                optional = False
        if optional is None and kind == RelationshipKind.NON_IDENTIFYING and migrated:
            known = [a.nullable for a in migrated if a.nullable is not None]
            if known:
                optional = any(known)

        relationships.append(ErwinRelationship(
            id=r.id,
            name=_name(r) if (r.first("Name") or r.name) else None,
            kind=kind,
            parent_id=parent_id,
            child_id=child_id,
            parent_to_child_phrase=r.first("Parent_To_Child_Verb_Phrase", "Verb_Phrase"),
            child_to_parent_phrase=r.first("Child_To_Parent_Verb_Phrase", "Inverse_Verb_Phrase"),
            cardinality=_cardinality(r.first("Cardinality")),
            optional=optional,
            fk_pairs=fk_pairs,
            definition=r.first("Definition", "Comment"),
            kind_inferred=inferred,
        ))
    inferred_count = sum(1 for r in relationships if r.kind_inferred)
    if inferred_count:
        warnings.append(
            f"{inferred_count} relationship(s) had no recognised type; identifying vs. "
            "non-identifying was inferred from the child's primary key."
        )

    # Subtype groups
    rel_by_id = {r.id: r for r in relationships}
    subtype_groups: List[ErwinSubtypeGroup] = []
    for s in raw_symbols:
        rels = [rel_by_id[i] for i, sid in subtype_rel_ids.items() if sid == s.id and i in rel_by_id]
        parent_id = s.parent_id if s.parent_id in entity_ids else (rels[0].parent_id if rels else None)
        if not parent_id:
            warnings.append(f"Subtype symbol '{_name(s)}' has no supertype; skipped.")
            continue
        type_value = (s.first("Subtype_Type", "Type") or "").strip().lower()
        complete = None
        if type_value in ("complete", "1"):
            complete = True
        elif type_value in ("incomplete", "0"):
            complete = False
        subtype_groups.append(ErwinSubtypeGroup(
            id=s.id,
            parent_id=parent_id,
            child_ids=[r.child_id for r in rels],
            complete=complete,
            exclusive=_bool(s.first("Is_Exclusive", "Exclusive")),
        ))

    # Subject areas
    subject_areas: List[ErwinSubjectArea] = []
    for sa in by_type.get("Subject_Area", []):
        refs = sa.all("Referenced_Entities_Ref") + sa.all("Referenced_Entities")
        known = [ref for ref in refs if ref in entity_ids]
        if len(known) < len(refs):
            warnings.append(
                f"Subject area '{_name(sa)}' references {len(refs) - len(known)} unknown entities; ignored."
            )
        subject_areas.append(ErwinSubjectArea(
            id=sa.id, name=_name(sa), definition=sa.first("Definition", "Comment"),
            entity_ids=list(dict.fromkeys(known)),
        ))

    # Dangling references on attributes are dropped with a warning
    known_attr_ids = {a.id for e in entities for a in e.attributes}
    domain_ids = {d.id for d in domains}
    dangling = 0
    for e in entities:
        for a in e.attributes:
            if a.parent_attribute_id and a.parent_attribute_id not in known_attr_ids:
                a.parent_attribute_id = None
                dangling += 1
            if a.domain_id and a.domain_id not in domain_ids:
                a.domain_id = None
                dangling += 1
    if dangling:
        warnings.append(f"{dangling} dangling attribute reference(s) were ignored.")

    if not entities:
        warnings.append("The model contains no entities or tables.")
    all_attrs = [a for e in entities if not e.is_view for a in e.attributes]
    if all_attrs and all(a.nullable is None for a in all_attrs):
        warnings.append(
            "No attribute states its null option (an \"XML Standard with Min Info\" export?). "
            "Columns are imported as nullable unless they are part of a primary key."
        )

    udp_names = sorted({k for e in entities for k in list(e.udps) + [n for a in e.attributes for n in a.udps]})

    return ErwinModel(
        id=model_raw.id,
        name=_name(model_raw),
        model_type=_model_type(model_raw, has_logical, has_physical),
        source_format=source_format,
        target_dbms=model_raw.first("Target_Server", "Target_Database", "DBMS"),
        target_dbms_version=model_raw.first("Target_Server_Version", "DBMS_Version"),
        version=model_raw.first("Version", "Mart_Version"),
        entities=entities,
        relationships=relationships,
        subtype_groups=subtype_groups,
        subject_areas=subject_areas,
        domains=domains,
        udp_names=udp_names,
        warnings=warnings,
    )


def entities_in(model: ErwinModel, subject_area_ids: Optional[Iterable[str]]) -> List[ErwinEntity]:
    """The entities of the chosen subject areas (all entities when none are chosen)."""
    if not subject_area_ids:
        return list(model.entities)
    wanted = set(subject_area_ids)
    ids = {eid for sa in model.subject_areas if sa.id in wanted for eid in sa.entity_ids}
    return [e for e in model.entities if e.id in ids]
