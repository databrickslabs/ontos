"""Build enriched entity dictionaries for compliance DSL evaluation.

Produces a flat dict with raw entity fields + computed relationship/governance
counts so that maturity gate rules can use simple assertions like
``obj.business_term_count > 0`` or ``obj.certification_level >= 2``.

The same dict is what a workflow rule sees (``workflow_executor._rule_object``)
and what a compliance run sees for data products and data contracts
(``AppEntityLoader``). The ``build_*_dicts`` functions build many entities with
one query per kind of data, so a run over many entities doesn't query per entity.
"""
from typing import Dict, Any, Iterable, List, Optional

from sqlalchemy.orm import Session, selectinload
from sqlalchemy import func, and_, or_

from src.common.ontology_type_names import canonical_type_name
from src.common.logging import get_logger

logger = get_logger(__name__)


# Loader entity types (the MATCH types of compliance rules) and the entity_type their
# semantic links are stored under. The review type has no links (a review covers many
# assets), so it has no entry and its run dict has no concept fields.
CONCEPT_LINK_TYPES = {
    'data_product': 'data_product',
    'data_contract': 'data_contract',
    'domain': 'data_domain',
}


def build_data_product_dict(db: Session, product_id: str) -> Optional[Dict[str, Any]]:
    """Build an enriched dict for a DataProduct."""
    return build_data_product_dicts(db, [product_id]).get(str(product_id))


def build_data_product_dicts(db: Session, product_ids: Iterable[Any]) -> Dict[str, Dict[str, Any]]:
    """Enriched dicts for many DataProducts, keyed by id. Ids that don't exist are left out."""
    from src.db_models.data_products import DataProductDb
    products = _rows_by_id(db, DataProductDb, product_ids)
    if not products:
        return {}
    common = _common_fields(
        db, 'DataProduct', [(pid, p.owner_team_id) for pid, p in products.items()],
    )

    result: Dict[str, Dict[str, Any]] = {}
    for product_id, product in products.items():
        base = _extract_base_fields(product)
        base.update(common[product_id])
        base["entity_type"] = "DataProduct"
        base["type"] = "data_product"
        base["owner"] = product.owner_team_id

        # Description fields. ``description`` is the purpose text, as compliance rules read it.
        desc = product.description
        base["description"] = desc.purpose if desc else None
        base["has_description"] = bool(desc and (desc.purpose or desc.usage))
        base["has_purpose"] = bool(desc and desc.purpose)
        base["has_usage"] = bool(desc and desc.usage)

        # Owner
        base["has_owner"] = bool(product.owner_team_id)

        # Output ports / contracts
        output_ports = product.output_ports or []
        base["output_port_count"] = len(output_ports)
        contract_count = sum(
            len(getattr(op, "input_contracts", None) or [])
            for op in output_ports
        )
        base["contract_count"] = contract_count
        # Output ports linked to a data contract (OutputPortDb.contract_id): the output contracts.
        # ``contract_count`` above counts the input contracts the ports are built from.
        base["output_port_contract_count"] = sum(1 for op in output_ports if op.contract_id)
        base["has_contract"] = base["output_port_contract_count"] > 0

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

        result[product_id] = base

    _add_relationship_fields(db, result, "DataProduct")
    return result


def build_data_contract_dict(db: Session, contract_id: str) -> Optional[Dict[str, Any]]:
    """Build an enriched dict for a DataContract."""
    return build_data_contract_dicts(db, [contract_id]).get(str(contract_id))


def build_data_contract_dicts(db: Session, contract_ids: Iterable[Any]) -> Dict[str, Dict[str, Any]]:
    """Enriched dicts for many DataContracts, keyed by id. Ids that don't exist are left out."""
    from src.db_models.data_contracts import DataContractDb
    contracts = _rows_by_id(
        db, DataContractDb, contract_ids, options=[selectinload(DataContractDb.schema_objects)],
    )
    if not contracts:
        return {}
    common = _common_fields(
        db, 'DataContract', [(cid, c.owner_team_id) for cid, c in contracts.items()],
    )

    result: Dict[str, Dict[str, Any]] = {}
    for contract_id, contract in contracts.items():
        base = _extract_base_fields(contract)
        base.update(common[contract_id])
        base["entity_type"] = "DataContract"
        base["type"] = "data_contract"
        base["owner"] = contract.owner_team_id
        base["description"] = contract.description_purpose

        # Description
        base["has_description"] = bool(contract.description_purpose or contract.description_usage)
        base["has_purpose"] = bool(contract.description_purpose)

        # Owner
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

        result[contract_id] = base

    _add_relationship_fields(db, result, "DataContract")
    return result


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

