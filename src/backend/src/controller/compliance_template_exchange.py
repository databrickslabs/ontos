"""Compliance template values in ODCS and ODPS documents.

Export: the stored values of the active template of an entity go to one
``customProperties`` entry, ``ontosComplianceValues``, whose value maps each
field's reference id to its value. ODPS carries it on the data product; ODCS on
the schema object that is a table or view asset (its ``implementsContract`` link,
else its ``physicalName`` equal to the asset location). The entries are only
exported to a user who may read the values (the read rules of the values routes).

Import: the entry is written to the fields of the active template whose
reference id it names, when the importer may write them (values feature at
read/write; for tables and views also asset edit). Nulls are skipped. The rest
(no active template, no matching table, no asset edit right, an unknown
reference id, a value that doesn't fit the field) is kept apart in
``ontosComplianceValuesUnmatched`` when the importer has the values feature at
read/write, and dropped otherwise. That entry is exported as it is and never
written as values on a later import. (On this stack's base the contract import
doesn't store schema-level custom properties at all, so there a schema object's
unmatched entry is only kept on development.)
"""
import json
import uuid
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Callable, Dict, List, Optional, Tuple

from fastapi import HTTPException, Request, status
from sqlalchemy.orm import Session

from src.common.compliance_value_types import ValueTypeError, coerce_value
from src.common.features import FeatureAccessLevel
from src.common.logging import get_logger
from src.controller.compliance_template_assets import (
    ASSET_ENTITY_TYPE,
    TEMPLATE_ASSET_TYPES,
    is_template_asset_type,
    location_key,
    location_key_sql,
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
UNMATCHED_VALUES_PROPERTY = "ontosComplianceValuesUnmatched"
_ENTRY_PROPERTIES = (COMPLIANCE_VALUES_PROPERTY, UNMATCHED_VALUES_PROPERTY)
DATA_PRODUCT_ENTITY_TYPE = "data_product"
VALUES_FEATURE_ID = "compliance-template-values"
ASSETS_FEATURE_ID = "assets"
# An entry larger than this is ignored on import (not written, not kept).
MAX_ENTRY_KEYS = 200
MAX_ENTRY_BYTES = 64 * 1024


@dataclass(frozen=True)
class ValuesReadAccess:
    """Whether the exporting user may read template values (the values routes' rules)."""
    values: bool = False
    assets_rw: bool = False
    # For tables and views without asset edit: is the asset linked to a data
    # product the user can access (as ``GET /api/assets/{id}``)?
    asset_accessible: Optional[Callable[[AssetDb], bool]] = None

    def may_read_product(self) -> bool:
        return self.values

    def may_read_asset(self, asset: AssetDb) -> bool:
        if not self.values:
            return False
        if self.assets_rw:
            return True
        return self.asset_accessible is not None and bool(self.asset_accessible(asset))


@dataclass
class ComplianceImport:
    """What an import may do with template values, and what it wrote (for the audit)."""
    user_email: Optional[str]
    can_write_values: bool = False
    can_write_assets: bool = False
    written: List[Dict[str, Any]] = field(default_factory=list)

    def record(self, entity_type: str, entity_id: str, reference_ids: List[str]) -> None:
        if reference_ids:
            self.written.append({
                "entityType": entity_type, "entityId": str(entity_id),
                "referenceIds": list(reference_ids),
            })


def has_active_template(db: Session, entity_type: str) -> bool:
    return compliance_templates_repo.get_active_template(db, entity_type=entity_type) is not None


def entity_values(db: Session, *, entity_type: str, entity_id: str) -> Optional[Dict[str, Any]]:
    """Reference id -> stored value for the active template, in field order.

    ``None`` when no template is active for the entity type.
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


# ----- customProperties helpers --------------------------------------------

def _is_prop(prop: Any, name: str) -> bool:
    return isinstance(prop, dict) and prop.get("property") == name


def read_entry(
    custom_props: Any, name: str = COMPLIANCE_VALUES_PROPERTY
) -> Optional[Dict[str, Any]]:
    """The entry's reference id -> value mapping, or ``None`` (absent, not a mapping
    or over the size cap). A JSON text is read too: data products store custom
    property values as text."""
    if isinstance(custom_props, dict):
        value = custom_props.get(name)
    elif isinstance(custom_props, list):
        value = next((p.get("value") for p in custom_props if _is_prop(p, name)), None)
    else:
        value = None
    if isinstance(value, str):
        if len(value) > MAX_ENTRY_BYTES:
            logger.warning("Compliance values entry %s over the size cap; ignored", name)
            return None
        try:
            value = json.loads(value)
        except ValueError:
            return None
    if not isinstance(value, dict):
        return None
    if len(value) > MAX_ENTRY_KEYS or len(json.dumps(value, default=str)) > MAX_ENTRY_BYTES:
        logger.warning("Compliance values entry %s over the size cap; ignored", name)
        return None
    return value


def without_entries(custom_props: Any) -> Any:
    """``custom_props`` without the values and unmatched-values entries."""
    if isinstance(custom_props, dict):
        return {k: v for k, v in custom_props.items() if k not in _ENTRY_PROPERTIES}
    if isinstance(custom_props, list):
        return [
            p for p in custom_props if not any(_is_prop(p, n) for n in _ENTRY_PROPERTIES)
        ]
    return custom_props


def _with_prop(custom_props: Any, name: str, values: Dict[str, Any]) -> Any:
    if isinstance(custom_props, dict):
        return {**custom_props, name: values}
    return [*(custom_props or []), {"property": name, "value": values}]


def apply_to_document(
    doc: Dict[str, Any], live: Optional[Dict[str, Any]], *, readable: bool
) -> None:
    """Export: put the live values in ``doc["customProperties"]``.

    A stored ``ontosComplianceValues`` entry is always replaced by the live values
    (or removed when there are none); the unmatched entry is kept. When the user
    may not read the values, neither entry is exported.
    """
    current = doc.get("customProperties")
    unmatched = read_entry(current, UNMATCHED_VALUES_PROPERTY) if readable else None
    props = without_entries(current)
    if unmatched:
        props = _with_prop(props, UNMATCHED_VALUES_PROPERTY, unmatched)
    if readable and live:
        props = _with_prop(props, COMPLIANCE_VALUES_PROPERTY, dict(live))
    if props:
        doc["customProperties"] = props
    else:
        doc.pop("customProperties", None)


def find_schema_asset(
    db: Session,
    *,
    physical_name: Optional[str],
    contract_id: Optional[str] = None,
    schema_object_id: Optional[str] = None,
) -> Optional[AssetDb]:
    """The table or view asset an ODCS schema object describes, if exactly one matches.

    The ``implementsContract`` link made by schema auto-linking, else the physical
    name equal to the asset location (``location_key``: no backticks, any case),
    which is what "Infer from Asset" writes. No match on the asset name: a bare
    table name could be another catalog's table.
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
    key = location_key(physical_name)
    if not key:
        return None
    matches = (
        db.query(AssetDb)
        .join(AssetTypeDb, AssetDb.asset_type_id == AssetTypeDb.id)
        .filter(
            AssetTypeDb.name.in_(sorted(TEMPLATE_ASSET_TYPES)),
            location_key_sql(AssetDb.location) == key,
        )
        .limit(2)
        .all()
    )
    if len(matches) == 1:
        return matches[0]
    if matches:
        logger.info("Schema object %s matches several assets; values not mapped", key)
    return None


