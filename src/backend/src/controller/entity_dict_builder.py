"""Build enriched entity dictionaries for compliance DSL evaluation.

Produces a flat dict with raw entity fields + computed relationship/governance
counts so that maturity gate rules can use simple assertions like
``obj.business_term_count > 0`` or ``obj.certification_level >= 2``.
"""
from typing import Dict, Any, Optional

from sqlalchemy.orm import Session
from sqlalchemy import func, and_, or_

from src.common.logging import get_logger

logger = get_logger(__name__)


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


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

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

    rels = (
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

    # Count by relationship type
    outgoing = [r for r in rels if r.source_id == entity_id]
    incoming = [r for r in rels if r.target_id == entity_id]

    d["relationship_count"] = len(rels)

    # Specific relationship counts
    d["dataset_count"] = sum(1 for r in outgoing if r.relationship_type == "hasDataset")
    d["business_term_count"] = (
        sum(1 for r in outgoing if r.relationship_type == "hasTerm") +
        sum(1 for r in incoming if r.relationship_type in ("relatesTo", "hasTerm"))
    )
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
