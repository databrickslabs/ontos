"""Derived relationships for the business → physical model lineage.

The model stack is spread over several features rather than stored as
``entity_relationships`` rows:

  business   Concepts (RDF), linked via ``entity_semantic_links``
  delivery   Data Products → Output Ports
  logical    Data Contracts → ODCS schema objects → schema properties
  physical   Assets (Dataset/Table/View/Column), bound by contract
             ``physical_name`` / port ``asset_identifier`` → asset ``location``

This module computes those links at query time so the business lineage BFS
can walk them alongside stored relationships. Derived edges are oriented
business → physical, so "upstream" means toward the business and
"downstream" toward the platform.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Set, Tuple
from uuid import UUID

from sqlalchemy import func, or_
from sqlalchemy.orm import Session

from src.common.logging import get_logger

logger = get_logger(__name__)

# Synthetic node types (not ontology classes, not assets)
CONCEPT = "Concept"
SCHEMA_OBJECT = "SchemaObject"
SCHEMA_PROPERTY = "SchemaProperty"
SYNTHETIC_TYPES = {CONCEPT, SCHEMA_OBJECT, SCHEMA_PROPERTY}

# Derived relationship types
REL_DESCRIBES = "describes"            # Concept → entity
REL_HAS_OUTPUT_PORT = "hasOutputPort"  # DataProduct → OutputPort
REL_PORT_CONTRACT = "portHasContract"  # OutputPort → DataContract
REL_PORT_ASSET = "portHasAsset"        # OutputPort → Table/View/Dataset
REL_HAS_SCHEMA = "hasSchemaObject"     # DataContract → SchemaObject
REL_HAS_PROPERTY = "hasProperty"       # SchemaObject|SchemaProperty → SchemaProperty
REL_IMPLEMENTED_BY = "implementedBy"   # SchemaObject → Table/View, SchemaProperty → Column

REL_LABELS = {
    REL_DESCRIBES: "describes",
    REL_HAS_OUTPUT_PORT: "has output port",
    REL_PORT_CONTRACT: "governed by",
    REL_PORT_ASSET: "exposes",
    REL_HAS_SCHEMA: "has schema",
    REL_HAS_PROPERTY: "has property",
    REL_IMPLEMENTED_BY: "implemented by",
}

# Containment links that do not consume BFS breadth and ignore the direction
# filter — a contract is shown with its schema, a product with its ports.
# All are stored parent → child.
ZERO_COST_RELS = {REL_HAS_OUTPUT_PORT, REL_HAS_SCHEMA, REL_HAS_PROPERTY, "hasColumn"}

# Hard cap on nodes per lineage graph — each visited node costs several
# queries, and containment adds nodes without consuming depth.
MAX_LINEAGE_NODES = 500

# Layer fallback for types the ontology does not annotate with ontos:modelLayer
SYNTHETIC_LAYERS = {
    CONCEPT: "business",
    SCHEMA_OBJECT: "logical",
    SCHEMA_PROPERTY: "logical",
}
DEFAULT_LAYER = "physical"
MODEL_LAYERS = ("business", "delivery", "logical", "physical", "other")

# Lane order for flow orientation; 'other' (governance/org) has no rank
LAYER_RANK = {"business": 0, "delivery": 1, "logical": 2, "physical": 3}

# Relationships whose stored direction points *against* the flow
# (business → platform, provider → consumer). Used only within a layer or
# when 'other' is involved; across ranked layers the layer order decides.
REVERSED_FLOW_RELS = {
    "dependsOn",           # consumer → provider
    "consumesFrom",        # consumer → provider
    "derivedFrom",         # derived → source
    "outputFrom",          # output → producer
    "governedBy",          # governed → contract
    "implementsContract",  # table → contract
    "hasTerm",             # entity → term
    "hasSemanticConcept",  # entity → concept
    "attachedPolicy",      # entity → policy
    "belongsToDomain",     # entity → domain
    "ownedByTeam",         # entity → team
    "inProject",           # entity → project
    "belongsToSystem",     # asset → system
    "deployedOnSystem",    # asset → system
}


def is_forward_flow(relationship_type: str, source_layer: Optional[str], target_layer: Optional[str]) -> bool:
    """True when the stored source is the upstream end of the edge."""
    si, ti = LAYER_RANK.get(source_layer or ""), LAYER_RANK.get(target_layer or "")
    if si is not None and ti is not None and si != ti:
        return si < ti
    return relationship_type not in REVERSED_FLOW_RELS


# Legacy CDM asset types superseded by ODCS schema objects/properties.
# Hidden from lineage unless they are the center entity.
HIDDEN_LINEAGE_TYPES = {"LogicalEntity", "LogicalAttribute"}

PHYSICAL_TABLE_TYPES = ("Table", "View")
MAX_CONCEPT_FANOUT = 30

# Semantic-link entity_type for dedicated types
_SEMANTIC_LINK_TYPE = {
    "DataContract": "data_contract",
    "DataProduct": "data_product",
    "DataDomain": "data_domain",
}
_SEMANTIC_LINK_TYPE_REVERSE = {v: k for k, v in _SEMANTIC_LINK_TYPE.items()}
_DEDICATED_TYPES = {"DataProduct", "DataDomain", "DataContract", "Team", "Project", "OutputPort"}


@dataclass
class LineageAccess:
    """Per-caller read checks for entities with their own visibility rules.

    Each callable receives the ORM row. Sub-entities inherit: output ports from
    their product, schema objects/properties from their contract.
    """
    can_read_product: Callable[[Any], bool]
    can_read_contract: Callable[[Any], bool]


@dataclass
class LineageRequest:
    """State for one lineage request: caches shared by both passes of
    "Both", the caller's access checks, and the truncation signal."""
    access: Optional[LineageAccess] = None
    links: Dict[Tuple[str, str], List[tuple]] = field(default_factory=dict)
    visible: Dict[Tuple[str, str], bool] = field(default_factory=dict)
    physical_assets: Dict[Tuple[str, bool], List[Any]] = field(default_factory=dict)
    unresolvable: Set[str] = field(default_factory=set)
    truncated: bool = False
    # Row and index caches — a schema of N properties bound to tables of N
    # columns must not cost O(N) queries per property
    rows: Dict[Tuple[str, str], Any] = field(default_factory=dict)
    props_by_object: Dict[str, List[Any]] = field(default_factory=dict)
    columns_by_table: Dict[str, Dict[str, List[str]]] = field(default_factory=dict)
    props_by_table: Dict[str, Dict[str, List[str]]] = field(default_factory=dict)
    parent_tables: Dict[str, List[Any]] = field(default_factory=dict)