# ----- Export ---------------------------------------------------------------

def apply_schema_export(
    db: Session,
    schema_dict: Dict[str, Any],
    *,
    physical_name: Optional[str],
    contract_id: str,
    schema_object_id: str,
    access: Optional[ValuesReadAccess],
) -> None:
    """Export: the values of the table or view a schema object describes."""
    if access is None or not access.values:
        apply_to_document(schema_dict, None, readable=False)
        return
    asset = None
    if has_active_template(db, ASSET_ENTITY_TYPE):
        asset = find_schema_asset(
            db, physical_name=physical_name, contract_id=contract_id,
            schema_object_id=schema_object_id,
        )
    if asset is None:
        # No table to read the values of: only the unmatched entry stays.
        apply_to_document(schema_dict, None, readable=True)
        return
    if not access.may_read_asset(asset):
        apply_to_document(schema_dict, None, readable=False)
        return
    live = entity_values(db, entity_type=ASSET_ENTITY_TYPE, entity_id=str(asset.id))
    apply_to_document(schema_dict, live, readable=True)


def apply_product_export(
    db: Session, odps: Dict[str, Any], *, product_id: str, access: Optional[ValuesReadAccess]
) -> None:
    """Export: the values of a data product."""
    readable = access is not None and access.may_read_product()
    live = (
        entity_values(db, entity_type=DATA_PRODUCT_ENTITY_TYPE, entity_id=product_id)
        if readable else None
    )
    apply_to_document(odps, live, readable=readable)


