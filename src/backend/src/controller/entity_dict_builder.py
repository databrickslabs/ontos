"""Build enriched entity dictionaries for compliance DSL evaluation.

Produces a flat dict with raw entity fields + computed relationship/governance
counts so that maturity gate rules can use simple assertions like
``obj.business_term_count > 0`` or ``obj.certification_level >= 2``.
"""
import re
import uuid
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Optional

from sqlalchemy.orm import Session
from sqlalchemy import func, and_, or_

from src.common.api_errors import CodedValueError
from src.common.logging import get_logger
from src.common.uc_table_columns import table_column_fields

logger = get_logger(__name__)

# Asset types that maturity levels with entity type ``Asset`` apply to.
MATURITY_ASSET_TYPES = ("Table", "View")

# Fields that come from the Unity Catalog table an asset points to. Absent from
# the dict when the asset isn't UC-backed or its table can't be read.
UC_TABLE_FIELDS = frozenset(table_column_fields(None))

# ``uc_table_status`` values (``None`` = the asset doesn't point to a UC table).
UC_TABLE_READ = "read"
UC_TABLE_CLIENT_UNAVAILABLE = "client_unavailable"
UC_TABLE_NOT_FOUND = "not_found"
UC_TABLE_PERMISSION_DENIED = "permission_denied"
UC_TABLE_READ_FAILED = "read_failed"

_UC_PLATFORMS = {"databricks", "unity catalog", "unity_catalog"}
_UC_NAME_PART = re.compile(r"^[^./:\s][^./:]*$")


class UnsupportedMaturityAssetTypeError(CodedValueError):
    """Maturity is evaluated only for table and view assets."""

    code = "maturity_asset_type_unsupported"


def build_data_product_dict(db: Session, product_id: str) -> Optional[Dict[str, Any]]:
    """Build an enriched dict for a DataProduct."""
    from src.db_models.data_products import DataProductDb
    product = db.get(DataProductDb, product_id)
    if not product:
        return None

    base = _extract_base_fields(product)
    base["entity_type"] = "DataProduct"

    # Description fields
    desc = product.description
    base["has_description"] = bool(desc and (desc.purpose or desc.usage))
    base["has_purpose"] = bool(desc and desc.purpose)
    base["has_usage"] = bool(desc and desc.usage)

    # Owner
    base["owner_team_id"] = product.owner_team_id
    base["has_owner"] = bool(product.owner_team_id)

    # Output ports / contracts
    output_ports = product.output_ports or []
    base["output_port_count"] = len(output_ports)
    contract_count = sum(
        len(getattr(op, "input_contracts", None) or [])
        for op in output_ports
    )
    base["contract_count"] = contract_count
    base["has_contract"] = contract_count > 0
    # Output ports linked to a data contract (OutputPortDb.contract_id)
    base["output_port_contract_count"] = sum(1 for op in output_ports if op.contract_id)

    # Certification
    base["certification_level"] = product.certification_level or 0
    base["inherited_certification_level"] = product.inherited_certification_level or 0
    base["is_certified"] = bool(product.certification_level)
    base["effective_certification"] = max(
        product.certification_level or 0,
        product.inherited_certification_level or 0,
    )

    # Publication
    pub_scope = getattr(product, "publication_scope", "none") or "none"
    base["publication_scope"] = pub_scope
    base["is_published"] = pub_scope != "none"

    # Relationship counts
    _add_relationship_counts(db, base, "DataProduct", product_id)
    _add_tag_count(db, base, product_id, "DataProduct")
    _add_quality_check_count(db, base, "DataProduct", product_id)

    return base


