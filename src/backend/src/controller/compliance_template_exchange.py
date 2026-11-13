"""Compliance template values in ODCS and ODPS documents.

Export: the stored values of the active template of an entity go to one
``customProperties`` entry, ``ontosComplianceValues``, whose value maps each
field's reference id to its value. ODPS carries it on the data product; ODCS on
the schema object whose ``physicalName`` (else ``name``) is a table or view asset.

Import: the entry is read back into the values of the fields of the active
template whose reference id it names (values that don't fit the field type are
skipped). When it can't be applied (no active template, no matching asset, or
the importing user may not write the values) the entry stays an ordinary
custom property, so nothing is lost.
"""
import json
import uuid
from typing import TYPE_CHECKING, Any, Dict, Optional, Tuple

from fastapi import HTTPException, Request, status
from sqlalchemy import func
from sqlalchemy.orm import Session

from src.common.compliance_value_types import ValueTypeError, coerce_value
from src.common.features import FeatureAccessLevel
from src.common.logging import get_logger
from src.controller.compliance_template_assets import (
    ASSET_ENTITY_TYPE,
    TEMPLATE_ASSET_TYPES,
    is_template_asset_type,
)
from src.db_models.assets import AssetDb, AssetTypeDb
from src.db_models.compliance_templates import ComplianceTemplateValueDb
from src.db_models.data_products import CustomPropertyDb
from src.db_models.entity_relationships import EntityRelationshipDb
from src.models.users import UserInfo
from src.repositories.compliance_templates_repository import compliance_templates_repo

if TYPE_CHECKING:
    from src.controller.authorization_manager import AuthorizationManager

logger = get_logger(__name__)

COMPLIANCE_VALUES_PROPERTY = "ontosComplianceValues"
DATA_PRODUCT_ENTITY_TYPE = "data_product"
VALUES_FEATURE_ID = "compliance-template-values"
ASSETS_FEATURE_ID = "assets"


def has_active_template(db: Session, entity_type: str) -> bool:
    return compliance_templates_repo.get_active_template(db, entity_type=entity_type) is not None


def entity_values(db: Session, *, entity_type: str, entity_id: str) -> Optional[Dict[str, Any]]:
    """Reference id -> stored value for the active template, in field order.

    ``None`` when no template is active for the entity type (the document's own
    custom properties are then left as they are).
    """
    active = compliance_templates_repo.get_active_template(db, entity_type=entity_type)
    if active is None:
        return None
    fields = compliance_templates_repo.list_fields(db, template_id=active.id)
    rows = compliance_templates_repo.list_values(
        db, entity_type=entity_type, entity_id=str(entity_id), field_ids=[f.id for f in fields]
    )
    stored = {r.field_id: r.value for r in rows if r.value is not None}
    return {f.reference_id: stored[f.id] for f in fields if f.id in stored}


def _is_entry(prop: Any) -> bool:
    return isinstance(prop, dict) and prop.get("property") == COMPLIANCE_VALUES_PROPERTY


def apply_to_document(doc: Dict[str, Any], values: Optional[Dict[str, Any]]) -> None:
    """Put the live values in ``doc["customProperties"]`` (replacing any stored entry).

    ``values`` is ``None`` when no template is active: the document is untouched.
    An empty mapping removes a stale entry.
    """
    if values is None:
        return
    current = doc.get("customProperties")
    if isinstance(current, dict):
        if values:
            current[COMPLIANCE_VALUES_PROPERTY] = dict(values)
        else:
            current.pop(COMPLIANCE_VALUES_PROPERTY, None)
        return
    props = [p for p in (current or []) if not _is_entry(p)]
    if values:
        props.append({"property": COMPLIANCE_VALUES_PROPERTY, "value": dict(values)})
    if props:
        doc["customProperties"] = props
    else:
        doc.pop("customProperties", None)


def read_entry(custom_props: Any) -> Optional[Dict[str, Any]]:
    """The entry's reference id -> value mapping, or ``None`` (absent or not a mapping).

    A JSON text is read too: data products store custom property values as text.
    """
    if isinstance(custom_props, dict):
        value = custom_props.get(COMPLIANCE_VALUES_PROPERTY)
    elif isinstance(custom_props, list):
        value = next((p.get("value") for p in custom_props if _is_entry(p)), None)
    else:
        value = None
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except ValueError:
            return None
    return value if isinstance(value, dict) else None