# ----- Import ---------------------------------------------------------------

def apply_imported_values(
    db: Session,
    *,
    entity_type: str,
    entity_id: str,
    values: Dict[str, Any],
    user_email: Optional[str],
) -> Tuple[List[str], Dict[str, Any]]:
    """Write imported values for the active template's fields.

    Upsert per field (other fields keep their values). Nulls are skipped (an
    import never clears a value). Returns the reference ids written and the
    values not written (unknown reference ids, values that don't fit the field).
    Flushes; the caller commits.
    """
    present = {k: v for k, v in values.items() if v is not None}
    active = compliance_templates_repo.get_active_template(db, entity_type=entity_type)
    if active is None:
        return [], present
    fields = compliance_templates_repo.list_fields(db, template_id=active.id)
    by_ref = {f.reference_id: f for f in fields}
    existing = {
        r.field_id: r
        for r in compliance_templates_repo.list_values(
            db, entity_type=entity_type, entity_id=str(entity_id),
            field_ids=[f.id for f in fields],
        )
    }
    written: List[str] = []
    rest: Dict[str, Any] = {}
    for reference_id, raw in present.items():
        template_field = by_ref.get(reference_id)
        if template_field is None:
            rest[reference_id] = raw
            continue
        try:
            value = coerce_value(template_field.value_type, raw, template_field.possible_values)
        except ValueTypeError:
            rest[reference_id] = raw
            continue
        row = existing.get(template_field.id)
        if row is None:
            db.add(ComplianceTemplateValueDb(
                field_id=template_field.id, entity_type=entity_type, entity_id=str(entity_id),
                value=value, filled_by=user_email,
            ))
        else:
            row.value = value
            row.filled_by = user_email
        written.append(reference_id)
    if rest:
        logger.debug(
            "%d imported compliance value(s) for %s %s not written (unknown field or invalid)",
            len(rest), entity_type, entity_id,
        )
    db.flush()
    return written, rest


def _write_in_savepoint(
    db: Session, imp: ComplianceImport, *, entity_type: str, entity_id: str,
    values: Dict[str, Any],
) -> Dict[str, Any]:
    """Write ``values`` in a savepoint; returns what wasn't written (all of it on failure)."""
    try:
        with db.begin_nested():
            written, rest = apply_imported_values(
                db, entity_type=entity_type, entity_id=entity_id, values=values,
                user_email=imp.user_email,
            )
    except Exception:
        logger.warning(
            "Imported compliance values of %s %s not stored", entity_type, entity_id,
            exc_info=True,
        )
        return dict(values)
    imp.record(entity_type, entity_id, written)
    return rest


def _leftovers(
    imp: ComplianceImport, carried: Optional[Dict[str, Any]], rest: Dict[str, Any]
) -> Dict[str, Any]:
    """The unmatched values to keep: none unless the importer may write values."""
    leftovers = {**(carried or {}), **rest}
    if leftovers and not imp.can_write_values:
        logger.debug("%d unmatched imported compliance value(s) dropped", len(leftovers))
        return {}
    return leftovers


def import_schema_entries(db: Session, schema_data: list, imp: ComplianceImport) -> None:
    """Import: write each schema object's entry to its table or view asset.

    Runs in the import's transaction, before the schema objects are stored; each
    asset's write is in a savepoint. Both entries leave the schema object; what
    wasn't written is put back as ``ontosComplianceValuesUnmatched`` (see the
    module docstring). Only the asset location matches here (the contract is new,
    so there's no auto-link yet).
    """
    active = has_active_template(db, ASSET_ENTITY_TYPE)
    for schema in schema_data:
        if not isinstance(schema, dict):
            continue
        key = "customProperties" if "customProperties" in schema else "custom_properties"
        props = schema.get(key)
        if props is None:
            continue
        values = read_entry(props)
        carried = read_entry(props, UNMATCHED_VALUES_PROPERTY)
        rest = {k: v for k, v in (values or {}).items() if v is not None}
        if rest and active and imp.can_write_assets:
            asset = find_schema_asset(
                db, physical_name=schema.get("physicalName") or schema.get("physical_name"),
            )
            if asset is not None:
                rest = _write_in_savepoint(
                    db, imp, entity_type=ASSET_ENTITY_TYPE, entity_id=str(asset.id),
                    values=rest,
                )
        stored = without_entries(props)
        leftovers = _leftovers(imp, carried, rest)
        if leftovers:
            stored = _with_prop(stored, UNMATCHED_VALUES_PROPERTY, leftovers)
        schema[key] = stored