def build_data_contract_dict(db: Session, contract_id: str) -> Optional[Dict[str, Any]]:
    """Build an enriched dict for a DataContract."""
    from src.db_models.data_contracts import DataContractDb
    contract = db.get(DataContractDb, contract_id)
    if not contract:
        return None

    base = _extract_base_fields(contract)
    base["entity_type"] = "DataContract"

    # Description
    base["has_description"] = bool(contract.description_purpose or contract.description_usage)
    base["has_purpose"] = bool(contract.description_purpose)

    # Owner
    base["owner_team_id"] = contract.owner_team_id
    base["has_owner"] = bool(contract.owner_team_id)

    # Certification
    base["certification_level"] = contract.certification_level or 0
    base["inherited_certification_level"] = contract.inherited_certification_level or 0
    base["is_certified"] = bool(contract.certification_level)
    base["effective_certification"] = max(
        contract.certification_level or 0,
        contract.inherited_certification_level or 0,
    )

    # Publication
    pub_scope = getattr(contract, "publication_scope", "none") or "none"
    base["publication_scope"] = pub_scope
    base["is_published"] = pub_scope != "none"

    # Schema objects count
    schema_objs = getattr(contract, "schema_objects", None) or []
    base["schema_object_count"] = len(schema_objs) if hasattr(schema_objs, '__len__') else 0

    # Relationship counts
    _add_relationship_counts(db, base, "DataContract", contract_id)
    _add_tag_count(db, base, contract_id, "DataContract")
    _add_quality_check_count(db, base, "DataContract", contract_id)

    return base


def build_asset_dict(
    db: Session,
    asset_id: str,
    *,
    get_workspace_client: Optional[Callable[[], Any]] = None,
) -> Optional[Dict[str, Any]]:
    """Build an enriched dict for a table or view asset.

    Ontos fields: owners (``business_owners``), domains, status, certification
    and its dates, custom properties (``properties`` plus one ``prop_<key>``
    per top-level key, because rules read one level: ``obj.prop_tier``),
    linked business terms (``hasTerm`` relationships) and concept links,
    tags and quality items.

    When the asset points to a Unity Catalog table (platform Databricks and a
    ``catalog.schema.table`` location) the table is read with one
    ``tables.get`` and ``table_column_fields`` is merged in. If it can't be
    read, those fields stay absent and ``uc_table_status`` says why (a code,
    never the exception text).

    Raises ``UnsupportedMaturityAssetTypeError`` for asset types other than
    tables and views.
    """
    from src.db_models.assets import AssetDb

    try:
        asset_uuid = uuid.UUID(str(asset_id))
    except ValueError:
        return None
    asset = db.get(AssetDb, asset_uuid)
    if not asset:
        return None

    asset_type = asset.asset_type.name if asset.asset_type else None
    if asset_type not in MATURITY_ASSET_TYPES:
        raise UnsupportedMaturityAssetTypeError(
            f"Maturity levels apply to table and view assets, not to {asset_type!r} assets.",
            assetType=asset_type,
        )

    entity_id = str(asset.id)
    base = _extract_base_fields(asset)
    base["id"] = entity_id
    base["asset_type_id"] = str(asset.asset_type_id) if asset.asset_type_id else None
    base["entity_type"] = "Asset"
    base["asset_type"] = asset_type
    base["has_description"] = bool(asset.description and asset.description.strip())

    _add_asset_owners(db, base, entity_id)
    _add_asset_domains(db, base, entity_id)
    _add_asset_certification(base, asset)
    _add_asset_properties(base, asset.properties)

    # Relationships are stored with the asset type name (``Table``/``View``)
    rels = _relationships_of(db, asset_type, entity_id)
    base["relationship_count"] = len(rels)
    base["business_term_count"] = _business_term_count(rels, entity_id)
    base["has_business_terms"] = base["business_term_count"] > 0
    _add_semantic_link_count(db, base, "asset", entity_id)

    quick_tags = asset.tags if isinstance(asset.tags, list) else []
    _add_tag_count(db, base, entity_id, "asset")
    base["tag_count"] += len(quick_tags)
    base["has_tags"] = base["tag_count"] > 0
    _add_quality_check_count(db, base, "asset", entity_id)

    _add_uc_table_fields(base, asset, get_workspace_client)
    return base


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def uc_table_name(platform: Optional[str], location: Optional[str]) -> Optional[str]:
    """The ``catalog.schema.table`` name an asset points to, or None."""
    if (platform or "").strip().lower() not in _UC_PLATFORMS or not location:
        return None
    parts = location.strip().split(".")
    if len(parts) != 3 or not all(_UC_NAME_PART.match(p) for p in parts):
        return None
    return ".".join(parts)


def _uc_read_status(error: Exception) -> str:
    from databricks.sdk.errors import NotFound, PermissionDenied, Unauthenticated

    if isinstance(error, NotFound):
        return UC_TABLE_NOT_FOUND
    if isinstance(error, (PermissionDenied, Unauthenticated)):
        return UC_TABLE_PERMISSION_DENIED
    return UC_TABLE_READ_FAILED