@dataclass(frozen=True)
class DerivedLink:
    source_type: str
    source_id: str
    target_type: str
    target_id: str
    relationship_type: str


def _as_uuid(value: str) -> Optional[UUID]:
    try:
        return UUID(str(value))
    except (ValueError, TypeError):
        return None


def _iri_local_name(iri: str) -> str:
    for sep in ("#", "/"):
        if sep in iri:
            tail = iri.rsplit(sep, 1)[-1]
            if tail:
                return tail
    return iri


def _location_suffixes(location: str) -> List[str]:
    """'a.b.c' → ['a.b.c', 'b.c', 'c'] (lower-cased)."""
    parts = location.lower().split(".")
    return [".".join(parts[i:]) for i in range(len(parts))]


def _matches_location(physical_name: str, location: Optional[str]) -> bool:
    if not physical_name or not location:
        return False
    pn = physical_name.lower()
    loc = location.lower()
    return loc == pn or loc.endswith("." + pn)


class ModelLineageResolver:
    """Computes derived model-lineage links and resolves synthetic nodes."""

    # ------------------------------------------------------------------
    # Node resolution
    # ------------------------------------------------------------------

    def resolve(
        self, db: Session, entity_type: str, entity_id: str, req: Optional[LineageRequest] = None,
    ) -> Optional[Dict[str, Any]]:
        """Resolve a synthetic node. Returns None for non-synthetic types."""
        req = req or LineageRequest()
        try:
            if entity_type == CONCEPT:
                return self._resolve_concept(db, entity_id)
            if entity_type == SCHEMA_OBJECT:
                obj = self._schema_object(db, entity_id, req)
                if obj:
                    return {
                        "name": obj.business_name or obj.name,
                        "status": None,
                        "description": obj.description,
                        "context_id": obj.contract_id,
                    }
            if entity_type == SCHEMA_PROPERTY:
                prop = self._schema_property(db, entity_id, req)
                if prop:
                    obj = self._schema_object(db, prop.object_id, req)
                    return {
                        "name": prop.business_name or prop.name,
                        "status": prop.logical_type,
                        "description": prop.transform_description,
                        "context_id": obj.contract_id if obj else None,
                    }
        except Exception as e:
            logger.warning(f"Failed to resolve model-lineage node {entity_type}:{entity_id}: {e}")
        return None

    def _resolve_concept(self, db: Session, iri: str) -> Dict[str, Any]:
        from src.db_models.semantic_links import EntitySemanticLinkDb
        label = (
            db.query(EntitySemanticLinkDb.label)
            .filter(EntitySemanticLinkDb.iri == iri, EntitySemanticLinkDb.label.isnot(None))
            .limit(1)
            .scalar()
        )
        return {"name": label or _iri_local_name(iri), "status": None, "description": iri}

    @staticmethod
    def output_port_context(db: Session, port_id: str) -> Optional[str]:
        from src.db_models.data_products import OutputPortDb
        port = db.query(OutputPortDb).filter(OutputPortDb.id == port_id).first()
        return port.product_id if port else None

    # ------------------------------------------------------------------
    # Neighbors
    # ------------------------------------------------------------------

    def neighbors(
        self, db: Session, entity_type: str, entity_id: str, req: Optional[LineageRequest] = None,
    ) -> List[DerivedLink]:
        """All derived links touching the entity (either direction)."""
        req = req or LineageRequest()
        links: List[DerivedLink] = []
        try:
            if entity_type == CONCEPT:
                links.extend(self._concept_links(db, entity_id, req))
            else:
                links.extend(self._semantic_links_for(db, entity_type, entity_id, req))

            if entity_type == "DataProduct":
                links.extend(self._product_links(db, entity_id))
            elif entity_type == "OutputPort":
                links.extend(self._port_links(db, entity_id, req))
            elif entity_type == "DataContract":
                links.extend(self._contract_links(db, entity_id))
            elif entity_type == SCHEMA_OBJECT:
                links.extend(self._schema_object_links(db, entity_id, req))
            elif entity_type == SCHEMA_PROPERTY:
                links.extend(self._schema_property_links(db, entity_id, req))
            elif entity_type in PHYSICAL_TABLE_TYPES or entity_type == "Dataset":
                links.extend(self._table_links(db, entity_type, entity_id, req))
            elif entity_type == "Column":
                links.extend(self._column_links(db, entity_id, req))
        except Exception as e:
            logger.warning(f"Derived lineage lookup failed for {entity_type}:{entity_id}: {e}")
        return links

    # --- semantic links ------------------------------------------------

    def _semantic_keys(self, db: Session, entity_type: str, entity_id: str, req: LineageRequest) -> List[Tuple[str, str]]:
        """(semantic-link entity_type, entity_id) pairs under which an entity may be linked."""
        if entity_type in _SEMANTIC_LINK_TYPE:
            return [(_SEMANTIC_LINK_TYPE[entity_type], entity_id)]
        if entity_type == SCHEMA_OBJECT:
            obj = self._schema_object(db, entity_id, req)
            return [("data_contract_schema", f"{obj.contract_id}#{obj.name}")] if obj else []
        if entity_type == SCHEMA_PROPERTY:
            prop = self._schema_property(db, entity_id, req)
            obj = self._schema_object(db, prop.object_id, req) if prop else None
            if obj:
                return [("data_contract_property", f"{obj.contract_id}#{obj.name}#{prop.name}")]
            return []
        if entity_type in _DEDICATED_TYPES:
            return []
        # Asset-backed: canonical 'asset', plus legacy per-type / 'dataset' keys
        return [("asset", entity_id), (entity_type, entity_id), ("dataset", entity_id)]

    def _semantic_links_for(self, db: Session, entity_type: str, entity_id: str, req: LineageRequest) -> List[DerivedLink]:
        from src.db_models.semantic_links import EntitySemanticLinkDb
        keys = self._semantic_keys(db, entity_type, entity_id, req)
        if not keys:
            return []
        rows = (
            db.query(EntitySemanticLinkDb.iri)
            .filter(or_(*[
                (EntitySemanticLinkDb.entity_type == t) & (EntitySemanticLinkDb.entity_id == i)
                for t, i in keys
            ]))
            .distinct()
            .all()
        )
        return [DerivedLink(CONCEPT, r.iri, entity_type, entity_id, REL_DESCRIBES) for r in rows]

    def _concept_links(self, db: Session, iri: str, req: LineageRequest) -> List[DerivedLink]:
        """Concept → every entity linked to it, capped deterministically; an
        overflow marks the request truncated."""
        from src.db_models.semantic_links import EntitySemanticLinkDb
        rows = (
            db.query(EntitySemanticLinkDb.entity_type, EntitySemanticLinkDb.entity_id)
            .filter(EntitySemanticLinkDb.iri == iri)
            .order_by(EntitySemanticLinkDb.entity_type, EntitySemanticLinkDb.entity_id)
            .limit(MAX_CONCEPT_FANOUT + 1)
            .all()
        )
        if len(rows) > MAX_CONCEPT_FANOUT:
            req.truncated = True
            rows = rows[:MAX_CONCEPT_FANOUT]
        links: List[DerivedLink] = []
        for row in rows:
            target = self._entity_for_semantic_key(db, row.entity_type, row.entity_id, req)
            if target:
                links.append(DerivedLink(CONCEPT, iri, target[0], target[1], REL_DESCRIBES))
        return links

    def _entity_for_semantic_key(
        self, db: Session, link_type: str, link_id: str, req: LineageRequest,
    ) -> Optional[Tuple[str, str]]:
        from src.db_models.data_contracts import SchemaObjectDb, SchemaPropertyDb
        if link_type in _SEMANTIC_LINK_TYPE_REVERSE:
            return _SEMANTIC_LINK_TYPE_REVERSE[link_type], link_id
        if link_type == "data_contract_schema":
            contract_id, _, schema_name = link_id.partition("#")
            obj = (
                db.query(SchemaObjectDb)
                .filter(SchemaObjectDb.contract_id == contract_id, SchemaObjectDb.name == schema_name)
                .first()
            )
            return (SCHEMA_OBJECT, obj.id) if obj else None
        if link_type == "data_contract_property":
            parts = link_id.split("#")
            if len(parts) < 3:
                return None
            contract_id, schema_name, prop_name = parts[0], parts[1], parts[-1]
            prop = (
                db.query(SchemaPropertyDb)
                .join(SchemaObjectDb, SchemaPropertyDb.object_id == SchemaObjectDb.id)
                .filter(
                    SchemaObjectDb.contract_id == contract_id,
                    SchemaObjectDb.name == schema_name,
                    SchemaPropertyDb.name == prop_name,
                )
                .first()
            )
            return (SCHEMA_PROPERTY, prop.id) if prop else None
        if link_type.startswith("uc_"):
            return None  # raw UC objects are not lineage nodes
        asset = self._asset(db, link_id, req)
        if asset is not None and asset.asset_type is not None:
            return asset.asset_type.name, str(asset.id)
        return None

    # --- delivery --------------------------------------------------------

    def _product_links(self, db: Session, product_id: str) -> List[DerivedLink]:
        from src.db_models.data_products import OutputPortDb
        ports = db.query(OutputPortDb.id).filter(OutputPortDb.product_id == product_id).all()
        return [DerivedLink("DataProduct", product_id, "OutputPort", p.id, REL_HAS_OUTPUT_PORT) for p in ports]

    def _port_links(self, db: Session, port_id: str, req: LineageRequest) -> List[DerivedLink]:
        from src.db_models.data_products import OutputPortDb
        port = db.query(OutputPortDb).filter(OutputPortDb.id == port_id).first()
        if not port:
            return []
        links = [DerivedLink("DataProduct", port.product_id, "OutputPort", port.id, REL_HAS_OUTPUT_PORT)]
        contract = self._contract_by_ref(db, port.contract_id)
        if contract is not None:
            links.append(DerivedLink("OutputPort", port.id, "DataContract", contract.id, REL_PORT_CONTRACT))
        if port.asset_identifier:
            for asset in self._physical_assets_at(db, port.asset_identifier, req, exact=True):
                links.append(DerivedLink("OutputPort", port.id, asset.asset_type.name, str(asset.id), REL_PORT_ASSET))
        return links

    @staticmethod
    def _contract_by_ref(db: Session, ref: Optional[str]):
        """Output ports reference contracts by id (or, in older data, by name).

        A name can match several versions; pick deterministically: active,
        then deprecated, then anything else — newest first within each.
        """
        if not ref:
            return None
        from src.db_models.data_contracts import DataContractDb
        contract = db.query(DataContractDb).filter(DataContractDb.id == ref).first()
        if contract is not None:
            return contract
        candidates = db.query(DataContractDb).filter(DataContractDb.name == ref).all()
        if not candidates:
            return None
        status_rank = {"active": 0, "deprecated": 1}

        def key(c):
            created = getattr(c, "created_at", None)
            return (
                status_rank.get((c.status or "").lower(), 2),
                -(created.timestamp() if created else 0),
                str(c.id),
            )

        return sorted(candidates, key=key)[0]

    # --- logical ---------------------------------------------------------

    def _contract_links(self, db: Session, contract_id: str) -> List[DerivedLink]:
        from src.db_models.data_contracts import DataContractDb, SchemaObjectDb
        from src.db_models.data_products import OutputPortDb
        links = [
            DerivedLink("DataContract", contract_id, SCHEMA_OBJECT, o.id, REL_HAS_SCHEMA)
            for o in db.query(SchemaObjectDb.id).filter(SchemaObjectDb.contract_id == contract_id).all()
        ]
        refs = [contract_id]
        name = db.query(DataContractDb.name).filter(DataContractDb.id == contract_id).scalar()
        if name:
            refs.append(name)
        for p in db.query(OutputPortDb.id).filter(OutputPortDb.contract_id.in_(refs)).all():
            links.append(DerivedLink("OutputPort", p.id, "DataContract", contract_id, REL_PORT_CONTRACT))
        return links

    def _schema_object_links(self, db: Session, object_id: str, req: LineageRequest) -> List[DerivedLink]:
        obj = self._schema_object(db, object_id, req)
        if not obj:
            return []
        links = [DerivedLink("DataContract", obj.contract_id, SCHEMA_OBJECT, obj.id, REL_HAS_SCHEMA)]
        top_props = [p for p in self._props_of_object(db, obj.id, req) if p.parent_property_id is None]
        links.extend(DerivedLink(SCHEMA_OBJECT, obj.id, SCHEMA_PROPERTY, p.id, REL_HAS_PROPERTY) for p in top_props)
        if obj.physical_name:
            for asset in self._physical_assets_at(db, obj.physical_name, req):
                links.append(DerivedLink(SCHEMA_OBJECT, obj.id, asset.asset_type.name, str(asset.id), REL_IMPLEMENTED_BY))
        return links

    def _schema_property_links(self, db: Session, prop_id: str, req: LineageRequest) -> List[DerivedLink]:
        prop = self._schema_property(db, prop_id, req)
        if not prop:
            return []
        links: List[DerivedLink] = []
        if prop.parent_property_id:
            links.append(DerivedLink(SCHEMA_PROPERTY, prop.parent_property_id, SCHEMA_PROPERTY, prop.id, REL_HAS_PROPERTY))
        else:
            links.append(DerivedLink(SCHEMA_OBJECT, prop.object_id, SCHEMA_PROPERTY, prop.id, REL_HAS_PROPERTY))
        children = [p for p in self._props_of_object(db, prop.object_id, req) if p.parent_property_id == prop.id]
        links.extend(DerivedLink(SCHEMA_PROPERTY, prop.id, SCHEMA_PROPERTY, c.id, REL_HAS_PROPERTY) for c in children)

        # Bind top-level properties to columns of the tables implementing the schema object
        obj = self._schema_object(db, prop.object_id, req)
        if obj is not None and obj.physical_name and not prop.parent_property_id:
            # Cached per physical name: resolved once per schema object, not per property
            for table in self._physical_assets_at(db, obj.physical_name, req):
                for col_id in self._columns_of_table(db, str(table.id), req).get(prop.name.lower(), []):
                    links.append(DerivedLink(SCHEMA_PROPERTY, prop.id, "Column", col_id, REL_IMPLEMENTED_BY))
        return links

    # --- physical --------------------------------------------------------

    def _table_links(self, db: Session, entity_type: str, asset_id: str, req: LineageRequest) -> List[DerivedLink]:
        from src.db_models.data_contracts import SchemaObjectDb
        from src.db_models.data_products import OutputPortDb
        asset = self._asset(db, asset_id, req)
        if asset is None or not asset.location:
            return []
        links: List[DerivedLink] = []
        if entity_type in PHYSICAL_TABLE_TYPES:
            objs = (
                db.query(SchemaObjectDb.id)
                .filter(func.lower(SchemaObjectDb.physical_name).in_(_location_suffixes(asset.location)))
                .all()
            )
            links.extend(DerivedLink(SCHEMA_OBJECT, o.id, entity_type, asset_id, REL_IMPLEMENTED_BY) for o in objs)
        ports = (
            db.query(OutputPortDb.id)
            .filter(func.lower(OutputPortDb.asset_identifier) == asset.location.lower())
            .all()
        )
        links.extend(DerivedLink("OutputPort", p.id, entity_type, asset_id, REL_PORT_ASSET) for p in ports)
        return links

    def _column_links(self, db: Session, column_id: str, req: LineageRequest) -> List[DerivedLink]:
        column = self._asset(db, column_id, req)
        if column is None:
            return []
        links: List[DerivedLink] = []
        for table in self._parent_tables(db, column_id, req):
            for prop_id in self._props_of_table(db, table, req).get(column.name.lower(), []):
                links.append(DerivedLink(SCHEMA_PROPERTY, prop_id, "Column", column_id, REL_IMPLEMENTED_BY))
        return links

    # ------------------------------------------------------------------
    # Lookups
    # ------------------------------------------------------------------

    def _schema_object(self, db: Session, object_id: str, req: LineageRequest):
        from src.db_models.data_contracts import SchemaObjectDb
        key = ("SchemaObject", str(object_id))
        if key not in req.rows:
            req.rows[key] = db.query(SchemaObjectDb).filter(SchemaObjectDb.id == object_id).first()
        return req.rows[key]

    def _schema_property(self, db: Session, prop_id: str, req: LineageRequest):
        from src.db_models.data_contracts import SchemaPropertyDb
        key = ("SchemaProperty", str(prop_id))
        if key not in req.rows:
            req.rows[key] = db.query(SchemaPropertyDb).filter(SchemaPropertyDb.id == prop_id).first()
        return req.rows[key]

    def _props_of_object(self, db: Session, object_id: str, req: LineageRequest) -> List[Any]:
        """All properties of a schema object (one query), also seeding the row cache."""
        from src.db_models.data_contracts import SchemaPropertyDb
        if object_id not in req.props_by_object:
            props = db.query(SchemaPropertyDb).filter(SchemaPropertyDb.object_id == object_id).all()
            req.props_by_object[object_id] = props
            for p in props:
                req.rows.setdefault(("SchemaProperty", str(p.id)), p)
        return req.props_by_object[object_id]

    def _asset(self, db: Session, asset_id: str, req: Optional[LineageRequest] = None):
        from src.db_models.assets import AssetDb
        uid = _as_uuid(asset_id)
        if uid is None:
            return None
        if req is None:
            return db.query(AssetDb).filter(AssetDb.id == uid).first()
        key = ("Asset", str(uid))
        if key not in req.rows:
            req.rows[key] = db.query(AssetDb).filter(AssetDb.id == uid).first()
        return req.rows[key]

    def _physical_assets_at(
        self, db: Session, physical_name: str, req: LineageRequest, exact: bool = False,
    ) -> List[Any]:
        """Table/View assets whose location equals or ends with the physical name.

        Contracts often carry a partial name (``schema.table``) while assets
        carry the FQN (``catalog.schema.table``); every matching environment
        (dev/prod catalogs, replicas) is returned. Cached per request: the
        suffix match is a leading-wildcard LIKE (no index), so it must run once
        per distinct name — not once per property.
        """
        pn = physical_name.strip().lower()
        if not pn:
            return []
        key = (pn, exact)
        if key not in req.physical_assets:
            req.physical_assets[key] = self._query_physical_assets(db, pn, exact)
        return req.physical_assets[key]

    @staticmethod
    def _query_physical_assets(db: Session, pn: str, exact: bool) -> List[Any]:
        from src.db_models.assets import AssetDb, AssetTypeDb
        query = (
            db.query(AssetDb)
            .join(AssetTypeDb, AssetDb.asset_type_id == AssetTypeDb.id)
            .filter(AssetTypeDb.name.in_(PHYSICAL_TABLE_TYPES + ("Dataset",)))
        )
        if exact:
            return query.filter(func.lower(AssetDb.location) == pn).all()
        # LIKE pre-filter ('_' is a wildcard there), exact suffix check in Python
        candidates = query.filter(func.lower(AssetDb.location).like(f"%{pn}")).all()
        return [
            a for a in candidates
            if a.asset_type.name in PHYSICAL_TABLE_TYPES and _matches_location(pn, a.location)
        ]

    def _columns_of_table(self, db: Session, table_id: str, req: LineageRequest) -> Dict[str, List[str]]:
        """Lower-cased column name → column asset ids for a table (two queries per table)."""
        if table_id in req.columns_by_table:
            return req.columns_by_table[table_id]
        from src.db_models.assets import AssetDb
        from src.db_models.entity_relationships import EntityRelationshipDb
        col_ids = [
            r.target_id for r in db.query(EntityRelationshipDb.target_id).filter(
                EntityRelationshipDb.source_id == table_id,
                EntityRelationshipDb.relationship_type == "hasColumn",
            ).all()
        ]
        uids = [u for u in (_as_uuid(c) for c in col_ids) if u is not None]
        index: Dict[str, List[str]] = {}
        if uids:
            for row in db.query(AssetDb).filter(AssetDb.id.in_(uids)).all():
                req.rows.setdefault(("Asset", str(row.id)), row)
                index.setdefault((row.name or "").lower(), []).append(str(row.id))
        req.columns_by_table[table_id] = index
        return index

    def _props_of_table(self, db: Session, table: Any, req: LineageRequest) -> Dict[str, List[str]]:
        """Lower-cased property name → top-level property ids of schema objects bound to a table."""
        table_id = str(table.id)
        if table_id in req.props_by_table:
            return req.props_by_table[table_id]
        index: Dict[str, List[str]] = {}
        if table.location:
            from src.db_models.data_contracts import SchemaObjectDb, SchemaPropertyDb
            rows = (
                db.query(SchemaPropertyDb)
                .join(SchemaObjectDb, SchemaPropertyDb.object_id == SchemaObjectDb.id)
                .filter(
                    func.lower(SchemaObjectDb.physical_name).in_(_location_suffixes(table.location)),
                    SchemaPropertyDb.parent_property_id.is_(None),
                )
                .all()
            )
            for p in rows:
                req.rows.setdefault(("SchemaProperty", str(p.id)), p)
                index.setdefault((p.name or "").lower(), []).append(p.id)
        req.props_by_table[table_id] = index
        return index

    def _parent_tables(self, db: Session, column_id: str, req: LineageRequest) -> List[Any]:
        if column_id in req.parent_tables:
            return req.parent_tables[column_id]
        from src.db_models.entity_relationships import EntityRelationshipDb
        rows = db.query(EntityRelationshipDb.source_id).filter(
            EntityRelationshipDb.target_id == column_id,
            EntityRelationshipDb.relationship_type == "hasColumn",
        ).all()
        tables: List[Any] = []
        for source_id in sorted({r.source_id for r in rows}):
            table = self._asset(db, source_id, req)
            if table is not None:
                tables.append(table)
        req.parent_tables[column_id] = tables
        return tables