def take_product_entries(
    product_data: Dict[str, Any],
) -> Tuple[Optional[Dict[str, Any]], Optional[Dict[str, Any]]]:
    """Import: detach a product's values and unmatched-values entries before it's stored."""
    props = product_data.get("customProperties")
    values = read_entry(props)
    carried = read_entry(props, UNMATCHED_VALUES_PROPERTY)
    if props is not None:
        product_data["customProperties"] = without_entries(props)
    return values, carried


def import_product_values(
    db: Session,
    *,
    product_id: str,
    values: Optional[Dict[str, Any]],
    carried: Optional[Dict[str, Any]],
    imp: ComplianceImport,
) -> None:
    """Import: write a stored product's values; keep what wasn't written (see the module)."""
    rest = {k: v for k, v in (values or {}).items() if v is not None}
    if rest and imp.can_write_values and has_active_template(db, DATA_PRODUCT_ENTITY_TYPE):
        rest = _write_in_savepoint(
            db, imp, entity_type=DATA_PRODUCT_ENTITY_TYPE, entity_id=str(product_id),
            values=rest,
        )
    leftovers = _leftovers(imp, carried, rest)
    if leftovers:
        db.add(CustomPropertyDb(
            product_id=str(product_id), property=UNMATCHED_VALUES_PROPERTY,
            value=json.dumps(leftovers, default=str),
        ))
    db.flush()


# ----- Permissions ----------------------------------------------------------

async def _has(
    request: Request, user: UserInfo, auth_manager: "AuthorizationManager",
    feature_id: str, level: FeatureAccessLevel,
) -> bool:
    # Imported here: src.common.authorization imports the managers that import this module.
    from src.common.authorization import PermissionChecker

    try:
        await PermissionChecker(feature_id, level)(request, user, auth_manager)
    except HTTPException as e:
        if e.status_code == status.HTTP_403_FORBIDDEN:
            return False
        raise
    return True


async def import_access(
    request: Request, user: UserInfo, auth_manager: "AuthorizationManager"
) -> ComplianceImport:
    """The importer's rights: the values feature at READ_WRITE (product values, and
    keeping unmatched values), plus ``assets`` at READ_WRITE for table and view values."""
    values_rw = await _has(
        request, user, auth_manager, VALUES_FEATURE_ID, FeatureAccessLevel.READ_WRITE
    )
    assets_rw = values_rw and await _has(
        request, user, auth_manager, ASSETS_FEATURE_ID, FeatureAccessLevel.READ_WRITE
    )
    return ComplianceImport(
        user_email=user.email or user.username,
        can_write_values=values_rw, can_write_assets=assets_rw,
    )


async def read_access(
    request: Request, user: UserInfo, auth_manager: "AuthorizationManager", db: Session
) -> ValuesReadAccess:
    """The exporter's rights, as the values routes: the values feature at READ_ONLY;
    for tables and views also ``assets`` at READ_WRITE or a link to a data product
    the user can access."""
    if not await _has(
        request, user, auth_manager, VALUES_FEATURE_ID, FeatureAccessLevel.READ_ONLY
    ):
        return ValuesReadAccess()
    assets_rw = await _has(
        request, user, auth_manager, ASSETS_FEATURE_ID, FeatureAccessLevel.READ_WRITE
    )
    dpm = getattr(request.app.state, "data_products_manager", None)

    def _accessible(asset: AssetDb) -> bool:
        from src.controller.assets_manager import assets_manager

        return dpm is not None and assets_manager.is_asset_accessible(
            db, asset_id=asset.id, data_products_manager=dpm, is_admin=False
        )

    return ValuesReadAccess(values=True, assets_rw=assets_rw, asset_accessible=_accessible)


def _asset_type(asset: AssetDb) -> Optional[str]:
    return asset.asset_type.name if asset.asset_type else None


def _uuid_or_none(value: Any) -> Optional[uuid.UUID]:
    try:
        return uuid.UUID(str(value))
    except ValueError:
        return None