def _add_uc_table_fields(
    d: Dict[str, Any], asset, get_workspace_client: Optional[Callable[[], Any]],
) -> None:
    """Merge the UC table's column fields, or record why they are absent."""
    full_name = uc_table_name(asset.platform, asset.location)
    d["uc_table_name"] = full_name
    d["uc_table_status"] = None
    d["uc_fields_available"] = False
    if not full_name:
        return

    ws = None
    if get_workspace_client is not None:
        try:
            ws = get_workspace_client()
        except Exception:
            logger.warning("Workspace client unavailable for asset %s", d.get("id"),
                           exc_info=True)
    if ws is None:
        d["uc_table_status"] = UC_TABLE_CLIENT_UNAVAILABLE
        return

    try:
        table = ws.tables.get(full_name=full_name)
    except Exception as e:
        d["uc_table_status"] = _uc_read_status(e)
        logger.warning("Could not read UC table %s for asset %s: %s",
                       full_name, d.get("id"), type(e).__name__)
        return

    d.update(table_column_fields(table))
    d["uc_table_status"] = UC_TABLE_READ
    d["uc_fields_available"] = True


def _add_asset_owners(db: Session, d: Dict[str, Any], asset_id: str) -> None:
    from src.db_models.business_owners import BusinessOwnerDb

    rows = (
        db.query(BusinessOwnerDb.user_email)
        .filter(
            BusinessOwnerDb.object_type == "asset",
            BusinessOwnerDb.object_id == asset_id,
            BusinessOwnerDb.is_active.is_(True),
        )
        .order_by(BusinessOwnerDb.assigned_at)
        .all()
    )
    owners: List[str] = list(dict.fromkeys(r.user_email for r in rows if r.user_email))
    d["owners"] = owners
    d["owner"] = owners[0] if owners else None
    d["owner_count"] = len(owners)
    d["has_owner"] = bool(owners)


def _add_asset_domains(db: Session, d: Dict[str, Any], asset_id: str) -> None:
    from src.repositories.entity_domain_association_repository import entity_domain_repo

    assigned = entity_domain_repo.get_domains_for_entity(
        db, entity_type="asset", entity_id=asset_id
    )
    primary = next((a for a in assigned if a.is_primary), assigned[0] if assigned else None)
    d["domain_ids"] = [a.domain_id for a in assigned]
    d["domain_id"] = primary.domain_id if primary else None
    d["domain_name"] = primary.domain_name if primary else None
    d["domain_count"] = len(assigned)
    d["has_domain"] = bool(assigned)


def _add_asset_certification(d: Dict[str, Any], asset) -> None:
    level = asset.certification_level or 0
    inherited = asset.inherited_certification_level or 0
    d["certification_level"] = level
    d["inherited_certification_level"] = inherited
    d["is_certified"] = bool(level)
    d["effective_certification"] = max(level, inherited)
    expires = asset.certification_expires_at
    if expires is not None and expires.tzinfo is None:
        expires = expires.replace(tzinfo=timezone.utc)
    d["is_certification_expired"] = bool(expires and expires <= datetime.now(timezone.utc))


def _add_asset_properties(d: Dict[str, Any], properties: Any) -> None:
    props = properties if isinstance(properties, dict) else {}
    d["properties"] = props
    d["property_count"] = sum(1 for v in props.values() if v not in (None, "", [], {}))
    for key, value in props.items():
        name = f"prop_{key}"
        if re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", str(key)) and name not in d:
            d[name] = value


def _relationships_of(db: Session, entity_type: str, entity_id: str) -> list:
    from src.db_models.entity_relationships import EntityRelationshipDb

    return (
        db.query(EntityRelationshipDb)
        .filter(
            or_(
                and_(EntityRelationshipDb.source_type == entity_type,
                     EntityRelationshipDb.source_id == entity_id),
                and_(EntityRelationshipDb.target_type == entity_type,
                     EntityRelationshipDb.target_id == entity_id),
            )
        )
        .all()
    )