def _with_entry(custom_props: Any, values: Dict[str, Any]) -> Any:
    """``custom_props`` with the entry set to ``values`` (removed when empty)."""
    props = without_entry(custom_props)
    if not values:
        return props
    if isinstance(props, dict):
        return {**props, COMPLIANCE_VALUES_PROPERTY: values}
    return [*(props or []), {"property": COMPLIANCE_VALUES_PROPERTY, "value": values}]


def without_entry(custom_props: Any) -> Any:
    """``custom_props`` without the ``ontosComplianceValues`` entry."""
    if isinstance(custom_props, dict):
        return {k: v for k, v in custom_props.items() if k != COMPLIANCE_VALUES_PROPERTY}
    if isinstance(custom_props, list):
        return [p for p in custom_props if not _is_entry(p)]
    return custom_props


def apply_imported_values(
    db: Session,
    *,
    entity_type: str,
    entity_id: str,
    values: Dict[str, Any],
    user_email: Optional[str],
) -> list[str]:
    """Write imported values for the active template's fields; returns the reference ids written.

    Upsert per field (other fields keep their values); unknown reference ids and
    values that don't fit the field are skipped. Flushes; the caller commits.
    """
    active = compliance_templates_repo.get_active_template(db, entity_type=entity_type)
    if active is None:
        return []
    fields = compliance_templates_repo.list_fields(db, template_id=active.id)
    by_ref = {f.reference_id: f for f in fields}
    existing = {
        r.field_id: r
        for r in compliance_templates_repo.list_values(
            db, entity_type=entity_type, entity_id=str(entity_id),
            field_ids=[f.id for f in fields],
        )
    }
    written: list[str] = []
    for reference_id, raw in values.items():
        field = by_ref.get(reference_id)
        if field is None:
            logger.info(
                "Imported compliance value %s skipped: no such field in the active template",
                reference_id,
            )
            continue
        try:
            value = coerce_value(field.value_type, raw, field.possible_values)
        except ValueTypeError:
            logger.warning(
                "Imported compliance value %s skipped for %s %s: not a valid %s",
                reference_id, entity_type, entity_id, field.value_type,
            )
            continue
        row = existing.get(field.id)
        if row is None:
            db.add(ComplianceTemplateValueDb(
                field_id=field.id, entity_type=entity_type, entity_id=str(entity_id),
                value=value, filled_by=user_email,
            ))
        else:
            row.value = value
            row.filled_by = user_email
        written.append(reference_id)
    db.flush()
    return written


def find_schema_asset(
    db: Session,
    *,
    physical_name: Optional[str],
    contract_id: Optional[str] = None,
    schema_object_id: Optional[str] = None,
) -> Optional[AssetDb]:
    """The table or view asset an ODCS schema object describes, if exactly one matches.

    First the ``implementsContract`` link made by schema auto-linking, then an
    exact (case-insensitive) match of the physical name on the asset location
    (what "Infer from Asset" writes), then on the asset name.
    """
    if contract_id and schema_object_id:
        links = (
            db.query(EntityRelationshipDb)
            .filter(
                EntityRelationshipDb.target_type == "DataContract",
                EntityRelationshipDb.target_id == str(contract_id),
                EntityRelationshipDb.relationship_type == "implementsContract",
                EntityRelationshipDb.source_type.in_(sorted(TEMPLATE_ASSET_TYPES)),
            )
            .all()
        )
        for link in links:
            props = link.properties or {}
            asset_id = _uuid_or_none(link.source_id)
            if asset_id is None or str(props.get("schema_object_id")) != str(schema_object_id):
                continue
            asset = db.get(AssetDb, asset_id)
            if asset is not None and is_template_asset_type(_asset_type(asset)):
                return asset
    name = (physical_name or "").strip()
    if not name:
        return None
    candidates = (
        db.query(AssetDb)
        .join(AssetTypeDb, AssetDb.asset_type_id == AssetTypeDb.id)
        .filter(AssetTypeDb.name.in_(sorted(TEMPLATE_ASSET_TYPES)))
    )
    for column in (AssetDb.location, AssetDb.name):
        matches = candidates.filter(func.lower(column) == name.lower()).limit(2).all()
        if len(matches) == 1:
            return matches[0]
        if matches:
            logger.info("Schema object %s matches several assets; values not mapped", name)
            return None
    return None


