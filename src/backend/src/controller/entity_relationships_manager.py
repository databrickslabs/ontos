"""Manager for cross-tier entity relationships.

Validates relationship types against the ontology before persisting,
and resolves entity names for display.
"""

from __future__ import annotations

from collections import deque
from typing import Any, Deque, Dict, List, Optional, Set, TYPE_CHECKING
from uuid import UUID

from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError

from src.db_models.entity_relationships import EntityRelationshipDb
from src.repositories.entity_relationships_repository import entity_relationship_repo
from src.models.entity_relationships import (
    EntityRelationshipCreate,
    EntityRelationshipRead,
    EntityRelationshipSummary,
    InstanceHierarchyNode,
    HierarchyRootGroup,
    LineageGraph,
    LineageGraphNode,
    LineageGraphEdge,
)
from src.common.errors import ConflictError, NotFoundError
from src.controller.model_lineage import (
    DEFAULT_LAYER,
    HIDDEN_LINEAGE_TYPES,
    LAYER_RANK,
    MAX_LINEAGE_NODES,
    MODEL_LAYERS,
    REL_LABELS,
    SYNTHETIC_LAYERS,
    SYNTHETIC_TYPES,
    ZERO_COST_RELS,
    ModelLineageResolver,
    is_forward_flow,
)
from src.common.logging import get_logger

if TYPE_CHECKING:
    from src.controller.ontology_schema_manager import OntologySchemaManager

logger = get_logger(__name__)

ONTOS_NS = "http://ontos.app/ontology#"

DEDICATED_TYPE_RESOLVERS: Dict[str, str] = {
    "DataProduct": "data_products",
    "DataDomain": "data_domains",
    "DataContract": "data_contracts",
    "Team": "teams",
    "Project": "projects",
    "OutputPort": "data_product_output_ports",
}