def _business_term_count(rels: list, entity_id: str) -> int:
    return (
        sum(1 for r in rels if r.source_id == entity_id and r.relationship_type == "hasTerm")
        + sum(1 for r in rels if r.target_id == entity_id
              and r.relationship_type in ("relatesTo", "hasTerm"))
    )


def _add_semantic_link_count(db: Session, d: Dict[str, Any],
                             entity_type: str, entity_id: str) -> None:
    from src.db_models.semantic_links import EntitySemanticLinkDb

    count = (
        db.query(func.count(EntitySemanticLinkDb.id))
        .filter(
            EntitySemanticLinkDb.entity_type == entity_type,
            EntitySemanticLinkDb.entity_id == entity_id,
        )
        .scalar()
    ) or 0
    d["semantic_link_count"] = count
    d["has_semantic_links"] = count > 0


def _extract_base_fields(db_obj) -> Dict[str, Any]:
    """Extract common scalar fields from a SQLAlchemy model."""
    d: Dict[str, Any] = {}
    for col in db_obj.__table__.columns:
        val = getattr(db_obj, col.name, None)
        d[col.name] = val
    return d


def _add_relationship_counts(db: Session, d: Dict[str, Any],
                              entity_type: str, entity_id: str) -> None:
    """Count relationships by type and add to dict."""
    from src.db_models.entity_relationships import EntityRelationshipDb

    rels = _relationships_of(db, entity_type, entity_id)

    # Count by relationship type
    outgoing = [r for r in rels if r.source_id == entity_id]

    d["relationship_count"] = len(rels)

    # Specific relationship counts
    d["dataset_count"] = sum(1 for r in outgoing if r.relationship_type == "hasDataset")
    d["business_term_count"] = _business_term_count(rels, entity_id)
    d["upstream_system_count"] = sum(
        1 for r in outgoing if r.relationship_type == "deployedOnSystem"
    )
    d["upstream_product_count"] = sum(
        1 for r in outgoing if r.relationship_type == "dependsOn"
    )
    d["delivery_channel_count"] = sum(
        1 for r in outgoing if r.relationship_type == "exposes"
    )
    d["has_business_terms"] = d["business_term_count"] > 0
    d["has_upstream_lineage"] = (d["upstream_system_count"] + d["upstream_product_count"]) > 0
    d["has_delivery_channels"] = d["delivery_channel_count"] > 0

    # Logical attribute mappings (via datasets)
    logical_attr_count = 0
    for dr in [r for r in outgoing if r.relationship_type == "hasDataset"]:
        ds_rels = (
            db.query(EntityRelationshipDb)
            .filter(
                or_(
                    and_(EntityRelationshipDb.source_type == "Dataset",
                         EntityRelationshipDb.source_id == dr.target_id),
                    and_(EntityRelationshipDb.target_type == "Dataset",
                         EntityRelationshipDb.target_id == dr.target_id),
                )
            )
            .all()
        )
        for dsr in ds_rels:
            if dsr.relationship_type == "implementedBy" and dsr.source_type == "LogicalAttribute":
                logical_attr_count += 1
    d["logical_attribute_mapping_count"] = logical_attr_count
    d["has_logical_attribute_mappings"] = logical_attr_count > 0


def _add_tag_count(db: Session, d: Dict[str, Any],
                    entity_id: str, entity_type: str) -> None:
    """Count tags assigned to entity."""
    from src.db_models.tags import EntityTagAssociationDb
    count = (
        db.query(func.count(EntityTagAssociationDb.id))
        .filter(
            and_(
                EntityTagAssociationDb.entity_id == entity_id,
                EntityTagAssociationDb.entity_type == entity_type,
            )
        )
        .scalar()
    ) or 0
    d["tag_count"] = count
    d["has_tags"] = count > 0


def _add_quality_check_count(db: Session, d: Dict[str, Any],
                              entity_type: str, entity_id: str) -> None:
    """Count quality items for entity."""
    try:
        from src.db_models.quality import QualityItemDb
        count = (
            db.query(func.count(QualityItemDb.id))
            .filter(
                and_(
                    QualityItemDb.entity_type == entity_type,
                    QualityItemDb.entity_id == entity_id,
                )
            )
            .scalar()
        ) or 0
    except Exception:
        count = 0
    d["quality_check_count"] = count
    d["has_quality_checks"] = count > 0