# The entity type tag assignments, quality items, semantic links and domain
# assignments are stored under (the tags API, ``QualityManager``), by the entity
# type relationships use
_ASSOCIATION_ENTITY_TYPES = {
    "DataProduct": "data_product",
    "DataContract": "data_contract",
}


def _rows_by_id(db: Session, model, ids: Iterable[Any], options=()) -> Dict[str, Any]:
    """The rows of ``model`` with these ids, keyed by id (one query; none for no ids)."""
    keys = list(dict.fromkeys(str(i) for i in ids))
    if not keys:
        return {}
    query = db.query(model)
    for option in options:
        query = query.options(option)
    return {str(row.id): row for row in query.filter(model.id.in_(keys)).all()}


def _extract_base_fields(db_obj) -> Dict[str, Any]:
    """Extract common scalar fields from a SQLAlchemy model."""
    d: Dict[str, Any] = {}
    for col in db_obj.__table__.columns:
        val = getattr(db_obj, col.name, None)
        d[col.name] = val
    return d


def _common_fields(db: Session, kind: str, owners: List[tuple]) -> Dict[str, Dict[str, Any]]:
    """The fields products and contracts share, per id: tags, quality, links, domain, owner team.

    ``owners`` is ``[(id, owner_team_id)]``. Each lookup is one query for all ids.
    """
    from src.repositories.tags_repository import entity_tag_repo
    from src.repositories.entity_domain_association_repository import entity_domain_repo
    from src.common.compliance_entities import tag_values, tags_load_error

    entity_type = _ASSOCIATION_ENTITY_TYPES[kind]
    ids = [entity_id for entity_id, _ in owners]
    out: Dict[str, Dict[str, Any]] = {entity_id: {} for entity_id in ids}

    # Tags (the values as compliance rules read them). A failed lookup is the
    # coded error of a compliance run, as AppEntityLoader raises it.
    try:
        with db.begin_nested():
            assigned_tags = entity_tag_repo.get_assigned_tags_for_entities(
                db, entity_ids=ids, entity_type=entity_type,
            )
    except Exception as e:
        raise tags_load_error(entity_type) from e
    for entity_id in ids:
        assigned = assigned_tags.get(entity_id, [])
        out[entity_id]["tags"] = tag_values(assigned)
        out[entity_id]["tag_count"] = len(assigned)
        out[entity_id]["has_tags"] = bool(assigned)

    # Quality items
    out_quality = _quality_counts(db, entity_type, ids)
    for entity_id in ids:
        count = out_quality.get(entity_id, 0)
        out[entity_id]["quality_check_count"] = count
        out[entity_id]["has_quality_checks"] = count > 0

    # Relationship counts are added after the dicts exist (_add_relationship_fields)

    # Semantic links
    concepts = concept_fields_by_entity(db, entity_type, ids)
    for entity_id in ids:
        out[entity_id].update(concepts[entity_id])

    # Domain: the primary domain, by name and by id
    domains = entity_domain_repo.get_domains_for_entities(
        db, entity_type=entity_type, entity_ids=ids,
    )
    for entity_id in ids:
        primary = next((a for a in domains.get(entity_id, []) if a.is_primary), None)
        out[entity_id]["domain"] = primary.domain_name if primary else None
        out[entity_id]["domain_name"] = primary.domain_name if primary else None
        out[entity_id]["domain_id"] = primary.domain_id if primary else None

    # Owner team: name and the emails of its user members
    owner_ids = {owner for _, owner in owners if owner}
    team_names, team_emails = _team_owner_fields(db, owner_ids)
    for entity_id, owner_team_id in owners:
        out[entity_id]["owner_team_name"] = team_names.get(owner_team_id)
        out[entity_id]["owner_emails"] = team_emails.get(owner_team_id, [])
    return out


def _quality_counts(db: Session, entity_type: str, ids: List[str]) -> Dict[str, int]:
    """Quality item counts per entity id (empty when the count can't be read)."""
    if not ids:
        return {}
    try:
        from src.db_models.quality import QualityItemDb
        rows = (
            db.query(QualityItemDb.entity_id, func.count(QualityItemDb.id))
            .filter(
                and_(
                    QualityItemDb.entity_type == entity_type,
                    QualityItemDb.entity_id.in_(ids),
                )
            )
            .group_by(QualityItemDb.entity_id)
            .all()
        )
        return {entity_id: count for entity_id, count in rows}
    except Exception:
        return {}


