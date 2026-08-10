from typing import List, Optional, Union, TYPE_CHECKING, Dict
from uuid import UUID
from sqlalchemy.orm import Session
from sqlalchemy import text
import re

from src.db_models.semantic_links import EntitySemanticLinkDb
from src.models.semantic_links import EntitySemanticLink, EntitySemanticLinkCreate, MappingStatus
from src.repositories.semantic_links_repository import entity_semantic_links_repo
from src.common.logging import get_logger
from src.controller.change_log_manager import change_log_manager

if TYPE_CHECKING:
    from src.controller.semantic_models_manager import SemanticModelsManager

logger = get_logger(__name__)

class SemanticLinksManager:
    def __init__(self, db: Session, semantic_models_manager: Optional['SemanticModelsManager'] = None):
        self._db = db
        self._semantic_models_manager = semantic_models_manager

    def _resolve_entity_name(self, entity_id: str, entity_type: str) -> Optional[str]:
        """Resolve the readable name for an entity based on its type and ID."""
        try:
            if entity_type == "data_domain":
                result = self._db.execute(
                    text("SELECT name FROM data_domains WHERE id = :entity_id"),
                    {"entity_id": entity_id}
                ).fetchone()
                return result[0] if result else None

            elif entity_type == "data_product":
                result = self._db.execute(
                    text("SELECT title FROM data_product_info WHERE data_product_id = :entity_id"),
                    {"entity_id": entity_id}
                ).fetchone()
                return result[0] if result else None

            elif entity_type == "data_contract":
                result = self._db.execute(
                    text("SELECT name FROM data_contracts WHERE id = :entity_id"),
                    {"entity_id": entity_id}
                ).fetchone()
                return result[0] if result else None

            elif entity_type in ("dataset", "asset"):
                result = self._db.execute(
                    text("SELECT name FROM assets WHERE id = :entity_id"),
                    {"entity_id": entity_id}
                ).fetchone()
                return result[0] if result else None

            elif entity_type == "uc_catalog":
                # entity_id is catalog name; use as display name
                return entity_id

            elif entity_type == "uc_schema":
                # entity_id is catalog.schema; use as display name
                return entity_id

            elif entity_type == "uc_table":
                # entity_id is catalog.schema.table; use as display name
                return entity_id

            elif entity_type == "uc_column":
                # entity_id is catalog.schema.table.column; use as display name
                return entity_id

            elif entity_type == "data_contract_schema":
                # entity_id is contractId#schemaName
                parts = entity_id.split("#", 1)
                if len(parts) >= 2:
                    contract_id, schema_name = parts[0], parts[1]
                    result = self._db.execute(
                        text("SELECT name FROM data_contracts WHERE id = :cid"),
                        {"cid": contract_id}
                    ).fetchone()
                    contract_name = result[0] if result else contract_id
                    return f"{contract_name}#{schema_name}"
                return entity_id

            elif entity_type == "data_contract_property":
                # entity_id is contractId#schemaName#propertyName
                parts = entity_id.split("#", 2)
                if len(parts) >= 3:
                    contract_id, schema_name, property_name = parts[0], parts[1], parts[2]
                    result = self._db.execute(
                        text("SELECT name FROM data_contracts WHERE id = :cid"),
                        {"cid": contract_id}
                    ).fetchone()
                    contract_name = result[0] if result else contract_id
                    return f"{contract_name}#{schema_name}.{property_name}"
                return entity_id

        except Exception as e:
            logger.warning(f"Failed to resolve entity name for {entity_type}:{entity_id}: {e}")

        return None

    def _to_api(self, db_obj: EntitySemanticLinkDb, parent_entity_id: Optional[str] = None) -> EntitySemanticLink:
        label = db_obj.label
        if not label:
            # Derive concept label from IRI local name (fragment or last path segment)
            iri = db_obj.iri or ''
            tail = iri.split('#')[-1].split('/')[-1]
            label = tail.replace('_', ' ') if tail else None

        return EntitySemanticLink(
            id=str(db_obj.id),
            entity_id=db_obj.entity_id,
            entity_type=db_obj.entity_type,  # type: ignore
            iri=db_obj.iri,
            label=label,
            parent_entity_id=parent_entity_id,
        )

    def _compute_nesting_for_links(self, links: List[EntitySemanticLink]) -> None:
        """Compute parent_entity_id for nestable links (contract-schema-property chain).

        Modifies links in-place. For data_contract_schema and data_contract_property links,
        sets parent_entity_id to point to their parent data_contract link if present.

        Nesting logic:
        - data_contract_schema#{contractId} links are nested under the data_contract link
          with entity_id={contractId}.
        - data_contract_property#{contractId}#{schemaName}#{propertyName} links are nested
          under their parent data_contract_schema link.
        - All other links stay at top level (parent_entity_id remains None).

        This is a O(n) algorithm over the concept's own link set; no extra DB queries.
        """
        # Build a map of entity_id -> link for quick lookup
        by_entity_id: Dict[str, EntitySemanticLink] = {}
        for link in links:
            by_entity_id[link.entity_id] = link

        # Process each link to find its parent (if any)
        for link in links:
            if link.entity_type == 'data_contract_schema':
                # Extract contractId from entity_id format: {contractId}#{schemaName}
                parts = link.entity_id.split('#', 1)
                if len(parts) >= 1:
                    contract_id = parts[0]
                    # Look for a data_contract link with this contract_id
                    if contract_id in by_entity_id and by_entity_id[contract_id].entity_type == 'data_contract':
                        link.parent_entity_id = contract_id

            elif link.entity_type == 'data_contract_property':
                # Extract schemaName from entity_id format: {contractId}#{schemaName}#{propertyName}
                parts = link.entity_id.split('#', 2)
                if len(parts) >= 2:
                    schema_entity_id = f"{parts[0]}#{parts[1]}"  # {contractId}#{schemaName}
                    # Look for a data_contract_schema link with this entity_id
                    if schema_entity_id in by_entity_id and by_entity_id[schema_entity_id].entity_type == 'data_contract_schema':
                        link.parent_entity_id = schema_entity_id

    def list_for_entity(self, entity_id: str, entity_type: str) -> List[EntitySemanticLink]:
        items = entity_semantic_links_repo.list_for_entity(self._db, entity_id, entity_type)
        results = [self._to_api(it) for it in items]
        self._compute_nesting_for_links(results)
        return results

    def list_for_iri(self, iri: str) -> List[EntitySemanticLink]:
        """Get all entities linked to an IRI, including both explicit links and inferred type relationships.

        For physical assets linked through data contracts or products, parent_entity_id is set to
        enable frontend nesting (concept -> contract -> asset in a visual hierarchy).
        Only contract-structured nesting is currently implemented (safe, deterministic);
        fuzzy FQN->product matching is deferred (uncertain and risky).
        """
        # Get explicit links from database
        items = entity_semantic_links_repo.list_for_iri(self._db, iri)
        results = [self._to_api(it) for it in items]

        # Add inferred links from RDF graph (entities with rdf:type matching this IRI)
        if self._semantic_models_manager:
            inferred = self._get_inferred_links_from_graph(iri)
            results.extend(inferred)

        # Compute nesting relationships for the concept's links
        self._compute_nesting_for_links(results)

        return results

    def mapping_status_for_iris(self, iris: List[str]) -> Dict[str, MappingStatus]:
        """Get mapping status for a batch of IRIs.

        Returns a dict mapping each IRI to its layer status (asset/product/contract).
        Only uses stored links (not inferred graph links) for efficiency in batch queries.

        Args:
            iris: List of IRI strings to query

        Returns:
            Dict[iri, MappingStatus] where MappingStatus indicates linked layers.
            IRIs with no links are included with all flags false.
        """
        # Entity types that belong to each layer
        physical_layer_types = {'asset', 'uc_catalog', 'uc_schema', 'uc_table', 'uc_column'}
        product_layer_types = {'data_product'}
        contract_layer_types = {'data_contract', 'data_contract_schema', 'data_contract_property'}

        # Initialize all IRIs with false status
        statuses: Dict[str, MappingStatus] = {
            iri: MappingStatus(asset=False, product=False, contract=False)
            for iri in iris
        }

        if not iris:
            return statuses

        # Batch query for all links matching these IRIs
        links = entity_semantic_links_repo.list_for_iris(self._db, iris)

        # Group by IRI and update status flags
        for link in links:
            if link.iri not in statuses:
                # IRI not requested; skip it
                continue

            if link.entity_type in physical_layer_types:
                statuses[link.iri].asset = True
            elif link.entity_type in product_layer_types:
                statuses[link.iri].product = True
            elif link.entity_type in contract_layer_types:
                statuses[link.iri].contract = True

        return statuses

    def _get_inferred_links_from_graph(self, iri: str) -> List[EntitySemanticLink]:
        """Query RDF graph for entities that have rdf:type matching the given IRI."""
        results = []

        try:
            # SPARQL query to find all subjects with this type
            query = f"""
            SELECT ?subject ?label WHERE {{
                ?subject a <{iri}> .
                OPTIONAL {{ ?subject <http://www.w3.org/2000/01/rdf-schema#label> ?label }}
            }}
            """

            sparql_results = self._semantic_models_manager.query(query)

            # Parse results and extract entity info from urn:ontos URIs
            for row in sparql_results:
                subject_uri = str(row.get('subject', ''))
                label = str(row.get('label', '')) if row.get('label') else None

                # Parse urn:ontos:{entity_type}:{entity_id} pattern
                match = re.match(r'^urn:ontos:([^:]+):(.+)$', subject_uri)
                if match:
                    entity_type = match.group(1)
                    entity_id = match.group(2)

                    # Resolve entity name if label not available
                    if not label:
                        label = self._resolve_entity_name(entity_id, entity_type)

                    # Create a pseudo-link object (no ID since it's inferred, not stored)
                    results.append(EntitySemanticLink(
                        id=f"inferred:{entity_type}:{entity_id}:{iri}",  # Synthetic ID
                        entity_id=entity_id,
                        entity_type=entity_type,  # type: ignore
                        iri=iri,
                        label=label,
                    ))
                    logger.debug(f"Inferred link: {entity_type}:{entity_id} -> {iri}")

        except Exception as e:
            logger.warning(f"Failed to get inferred links from graph for {iri}: {e}")

        return results

    def _link_exists(self, entity_id: str, entity_type: str, iri: str) -> bool:
        """Check if a semantic link already exists for this entity/IRI combination"""
        existing = entity_semantic_links_repo.get_by_entity_and_iri(self._db, entity_id, entity_type, iri)
        return existing is not None

    def add(self, payload: EntitySemanticLinkCreate, created_by: str | None) -> EntitySemanticLink:
        # Check if link already exists
        if self._link_exists(payload.entity_id, payload.entity_type, payload.iri):
            # Return existing link instead of creating a duplicate
            existing = entity_semantic_links_repo.get_by_entity_and_iri(
                self._db, payload.entity_id, payload.entity_type, payload.iri
            )
            logger.info(f"Semantic link already exists for {payload.entity_type}:{payload.entity_id} -> {payload.iri}")
            return self._to_api(existing)
        
        # Create new link
        db_obj = entity_semantic_links_repo.create(self._db, obj_in=payload)
        if created_by:
            db_obj.created_by = created_by
            self._db.add(db_obj)
        self._db.commit()
        self._db.refresh(db_obj)
        
        # Incrementally update the in-memory RDF graph via the shared manager on app.state
        try:
            from fastapi import Request
            # Access global app.state manager through SQLAlchemy session bind info when available
            # Fallback: attempt to import a locator util
            manager = None
            try:
                # Preferred path: retrieve from a globally stored application reference
                from src.common.app_state import get_app_state_manager
                manager = get_app_state_manager('semantic_models_manager')
            except Exception:
                manager = None
            if manager is not None:
                manager.add_entity_semantic_link_to_graph(payload.entity_type, payload.entity_id, payload.iri, created_by=created_by)
                # The new triple changes which entities resolve to a concept,
                # so any cached concept/property/stat snapshot is now stale.
                manager._invalidate_cache()
            else:
                # As a safe fallback, perform a lightweight rebuild using a temp instance
                from src.controller.semantic_models_manager import SemanticModelsManager
                SemanticModelsManager(db=self._db).on_models_changed()
        except Exception as e:
            logger.warning(f"Failed to update KG after link add: {e}")
        
        # Change log entry for semantic link addition
        try:
            change_log_manager.log_change_with_details(
                self._db,
                entity_type=payload.entity_type,
                entity_id=payload.entity_id,
                action="SEMANTIC_LINK_ADD",
                username=created_by,
                details={
                    "iri": payload.iri,
                    "link_id": str(db_obj.id),
                },
            )
        except Exception as log_err:
            logger.warning(f"Failed to log change for semantic link add: {log_err}")
        return self._to_api(db_obj)

    def remove(self, link_id: Union[str, UUID], removed_by: Optional[str] = None) -> bool:
        removed = entity_semantic_links_repo.remove(self._db, id=link_id)
        try:
            manager = None
            try:
                from src.common.app_state import get_app_state_manager
                manager = get_app_state_manager('semantic_models_manager')
            except Exception:
                manager = None
            if removed and manager is not None:
                manager.remove_entity_semantic_link_from_graph(removed.entity_type, removed.entity_id, removed.iri)
                # Mirror of the add path: the removed triple invalidates
                # cached concepts/properties/stats and the inferred-link cache.
                manager._invalidate_cache()
            else:
                from src.controller.semantic_models_manager import SemanticModelsManager
                SemanticModelsManager(db=self._db).on_models_changed()
        except Exception as e:
            logger.warning(f"Failed to update KG after link removal: {e}")
        
        # Change log entry for semantic link removal
        try:
            if removed is not None:
                change_log_manager.log_change_with_details(
                    self._db,
                    entity_type=removed.entity_type,
                    entity_id=removed.entity_id,
                    action="SEMANTIC_LINK_REMOVE",
                    username=removed_by,
                    details={
                        "iri": removed.iri,
                        "link_id": str(link_id),
                    },
                )
        except Exception as log_err:
            logger.warning(f"Failed to log change for semantic link removal: {log_err}")
        return removed is not None