class EntityRelationshipsManager:
    """Manages cross-tier entity relationships with ontology validation."""

    def __init__(self, ontology_schema_manager: "OntologySchemaManager"):
        self._osm = ontology_schema_manager
        self._model_lineage = ModelLineageResolver()
        self._layer_cache: Dict[str, str] = {}
        self._rel_label_cache: Dict[str, str] = {}
        logger.info("EntityRelationshipsManager initialized")

    # ------------------------------------------------------------------
    # Ontology validation
    # ------------------------------------------------------------------

    def _normalize_relationship_type(self, relationship_type: str) -> str:
        """Accept both local names ('hasDataset') and full IRIs."""
        if relationship_type.startswith("http://") or relationship_type.startswith("https://"):
            return relationship_type
        return f"{ONTOS_NS}{relationship_type}"

    def _normalize_entity_type(self, entity_type: str) -> str:
        """Accept both local names ('DataProduct') and full IRIs."""
        if entity_type.startswith("http://") or entity_type.startswith("https://"):
            return entity_type
        return f"{ONTOS_NS}{entity_type}"

    def _validate_relationship(
        self, source_type: str, target_type: str, relationship_type: str
    ) -> Optional[str]:
        """Validate that the ontology allows this (source_type, rel, target_type) triple.

        Returns the human-readable relationship label if valid, or raises ValueError.
        """
        source_iri = self._normalize_entity_type(source_type)
        rel_iri = self._normalize_relationship_type(relationship_type)

        rels = self._osm.get_relationships(source_iri)

        for r in rels.outgoing:
            if r.property_iri == rel_iri:
                target_iri = self._normalize_entity_type(target_type)
                if r.target_type_iri == target_iri:
                    return r.label
                # Check if target is a subclass of the declared range
                target_ancestors = set()
                from rdflib import URIRef, RDFS
                for ancestor in self._osm._graph.objects(URIRef(target_iri), RDFS.subClassOf):
                    target_ancestors.add(str(ancestor))
                if r.target_type_iri in target_ancestors:
                    return r.label

        raise ValueError(
            f"Ontology does not allow relationship '{relationship_type}' "
            f"from '{source_type}' to '{target_type}'"
        )

    # ------------------------------------------------------------------
    # CRUD
    # ------------------------------------------------------------------

    def create_relationship(
        self,
        db: Session,
        rel_in: EntityRelationshipCreate,
        current_user_id: str,
    ) -> EntityRelationshipRead:
        """Create a new entity relationship, validated against the ontology."""
        rel_label = self._validate_relationship(
            rel_in.source_type, rel_in.target_type, rel_in.relationship_type
        )

        existing = entity_relationship_repo.find_existing(
            db,
            source_type=rel_in.source_type,
            source_id=rel_in.source_id,
            target_type=rel_in.target_type,
            target_id=rel_in.target_id,
            relationship_type=rel_in.relationship_type,
        )
        if existing:
            raise ConflictError(
                f"Relationship already exists: {rel_in.source_type}:{rel_in.source_id} "
                f"--[{rel_in.relationship_type}]--> "
                f"{rel_in.target_type}:{rel_in.target_id}"
            )

        db_obj = EntityRelationshipDb(
            source_type=rel_in.source_type,
            source_id=rel_in.source_id,
            target_type=rel_in.target_type,
            target_id=rel_in.target_id,
            relationship_type=rel_in.relationship_type,
            properties=rel_in.properties,
            created_by=current_user_id,
        )

        try:
            db.add(db_obj)
            db.flush()
            db.refresh(db_obj)
        except IntegrityError as e:
            db.rollback()
            raise ConflictError(f"Relationship already exists (constraint violation): {e}")

        return self._to_read(db_obj, relationship_label=rel_label)

    def delete_relationship(self, db: Session, rel_id: UUID) -> None:
        """Delete a relationship by ID."""
        obj = entity_relationship_repo.get(db, rel_id)
        if not obj:
            raise NotFoundError(f"Entity relationship not found: {rel_id}")
        entity_relationship_repo.remove(db, id=rel_id)

    def get_relationship(self, db: Session, rel_id: UUID) -> EntityRelationshipRead:
        """Get a single relationship by ID."""
        obj = entity_relationship_repo.get(db, rel_id)
        if not obj:
            raise NotFoundError(f"Entity relationship not found: {rel_id}")
        return self._to_read(obj)

    # ------------------------------------------------------------------
    # Query methods
    # ------------------------------------------------------------------

    def get_outgoing(
        self, db: Session,
        source_type: str, source_id: str,
        relationship_type: Optional[str] = None,
    ) -> List[EntityRelationshipRead]:
        if relationship_type:
            rows = entity_relationship_repo.get_by_source_and_type(
                db, source_type=source_type, source_id=source_id,
                relationship_type=relationship_type,
            )
        else:
            rows = entity_relationship_repo.get_by_source(
                db, source_type=source_type, source_id=source_id,
            )
        return [self._to_read(r, db=db) for r in rows]

    def get_incoming(
        self, db: Session,
        target_type: str, target_id: str,
        relationship_type: Optional[str] = None,
    ) -> List[EntityRelationshipRead]:
        if relationship_type:
            rows = entity_relationship_repo.get_by_target_and_type(
                db, target_type=target_type, target_id=target_id,
                relationship_type=relationship_type,
            )
        else:
            rows = entity_relationship_repo.get_by_target(
                db, target_type=target_type, target_id=target_id,
            )
        return [self._to_read(r, db=db) for r in rows]

    def get_all_for_entity(
        self, db: Session, entity_type: str, entity_id: str
    ) -> EntityRelationshipSummary:
        """All relationships for an entity, split into outgoing/incoming.

        Also merges relationships from the legacy asset_relationships table
        so that schema-imported links are visible.
        """
        rows = entity_relationship_repo.get_for_entity(
            db, entity_type=entity_type, entity_id=entity_id,
        )

        outgoing = []
        incoming = []
        for r in rows:
            read = self._to_read(r, db=db)
            if r.source_type == entity_type and r.source_id == entity_id:
                outgoing.append(read)
            else:
                incoming.append(read)

        # Merge legacy asset_relationships if this is an asset-tier entity
        seen_keys = {
            (r.source_type, r.source_id, r.target_type, r.target_id, r.relationship_type)
            for r in rows
        }
        self._merge_asset_relationships(db, entity_id, outgoing, incoming, seen_keys)

        return EntityRelationshipSummary(
            entity_type=entity_type,
            entity_id=entity_id,
            outgoing=outgoing,
            incoming=incoming,
            total=len(outgoing) + len(incoming),
        )

    def _merge_asset_relationships(
        self,
        db: Session,
        entity_id: str,
        outgoing: list,
        incoming: list,
        seen_keys: set,
    ) -> None:
        """Merge legacy asset_relationships into the outgoing/incoming lists."""
        try:
            from src.db_models.assets import AssetRelationshipDb, AssetDb
            from sqlalchemy.orm import selectinload
            from sqlalchemy import or_
            from uuid import UUID as PyUUID

            try:
                asset_uuid = PyUUID(entity_id)
            except ValueError:
                return

            asset_rels = (
                db.query(AssetRelationshipDb)
                .options(
                    selectinload(AssetRelationshipDb.source_asset).selectinload(AssetDb.asset_type),
                    selectinload(AssetRelationshipDb.target_asset).selectinload(AssetDb.asset_type),
                )
                .filter(or_(
                    AssetRelationshipDb.source_asset_id == asset_uuid,
                    AssetRelationshipDb.target_asset_id == asset_uuid,
                ))
                .all()
            )

            for ar in asset_rels:
                src_type = ar.source_asset.asset_type.name if ar.source_asset and ar.source_asset.asset_type else "Asset"
                tgt_type = ar.target_asset.asset_type.name if ar.target_asset and ar.target_asset.asset_type else "Asset"
                key = (src_type, str(ar.source_asset_id), tgt_type, str(ar.target_asset_id), ar.relationship_type)
                if key in seen_keys:
                    continue
                seen_keys.add(key)

                rel_label = ar.relationship_type
                try:
                    rel_iri = self._normalize_relationship_type(ar.relationship_type)
                    from rdflib import URIRef, RDFS
                    lv = self._osm._graph.value(URIRef(rel_iri), RDFS.label)
                    if lv:
                        rel_label = str(lv)
                except Exception:
                    pass

                read = EntityRelationshipRead(
                    id=ar.id,
                    source_type=src_type,
                    source_id=str(ar.source_asset_id),
                    target_type=tgt_type,
                    target_id=str(ar.target_asset_id),
                    relationship_type=ar.relationship_type,
                    properties=ar.properties,
                    created_by=ar.created_by,
                    created_at=ar.created_at,
                    relationship_label=rel_label,
                    source_name=ar.source_asset.name if ar.source_asset else None,
                    target_name=ar.target_asset.name if ar.target_asset else None,
                )

                is_outgoing = str(ar.source_asset_id) == entity_id
                if is_outgoing:
                    outgoing.append(read)
                else:
                    incoming.append(read)
        except Exception as e:
            logger.debug(f"Failed to merge asset_relationships for {entity_id}: {e}")

    def query_relationships(
        self, db: Session, *,
        source_type: Optional[str] = None, source_id: Optional[str] = None,
        target_type: Optional[str] = None, target_id: Optional[str] = None,
        relationship_type: Optional[str] = None,
        skip: int = 0, limit: int = 100,
    ) -> List[EntityRelationshipRead]:
        rows = entity_relationship_repo.query_filtered(
            db,
            source_type=source_type, source_id=source_id,
            target_type=target_type, target_id=target_id,
            relationship_type=relationship_type,
            skip=skip, limit=limit,
        )
        return [self._to_read(r, db=db) for r in rows]

    # ------------------------------------------------------------------
    # Instance Hierarchy
    # ------------------------------------------------------------------

    def _resolve_entity(
        self, db: Session, entity_type: str, entity_id: str
    ) -> Optional[Dict[str, Any]]:
        """Resolve an entity's display info (name, status, description) by type and ID."""
        if entity_type in SYNTHETIC_TYPES:
            return self._model_lineage.resolve(db, entity_type, entity_id)
        table_name = DEDICATED_TYPE_RESOLVERS.get(entity_type)
        if table_name:
            return self._resolve_dedicated_entity(db, table_name, entity_id)
        return self._resolve_asset_entity(db, entity_id)

    @staticmethod
    def _resolve_dedicated_entity(
        db: Session, table_name: str, entity_id: str
    ) -> Optional[Dict[str, Any]]:
        """Resolve a dedicated-tier entity by querying its specific table."""
        try:
            if table_name == "data_products":
                from src.db_models.data_products import DataProductDb
                obj = db.query(DataProductDb).filter(DataProductDb.id == entity_id).first()
                if obj:
                    desc = None
                    if obj.description and hasattr(obj.description, "purpose"):
                        desc = obj.description.purpose
                    return {"name": getattr(obj, "name", None) or entity_id, "status": getattr(obj, "status", None), "description": desc}
            elif table_name == "data_domains":
                from src.db_models.data_domains import DataDomain
                obj = db.query(DataDomain).filter(DataDomain.id == entity_id).first()
                if obj:
                    return {"name": obj.name, "status": None, "description": obj.description}
            elif table_name == "data_contracts":
                from src.db_models.data_contracts import DataContractDb
                obj = db.query(DataContractDb).filter(DataContractDb.id == entity_id).first()
                if obj:
                    return {"name": getattr(obj, "name", None) or entity_id, "status": getattr(obj, "status", None), "description": getattr(obj, "description_purpose", None)}
            elif table_name == "teams":
                from src.db_models.teams import TeamDb
                obj = db.query(TeamDb).filter(TeamDb.id == entity_id).first()
                if obj:
                    return {"name": obj.name, "status": None, "description": getattr(obj, "description", None)}
            elif table_name == "projects":
                from src.db_models.projects import ProjectDb
                obj = db.query(ProjectDb).filter(ProjectDb.id == entity_id).first()
                if obj:
                    return {"name": obj.name, "status": getattr(obj, "status", None), "description": getattr(obj, "description", None)}
            elif table_name == "data_product_output_ports":
                from src.db_models.data_products import OutputPortDb
                obj = db.query(OutputPortDb).filter(OutputPortDb.id == entity_id).first()
                if obj:
                    return {"name": obj.name, "status": getattr(obj, "status", None), "description": getattr(obj, "description", None)}
        except Exception as e:
            logger.warning(f"Failed to resolve dedicated entity {table_name}:{entity_id}: {e}")
        return None

    @staticmethod
    def _resolve_asset_entity(
        db: Session, entity_id: str
    ) -> Optional[Dict[str, Any]]:
        """Resolve an asset-tier entity from the assets table."""
        try:
            from src.repositories.assets_repository import asset_repo
            try:
                key: Any = UUID(str(entity_id))
            except ValueError:
                return None  # asset ids are UUIDs
            obj = asset_repo.get(db, key)
            if obj:
                return {"name": obj.name, "status": obj.status, "description": obj.description}
        except Exception as e:
            logger.warning(f"Failed to resolve asset entity {entity_id}: {e}")
        return None

    def _get_icon_for_type(self, entity_type: str) -> Optional[str]:
        """Get the UI icon for an entity type from the ontology."""
        type_iri = self._normalize_entity_type(entity_type)
        et = self._osm.get_entity_type(type_iri)
        return et.ui_icon if et else None

    def get_entity_hierarchy(
        self,
        db: Session,
        entity_type: str,
        entity_id: str,
        max_depth: int = 5,
    ) -> Optional[InstanceHierarchyNode]:
        """Build a recursive hierarchy tree for a specific entity instance.

        Uses ontology-defined hierarchical relationships to find children.
        """
        info = self._resolve_entity(db, entity_type, entity_id)
        if not info:
            return None

        icon = self._get_icon_for_type(entity_type)

        root = InstanceHierarchyNode(
            entity_type=entity_type,
            entity_id=entity_id,
            name=info["name"],
            status=info.get("status"),
            icon=icon,
            description=info.get("description"),
        )

        visited: Set[tuple] = set()
        self._expand_children(db, root, current_depth=0, max_depth=max_depth, visited=visited)
        return root

    def _expand_children(
        self,
        db: Session,
        node: InstanceHierarchyNode,
        current_depth: int,
        max_depth: int,
        visited: Set[tuple],
    ) -> None:
        """Recursively expand children for a hierarchy node using ontology relationships."""
        if current_depth >= max_depth:
            return

        node_key = (node.entity_type, node.entity_id)
        if node_key in visited:
            return
        visited.add(node_key)

        type_iri = self._normalize_entity_type(node.entity_type)
        hier_rels = self._osm.get_hierarchy_relationships(type_iri)

        # For System, also check inverse relationships (assets belonging TO this system)
        inverse_rels = self._osm.get_hierarchy_relationships_inverse(type_iri)

        children: List[InstanceHierarchyNode] = []

        # Outgoing hierarchical relationships (e.g. DataProduct -> hasDataset -> Dataset)
        for rel_def in hier_rels:
            rel_name = rel_def.property_name
            child_rows = entity_relationship_repo.query_filtered(
                db,
                source_type=node.entity_type,
                source_id=node.entity_id,
                relationship_type=rel_name,
                limit=500,
            )
            for row in child_rows:
                if (row.target_type, row.target_id) in visited:
                    continue
                child_info = self._resolve_entity(db, row.target_type, row.target_id)
                if not child_info:
                    continue
                child_icon = self._get_icon_for_type(row.target_type)
                child_node = InstanceHierarchyNode(
                    entity_type=row.target_type,
                    entity_id=row.target_id,
                    name=child_info["name"],
                    status=child_info.get("status"),
                    icon=child_icon,
                    description=child_info.get("description"),
                    relationship_type=rel_name,
                    relationship_label=rel_def.label,
                )
                self._expand_children(db, child_node, current_depth + 1, max_depth, visited)
                children.append(child_node)

        # Incoming hierarchical relationships (e.g. System <- belongsToSystem <- Asset)
        for rel_def in inverse_rels:
            rel_name = rel_def.property_name
            child_rows = entity_relationship_repo.query_filtered(
                db,
                target_type=node.entity_type,
                target_id=node.entity_id,
                relationship_type=rel_name,
                limit=500,
            )
            for row in child_rows:
                if (row.source_type, row.source_id) in visited:
                    continue
                child_info = self._resolve_entity(db, row.source_type, row.source_id)
                if not child_info:
                    continue
                child_icon = self._get_icon_for_type(row.source_type)
                child_node = InstanceHierarchyNode(
                    entity_type=row.source_type,
                    entity_id=row.source_id,
                    name=child_info["name"],
                    status=child_info.get("status"),
                    icon=child_icon,
                    description=child_info.get("description"),
                    relationship_type=rel_name,
                    relationship_label=rel_def.inverse_label or rel_def.label,
                )
                self._expand_children(db, child_node, current_depth + 1, max_depth, visited)
                children.append(child_node)

        node.children = children
        node.child_count = len(children)

    def get_hierarchy_roots(
        self, db: Session, root_types: Optional[List[str]] = None
    ) -> List[HierarchyRootGroup]:
        """Return top-level entities grouped by type for the hierarchy browser.

        Default root types: System, DataDomain
        """
        if not root_types:
            root_types = ["System", "DataDomain"]

        groups: List[HierarchyRootGroup] = []

        for entity_type in root_types:
            icon = self._get_icon_for_type(entity_type)
            type_iri = self._normalize_entity_type(entity_type)
            et = self._osm.get_entity_type(type_iri)
            label = et.label if et else entity_type

            roots: List[InstanceHierarchyNode] = []

            if entity_type in DEDICATED_TYPE_RESOLVERS:
                roots = self._get_dedicated_roots(db, entity_type, icon)
            else:
                roots = self._get_asset_roots(db, entity_type, icon)

            groups.append(HierarchyRootGroup(
                entity_type=entity_type,
                label=label,
                icon=icon,
                roots=roots,
            ))

        return groups

    def _get_dedicated_roots(
        self, db: Session, entity_type: str, icon: Optional[str]
    ) -> List[InstanceHierarchyNode]:
        """Fetch all entities of a dedicated type as root nodes (without expanding children)."""
        roots: List[InstanceHierarchyNode] = []
        try:
            if entity_type == "DataDomain":
                from src.db_models.data_domains import DataDomain as DD
                objs = db.query(DD).order_by(DD.name).all()
                for obj in objs:
                    roots.append(InstanceHierarchyNode(
                        entity_type=entity_type,
                        entity_id=str(obj.id),
                        name=obj.name,
                        description=obj.description,
                        icon=icon,
                    ))
            elif entity_type == "DataProduct":
                from src.db_models.data_products import DataProductDb
                objs = db.query(DataProductDb).order_by(DataProductDb.name).all()
                for obj in objs:
                    desc = None
                    if obj.description and hasattr(obj.description, "purpose"):
                        desc = obj.description.purpose
                    roots.append(InstanceHierarchyNode(
                        entity_type=entity_type,
                        entity_id=str(obj.id),
                        name=obj.name or str(obj.id),
                        status=obj.status,
                        description=desc,
                        icon=icon,
                    ))
        except Exception as e:
            logger.warning(f"Failed to fetch dedicated roots for {entity_type}: {e}")
        return roots

    def _get_asset_roots(
        self, db: Session, entity_type: str, icon: Optional[str]
    ) -> List[InstanceHierarchyNode]:
        """Fetch all asset-tier entities of a given type as root nodes."""
        roots: List[InstanceHierarchyNode] = []
        try:
            from src.repositories.assets_repository import asset_type_repo, asset_repo
            from src.db_models.assets import AssetDb

            at = asset_type_repo.get_by_name(db, name=entity_type)
            if not at:
                return roots
            objs = (
                db.query(AssetDb)
                .filter(AssetDb.asset_type_id == at.id)
                .order_by(AssetDb.name)
                .all()
            )
            for obj in objs:
                roots.append(InstanceHierarchyNode(
                    entity_type=entity_type,
                    entity_id=str(obj.id),
                    name=obj.name,
                    status=obj.status,
                    description=obj.description,
                    icon=icon,
                ))
        except Exception as e:
            logger.warning(f"Failed to fetch asset roots for {entity_type}: {e}")
        return roots

    # ------------------------------------------------------------------
    # Business Lineage Graph
    # ------------------------------------------------------------------

    def get_business_lineage(
        self,
        db: Session,
        entity_type: str,
        entity_id: str,
        max_depth: int = 3,
        direction: Optional[str] = None,
    ) -> LineageGraph:
        """Lineage graph over stored and derived relationships.

        Stored ``entity_relationships`` rows are combined with links derived at
        query time (concepts, product ports, contract schema, physical-name
        binding — see ``model_lineage``). Direction follows the *flow*
        (business → platform, provider → consumer), not the stored edge
        direction: across layers the business-side end is upstream, within a
        layer ``REVERSED_FLOW_RELS`` decides (e.g. ``dependsOn`` points from
        consumer to provider).

        "Both" is the union of the upstream and the downstream chain — not an
        undirected walk, which would pull in siblings through shared nodes.

        Args:
            direction: None for both, "downstream" for impact analysis,
                       "upstream" for provenance.
        """
        graph = LineageGraph(
            center_entity_type=entity_type,
            center_entity_id=entity_id,
        )

        center_info = self._resolve_entity(db, entity_type, entity_id)
        if not center_info:
            return graph

        center_key = f"{entity_type}:{entity_id}"
        nodes: Dict[str, LineageGraphNode] = {
            center_key: self._make_lineage_node(db, entity_type, entity_id, center_info, is_center=True),
        }
        edges: Dict[tuple, LineageGraphEdge] = {}
        passes = [direction] if direction in ("upstream", "downstream") else ["upstream", "downstream"]
        leaves: Set[tuple] = set()
        truncated = False
        for pass_direction in passes:
            truncated |= self._walk_lineage(
                db, entity_type, entity_id, max_depth, pass_direction, nodes, edges, leaves,
            )
        self._attach_leaf_containers(db, leaves, nodes, edges)
        if truncated:
            logger.info(f"Business lineage for {center_key} truncated at {MAX_LINEAGE_NODES} nodes")

        graph.nodes = list(nodes.values())
        graph.edges = list(edges.values())
        graph.truncated = truncated
        return graph

    def _walk_lineage(
        self,
        db: Session,
        entity_type: str,
        entity_id: str,
        max_depth: int,
        direction: str,
        nodes: Dict[str, LineageGraphNode],
        edges: Dict[tuple, LineageGraphEdge],
        leaves: Set[tuple],
    ) -> bool:
        """One directional pass (0-1 BFS); adds to ``nodes`` / ``edges`` in place.

        Gap-fill neighbors are not walked further; they are collected in
        ``leaves`` so their containers can be attached afterwards.

        A node reached by going *up* containment (column → table) does not walk
        back down to its other children — those are siblings, not lineage.

        Returns True when the walk stopped at ``MAX_LINEAGE_NODES``.

        Containment links in ``ZERO_COST_RELS`` do not consume breadth and are
        followed in either direction, so a contract always comes with its
        schema and a column with its table.
        """
        show_hidden = entity_type in HIDDEN_LINEAGE_TYPES
        center_rank = LAYER_RANK.get(self._layer_for_type(entity_type))
        best_depth: Dict[str, int] = {f"{entity_type}:{entity_id}": 0}
        unresolvable: Set[str] = set()
        # (type, id, depth, reached_upward)
        queue: Deque[tuple] = deque([(entity_type, entity_id, 0, False)])

        while queue:
            cur_type, cur_id, depth, reached_upward = queue.popleft()
            cur_key = f"{cur_type}:{cur_id}"
            if depth > best_depth.get(cur_key, depth):
                continue  # stale entry, reached cheaper since

            for src_type, src_id, tgt_type, tgt_id, rel_type, derived in self._lineage_links(db, cur_type, cur_id):
                is_outgoing = (src_type == cur_type and src_id == cur_id)
                neighbor_type = tgt_type if is_outgoing else src_type
                neighbor_id = tgt_id if is_outgoing else src_id
                if neighbor_type in HIDDEN_LINEAGE_TYPES and not show_hidden:
                    continue

                forward = is_forward_flow(rel_type, self._layer_for_type(src_type), self._layer_for_type(tgt_type))
                zero_cost = rel_type in ZERO_COST_RELS
                # Containment is stored parent → child; outgoing means going down
                if zero_cost and is_outgoing and reached_upward:
                    continue
                gap_fill = False
                if not zero_cost:
                    neighbor_is_upstream = (forward != is_outgoing)
                    if neighbor_is_upstream != (direction == "upstream"):
                        # Wrong direction — unless the neighbor fills a layer the
                        # chain skipped (e.g. Product → Dataset skips Logical; the
                        # Dataset's contract belongs in between). Added as a leaf.
                        gap_fill = self._fills_layer_gap(center_rank, cur_type, neighbor_type)
                        if not gap_fill:
                            continue

                next_depth = depth + (0 if zero_cost else 1)
                neighbor_key = f"{neighbor_type}:{neighbor_id}"
                # Beyond the breadth budget only close edges between nodes already shown
                if next_depth > max_depth and neighbor_key not in nodes:
                    continue
                if neighbor_key in unresolvable:
                    continue
                if neighbor_key not in nodes:
                    if len(nodes) >= MAX_LINEAGE_NODES:
                        return True
                    n_info = self._resolve_entity(db, neighbor_type, neighbor_id)
                    if not n_info:
                        # Never emit an edge to a node that is not in the graph
                        unresolvable.add(neighbor_key)
                        continue
                    nodes[neighbor_key] = self._make_lineage_node(db, neighbor_type, neighbor_id, n_info)

                edge_key = (f"{src_type}:{src_id}", f"{tgt_type}:{tgt_id}", rel_type)
                if edge_key not in edges:
                    edges[edge_key] = LineageGraphEdge(
                        source=edge_key[0],
                        target=edge_key[1],
                        relationship_type=rel_type,
                        label=self._relationship_label(rel_type),
                        derived=derived,
                        reversed=not forward,
                    )

                if gap_fill:
                    leaves.add((neighbor_type, neighbor_id))
                    continue
                if next_depth <= max_depth and next_depth < best_depth.get(neighbor_key, max_depth + 1):
                    best_depth[neighbor_key] = next_depth
                    if zero_cost:
                        queue.appendleft((neighbor_type, neighbor_id, next_depth, not is_outgoing))
                    else:
                        queue.append((neighbor_type, neighbor_id, next_depth, False))
        return False

    def _attach_leaf_containers(
        self,
        db: Session,
        leaves: Set[tuple],
        nodes: Dict[str, LineageGraphNode],
        edges: Dict[tuple, LineageGraphEdge],
    ) -> None:
        """Give gap-fill leaves their containers (property → schema object → contract,
        column → table) so they nest as rows instead of floating as loose cards.

        Only parents are pulled in; children are linked only if already present.
        """
        stack = list(leaves)
        seen: Set[tuple] = set()
        while stack:
            cur_type, cur_id = stack.pop()
            if (cur_type, cur_id) in seen:
                continue
            seen.add((cur_type, cur_id))
            for src_type, src_id, tgt_type, tgt_id, rel_type, derived in self._lineage_links(db, cur_type, cur_id):
                if rel_type not in ZERO_COST_RELS:
                    continue
                cur_is_child = (tgt_type == cur_type and tgt_id == cur_id)
                other_type, other_id = (src_type, src_id) if cur_is_child else (tgt_type, tgt_id)
                other_key = f"{other_type}:{other_id}"
                if other_key not in nodes:
                    if not cur_is_child:
                        continue
                    info = self._resolve_entity(db, other_type, other_id)
                    if not info:
                        continue
                    nodes[other_key] = self._make_lineage_node(db, other_type, other_id, info)
                    stack.append((other_type, other_id))
                edge_key = (f"{src_type}:{src_id}", f"{tgt_type}:{tgt_id}", rel_type)
                if edge_key not in edges:
                    forward = is_forward_flow(rel_type, self._layer_for_type(src_type), self._layer_for_type(tgt_type))
                    edges[edge_key] = LineageGraphEdge(
                        source=edge_key[0],
                        target=edge_key[1],
                        relationship_type=rel_type,
                        label=self._relationship_label(rel_type),
                        derived=derived,
                        reversed=not forward,
                    )

    def _fills_layer_gap(self, center_rank: Optional[int], cur_type: str, neighbor_type: str) -> bool:
        """Neighbor's layer lies strictly between the center's and the current node's."""
        cur_rank = LAYER_RANK.get(self._layer_for_type(cur_type))
        n_rank = LAYER_RANK.get(self._layer_for_type(neighbor_type))
        if center_rank is None or cur_rank is None or n_rank is None:
            return False
        return min(center_rank, cur_rank) < n_rank < max(center_rank, cur_rank)

    def _lineage_links(self, db: Session, entity_type: str, entity_id: str) -> List[tuple]:
        """Stored + derived links touching an entity as (src_type, src_id, tgt_type, tgt_id, rel, derived)."""
        links: List[tuple] = []
        if entity_type not in SYNTHETIC_TYPES:
            for row in entity_relationship_repo.get_for_entity(db, entity_type=entity_type, entity_id=entity_id):
                links.append((row.source_type, row.source_id, row.target_type, row.target_id, row.relationship_type, False))
        for link in self._model_lineage.neighbors(db, entity_type, entity_id):
            links.append((link.source_type, link.source_id, link.target_type, link.target_id, link.relationship_type, True))
        return links

    def _relationship_label(self, relationship_type: str) -> str:
        if relationship_type in self._rel_label_cache:
            return self._rel_label_cache[relationship_type]
        label = REL_LABELS.get(relationship_type, relationship_type)
        try:
            from rdflib import URIRef, RDFS
            lv = self._osm._graph.value(URIRef(self._normalize_relationship_type(relationship_type)), RDFS.label)
            if lv:
                label = str(lv)
        except Exception:
            pass
        self._rel_label_cache[relationship_type] = label
        return label

    def _layer_for_type(self, entity_type: str) -> str:
        """Model layer from the ontology's ontos:modelLayer annotation (with fallbacks)."""
        if entity_type in SYNTHETIC_LAYERS:
            return SYNTHETIC_LAYERS[entity_type]
        if entity_type in self._layer_cache:
            return self._layer_cache[entity_type]
        layer = DEFAULT_LAYER
        try:
            from rdflib import URIRef
            lv = self._osm._graph.value(URIRef(self._normalize_entity_type(entity_type)), URIRef(f"{ONTOS_NS}modelLayer"))
            if lv and str(lv) in MODEL_LAYERS:
                layer = str(lv)
        except Exception:
            pass
        self._layer_cache[entity_type] = layer
        return layer

    def _make_lineage_node(
        self, db: Session, entity_type: str, entity_id: str, info: Dict[str, Any], is_center: bool = False,
    ) -> LineageGraphNode:
        context_id = info.get("context_id")
        if context_id is None and entity_type == "OutputPort":
            context_id = self._model_lineage.output_port_context(db, entity_id)
        return LineageGraphNode(
            id=f"{entity_type}:{entity_id}",
            entity_type=entity_type,
            entity_id=entity_id,
            name=info["name"],
            icon=self._get_icon_for_type(entity_type),
            status=info.get("status"),
            description=info.get("description"),
            is_center=is_center,
            layer=self._layer_for_type(entity_type),
            context_id=context_id,
        )

    # ------------------------------------------------------------------
    # Mapping
    # ------------------------------------------------------------------

    def _to_read(
        self,
        db_obj: EntityRelationshipDb,
        relationship_label: Optional[str] = None,
        db: Optional[Session] = None,
    ) -> EntityRelationshipRead:
        if not relationship_label:
            rel_iri = self._normalize_relationship_type(db_obj.relationship_type)
            try:
                from rdflib import URIRef, RDFS
                label_val = self._osm._graph.value(URIRef(rel_iri), RDFS.label)
                relationship_label = str(label_val) if label_val else db_obj.relationship_type
            except Exception:
                relationship_label = db_obj.relationship_type

        source_name: Optional[str] = None
        target_name: Optional[str] = None
        if db is not None:
            src_info = self._resolve_entity(db, db_obj.source_type, db_obj.source_id)
            if src_info:
                source_name = src_info["name"]
            tgt_info = self._resolve_entity(db, db_obj.target_type, db_obj.target_id)
            if tgt_info:
                target_name = tgt_info["name"]

        return EntityRelationshipRead(
            id=db_obj.id,
            source_type=db_obj.source_type,
            source_id=db_obj.source_id,
            target_type=db_obj.target_type,
            target_id=db_obj.target_id,
            relationship_type=db_obj.relationship_type,
            properties=db_obj.properties,
            created_by=db_obj.created_by,
            created_at=db_obj.created_at,
            relationship_label=relationship_label,
            source_name=source_name,
            target_name=target_name,
        )