def _team_owner_fields(db: Session, team_ids: set):
    """(team name by id, sorted user emails by team id) for the owner teams."""
    if not team_ids:
        return {}, {}
    from src.db_models.teams import TeamDb, TeamMemberDb
    names = {
        team_id: name
        for team_id, name in db.query(TeamDb.id, TeamDb.name).filter(TeamDb.id.in_(team_ids)).all()
    }
    emails: Dict[str, set] = {}
    members = (
        db.query(TeamMemberDb.team_id, TeamMemberDb.member_identifier)
        .filter(TeamMemberDb.team_id.in_(team_ids), TeamMemberDb.member_type == "user")
        .all()
    )
    for team_id, email in members:
        emails.setdefault(team_id, set()).add(email)
    return names, {team_id: sorted(addresses) for team_id, addresses in emails.items()}


def concept_fields(links: List[Any]) -> Dict[str, Any]:
    """The concept fields of one entity, from its semantic link rows."""
    concepts = [{'iri': link.iri, 'label': link.label} for link in links]
    return {
        'concepts': concepts,
        'concept_iris': [c['iri'] for c in concepts],
        'concept_labels': [c['label'] for c in concepts if c['label']],
        'concept_count': len(concepts),
        'has_concepts': bool(concepts),
    }


def concept_fields_by_entity(db: Session, loader_type: str, entity_ids: Iterable[Any]) -> Dict[str, Dict[str, Any]]:
    """Concept fields for many entities of one loader type, in one query.

    ``loader_type`` is a key of CONCEPT_LINK_TYPES (``data_product``, ``data_contract``,
    ``domain``). Every id gets an entry, with no concepts when it has no links.
    """
    from src.repositories.semantic_links_repository import entity_semantic_links_repo

    ids = list(dict.fromkeys(str(i) for i in entity_ids))
    link_type = CONCEPT_LINK_TYPES[loader_type]
    links_by_id: Dict[str, List[Any]] = {i: [] for i in ids}
    for link in entity_semantic_links_repo.list_for_entities(db, ids, link_type):
        links_by_id.setdefault(link.entity_id, []).append(link)
    return {
        entity_id: concept_fields(sorted(links, key=lambda l: ((l.label or l.iri), l.iri)))
        for entity_id, links in links_by_id.items()
    }


def _related_rows(db: Session, type_name: str, ids: Iterable[str]) -> Dict[str, List[Any]]:
    """Relationship rows touching each id of one type, in one query.

    A row counts for an id when its source or its target is that id, as a row of
    that type (a row linking the id to itself counts once).
    """
    from src.db_models.entity_relationships import EntityRelationshipDb

    wanted = set(ids)
    rows_by_id: Dict[str, List[Any]] = {i: [] for i in wanted}
    if not wanted:
        return rows_by_id
    rels = (
        db.query(EntityRelationshipDb)
        .filter(
            or_(
                and_(EntityRelationshipDb.source_type == type_name,
                     EntityRelationshipDb.source_id.in_(wanted)),
                and_(EntityRelationshipDb.target_type == type_name,
                     EntityRelationshipDb.target_id.in_(wanted)),
            )
        )
        .all()
    )
    for r in rels:
        matched = set()
        if r.source_type == type_name and r.source_id in wanted:
            matched.add(r.source_id)
        if r.target_type == type_name and r.target_id in wanted:
            matched.add(r.target_id)
        for entity_id in matched:
            rows_by_id[entity_id].append(r)
    return rows_by_id


def _add_relationship_fields(db: Session, result: Dict[str, Dict[str, Any]], entity_type: str) -> None:
    """Count relationships by type and add to each dict of ``result`` (keyed by id)."""
    canonical = canonical_type_name(entity_type)
    rels_by_id = _related_rows(db, canonical, result.keys())

    # Logical attribute mappings (via datasets): the datasets each entity has
    dataset_ids = {
        r.target_id
        for entity_id in result
        for r in rels_by_id[entity_id]
        if r.source_id == entity_id and r.relationship_type == "hasDataset"
    }
    datasets_rels = _related_rows(db, "Dataset", dataset_ids)

    for entity_id, d in result.items():
        rels = rels_by_id[entity_id]
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

        logical_attr_count = 0
        for dr in [r for r in outgoing if r.relationship_type == "hasDataset"]:
            for dsr in datasets_rels.get(dr.target_id, []):
                if dsr.relationship_type == "implementedBy" and dsr.source_type == "LogicalAttribute":
                    logical_attr_count += 1
        d["logical_attribute_mapping_count"] = logical_attr_count
        d["has_logical_attribute_mappings"] = logical_attr_count > 0