def schema_values(
    db: Session, *, physical_name: Optional[str], contract_id: str, schema_object_id: str
) -> Optional[Dict[str, Any]]:
    """Values of the asset a schema object describes (``None``: leave the document as is)."""
    if not has_active_template(db, ASSET_ENTITY_TYPE):
        return None
    asset = find_schema_asset(
        db, physical_name=physical_name, contract_id=contract_id,
        schema_object_id=schema_object_id,
    )
    if asset is None:
        return None
    return entity_values(db, entity_type=ASSET_ENTITY_TYPE, entity_id=str(asset.id))


def import_schema_values(
    db: Session, schema_data: list, *, user_email: Optional[str]
) -> list[Tuple[AssetDb, list[str]]]:
    """Write the entries of schema objects that map to a table or view asset.

    Runs in the import's transaction, before the schema objects are stored. The
    values written leave the schema object's entry; the rest (unknown reference
    ids, values that don't fit) stay in it, as does the whole entry of an object
    that maps to no asset. Returns ``(asset, reference ids written)``.
    """
    if not has_active_template(db, ASSET_ENTITY_TYPE):
        return []
    imported: list[Tuple[AssetDb, list[str]]] = []
    for schema in schema_data:
        if not isinstance(schema, dict):
            continue
        key = "customProperties" if "customProperties" in schema else "custom_properties"
        values = read_entry(schema.get(key))
        if values is None:
            continue
        asset = find_schema_asset(
            db, physical_name=schema.get("physicalName") or schema.get("physical_name")
            or schema.get("name"),
        )
        if asset is None:
            continue
        written = apply_imported_values(
            db, entity_type=ASSET_ENTITY_TYPE, entity_id=str(asset.id), values=values,
            user_email=user_email,
        )
        schema[key] = _with_entry(schema.get(key), unwritten(values, written))
        imported.append((asset, written))
    return imported


def unwritten(values: Dict[str, Any], written: list[str]) -> Dict[str, Any]:
    return {ref: value for ref, value in values.items() if ref not in written}


def keep_unwritten_product_values(
    db: Session, *, product_id: str, values: Dict[str, Any], written: list[str]
) -> None:
    """Leave only the values not written in the product's stored entry (none: drop it)."""
    rest = unwritten(values, written)
    rows = db.query(CustomPropertyDb).filter(
        CustomPropertyDb.product_id == str(product_id),
        CustomPropertyDb.property == COMPLIANCE_VALUES_PROPERTY,
    ).all()
    for row in rows:
        if rest:
            row.value = json.dumps(rest)
        else:
            db.delete(row)
    db.flush()


async def can_import_values(
    request: Request,
    user: UserInfo,
    auth_manager: "AuthorizationManager",
    *,
    entity_type: str,
) -> bool:
    """Whether an import may write template values of ``entity_type``.

    The same rights as the values routes: the values feature at READ_WRITE, and
    for tables and views also the right to edit assets.
    """
    # Imported here: src.common.authorization imports the managers that import this module.
    from src.common.authorization import PermissionChecker

    needed = [VALUES_FEATURE_ID]
    if entity_type == ASSET_ENTITY_TYPE:
        needed.append(ASSETS_FEATURE_ID)
    for feature_id in needed:
        try:
            await PermissionChecker(feature_id, FeatureAccessLevel.READ_WRITE)(
                request, user, auth_manager
            )
        except HTTPException as e:
            if e.status_code == status.HTTP_403_FORBIDDEN:
                return False
            raise
    return True


def _asset_type(asset: AssetDb) -> Optional[str]:
    return asset.asset_type.name if asset.asset_type else None


def _uuid_or_none(value: Any) -> Optional[uuid.UUID]:
    try:
        return uuid.UUID(str(value))
    except ValueError:
        return None
