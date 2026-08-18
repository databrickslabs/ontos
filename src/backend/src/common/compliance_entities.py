"""Entity Iteration Framework for Compliance Checks.

This module provides a framework for loading and filtering entities
(catalogs, schemas, tables, data products, etc.) for compliance evaluation.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any, Dict, Iterator, List, Optional, Protocol
from sqlalchemy.orm import Session

from src.common.logging import get_logger
from src.common.compliance_dsl import Lexer, Parser, Evaluator

logger = get_logger(__name__)


@dataclass
class EntityFilter:
    """Filter criteria for entities."""
    entity_types: List[str]  # Types to include (e.g., ['table', 'view'])
    where_clause_ast: Optional[Any] = None  # Parsed WHERE condition AST


class EntityLoader(ABC):
    """Base class for entity loaders."""

    @abstractmethod
    def get_supported_types(self) -> List[str]:
        """Return list of entity types this loader supports."""
        pass

    @abstractmethod
    def load_entities(
        self,
        entity_types: List[str],
        batch_size: int = 100
    ) -> Iterator[Dict[str, Any]]:
        """Load entities of specified types.

        Args:
            entity_types: List of entity types to load
            batch_size: Number of entities per batch

        Yields:
            Entity dictionaries
        """
        pass


class UnityCatalogLoader(EntityLoader):
    """Load entities from Unity Catalog."""

    def __init__(self, workspace_client):
        self.ws = workspace_client

    def get_supported_types(self) -> List[str]:
        return ['catalog', 'schema', 'table', 'view', 'function', 'volume']

    def load_entities(
        self,
        entity_types: List[str],
        batch_size: int = 100
    ) -> Iterator[Dict[str, Any]]:
        """Load UC entities."""
        try:
            # Load catalogs
            if 'catalog' in entity_types:
                for catalog in self.ws.catalogs.list():
                    yield {
                        'type': 'catalog',
                        'name': catalog.name,
                        'id': catalog.name,
                        'full_name': catalog.name,
                        'owner': getattr(catalog, 'owner', None),
                        'comment': getattr(catalog, 'comment', None),
                        'created_at': getattr(catalog, 'created_at', None),
                        'updated_at': getattr(catalog, 'updated_at', None),
                    }

            # Load schemas
            if 'schema' in entity_types:
                for catalog in self.ws.catalogs.list():
                    try:
                        for schema in self.ws.schemas.list(catalog_name=catalog.name):
                            yield {
                                'type': 'schema',
                                'name': schema.name,
                                'id': f"{catalog.name}.{schema.name}",
                                'full_name': schema.full_name or f"{catalog.name}.{schema.name}",
                                'catalog': catalog.name,
                                'owner': getattr(schema, 'owner', None),
                                'comment': getattr(schema, 'comment', None),
                                'created_at': getattr(schema, 'created_at', None),
                                'updated_at': getattr(schema, 'updated_at', None),
                            }
                    except Exception:
                        logger.exception(f"Failed to list schemas for catalog {catalog.name}")

            # Load tables and views
            if 'table' in entity_types or 'view' in entity_types:
                for catalog in self.ws.catalogs.list():
                    try:
                        for schema in self.ws.schemas.list(catalog_name=catalog.name):
                            try:
                                for table in self.ws.tables.list(
                                    catalog_name=catalog.name,
                                    schema_name=schema.name
                                ):
                                    table_type_raw = getattr(table, 'table_type', 'TABLE')
                                    entity_type = 'view' if table_type_raw == 'VIEW' else 'table'

                                    if entity_type not in entity_types:
                                        continue

                                    yield {
                                        'type': entity_type,
                                        'name': table.name,
                                        'id': getattr(table, 'full_name', f"{catalog.name}.{schema.name}.{table.name}"),
                                        'full_name': getattr(table, 'full_name', f"{catalog.name}.{schema.name}.{table.name}"),
                                        'catalog': catalog.name,
                                        'schema': schema.name,
                                        'table_type': table_type_raw,
                                        'owner': getattr(table, 'owner', None),
                                        'comment': getattr(table, 'comment', None),
                                        'created_at': getattr(table, 'created_at', None),
                                        'updated_at': getattr(table, 'updated_at', None),
                                        'storage_location': getattr(table, 'storage_location', None),
                                    }
                            except Exception:
                                logger.exception(f"Failed to list tables for schema {catalog.name}.{schema.name}")
                    except Exception:
                        logger.exception(f"Failed to list schemas for catalog {catalog.name}")

            # Load functions
            if 'function' in entity_types:
                for catalog in self.ws.catalogs.list():
                    try:
                        for schema in self.ws.schemas.list(catalog_name=catalog.name):
                            try:
                                for function in self.ws.functions.list(
                                    catalog_name=catalog.name,
                                    schema_name=schema.name
                                ):
                                    yield {
                                        'type': 'function',
                                        'name': function.name,
                                        'id': getattr(function, 'full_name', f"{catalog.name}.{schema.name}.{function.name}"),
                                        'full_name': getattr(function, 'full_name', f"{catalog.name}.{schema.name}.{function.name}"),
                                        'catalog': catalog.name,
                                        'schema': schema.name,
                                        'owner': getattr(function, 'owner', None),
                                        'comment': getattr(function, 'comment', None),
                                        'created_at': getattr(function, 'created_at', None),
                                        'updated_at': getattr(function, 'updated_at', None),
                                    }
                            except Exception:
                                logger.exception(f"Failed to list functions for schema {catalog.name}.{schema.name}")
                    except Exception:
                        logger.exception(f"Failed to list schemas for catalog {catalog.name}")

            # Load volumes
            if 'volume' in entity_types:
                for catalog in self.ws.catalogs.list():
                    try:
                        for schema in self.ws.schemas.list(catalog_name=catalog.name):
                            try:
                                for volume in self.ws.volumes.list(
                                    catalog_name=catalog.name,
                                    schema_name=schema.name
                                ):
                                    yield {
                                        'type': 'volume',
                                        'name': volume.name,
                                        'id': getattr(volume, 'full_name', f"{catalog.name}.{schema.name}.{volume.name}"),
                                        'full_name': getattr(volume, 'full_name', f"{catalog.name}.{schema.name}.{volume.name}"),
                                        'catalog': catalog.name,
                                        'schema': schema.name,
                                        'owner': getattr(volume, 'owner', None),
                                        'comment': getattr(volume, 'comment', None),
                                        'created_at': getattr(volume, 'created_at', None),
                                        'updated_at': getattr(volume, 'updated_at', None),
                                        'storage_location': getattr(volume, 'storage_location', None),
                                    }
                            except Exception:
                                logger.exception(f"Failed to list volumes for schema {catalog.name}.{schema.name}")
                    except Exception:
                        logger.exception(f"Failed to list schemas for catalog {catalog.name}")

        except Exception:
            logger.exception("Failed to load UC entities")


class AppEntityLoader(EntityLoader):
    """Load entities from application database."""

    def __init__(self, db: Session):
        self.db = db

    def get_supported_types(self) -> List[str]:
        return [
            'data_product',
            'data_contract',
            'domain',
            'glossary_term',
            'review',
        ]

    def load_entities(
        self,
        entity_types: List[str],
        batch_size: int = 100
    ) -> Iterator[Dict[str, Any]]:
        """Load app entities from database.

        NOTE: repositories expose get_multi() (CRUDBase), not list(); the Db
        models carry owner_team_id/domain_id rather than owner/domain/tags
        attributes. Each entity type loads in its own try block so a failure
        in one type cannot silently suppress every other type.
        """
        # Data Products
        if 'data_product' in entity_types:
            try:
                from src.repositories.data_products_repository import data_product_repo
                from src.repositories.entity_domain_association_repository import entity_domain_repo
                # is_admin: the products repo is fail-closed per caller scope;
                # compliance evaluates system-wide and its route is already
                # permission-checked, so it must see every product.
                products = data_product_repo.get_multi(self.db, limit=1000, is_admin=True)
                # Domain moved to the entity_domain_associations junction; batch-load the
                # primary domain name per product (the legacy `domain` column was dropped).
                domains_map = entity_domain_repo.get_domains_for_entities(
                    self.db, entity_type="data_product", entity_ids=[str(p.id) for p in products]
                ) if products else {}
                for product in products:
                    assigned = domains_map.get(str(product.id), [])
                    primary_domain = next((a.domain_name for a in assigned if a.is_primary), None)
                    yield {
                        'type': 'data_product',
                        'id': product.id,
                        'name': product.name,
                        'description': getattr(product, 'description_purpose', None)
                                       or getattr(product, 'description', None),
                        'domain': primary_domain,
                        'status': product.status,
                        'version': getattr(product, 'version', None),
                        'owner': getattr(product, 'owner_team_id', None),
                        'tags': {},
                        'created_at': getattr(product, 'created_at', None),
                        'updated_at': getattr(product, 'updated_at', None),
                    }
            except Exception:
                logger.exception("Failed to load data products for compliance")

        # Data Contracts
        if 'data_contract' in entity_types:
            try:
                from src.repositories.data_contracts_repository import data_contract_repo
                for contract in data_contract_repo.get_multi(self.db, limit=1000):
                    yield {
                        'type': 'data_contract',
                        'id': contract.id,
                        'name': contract.name,
                        'description': getattr(contract, 'description_purpose', None),
                        'status': contract.status,
                        'version': getattr(contract, 'version', None),
                        'owner': getattr(contract, 'owner_team_id', None),
                        'domain': getattr(contract, 'domain_id', None),
                        'tags': {},
                        'created_at': getattr(contract, 'created_at', None),
                        'updated_at': getattr(contract, 'updated_at', None),
                    }
            except Exception:
                logger.exception("Failed to load data contracts for compliance")

        # Domains
        if 'domain' in entity_types:
            try:
                from src.repositories.data_domain_repository import data_domain_repo
                for domain in data_domain_repo.get_multi(self.db, limit=1000):
                    yield {
                        'type': 'domain',
                        'id': domain.id,
                        'name': domain.name,
                        'description': getattr(domain, 'description', None),
                        'owner': getattr(domain, 'owner_team_id', None),
                        'tags': {},
                        'created_at': getattr(domain, 'created_at', None),
                        'updated_at': getattr(domain, 'updated_at', None),
                    }
            except Exception:
                logger.exception("Failed to load domains for compliance")

        # Glossary Terms - Now stored as RDF concepts in KnowledgeCollections
        # Compliance checks for glossary terms should query the semantic models manager
        # TODO: Implement compliance entity fetching from RDF-based knowledge collections
        # if 'glossary_term' in entity_types:
        #     # Glossary terms are now managed via SemanticModelsManager as OntologyConcepts
        #     pass

        # Reviews
        if 'review' in entity_types:
            try:
                from src.repositories.data_asset_reviews_repository import data_asset_review_repo
                for review in data_asset_review_repo.get_multi(self.db, limit=1000):
                    yield {
                        'type': 'review',
                        'id': review.id,
                        'asset_id': getattr(review, 'asset_id', None),
                        'asset_type': getattr(review, 'asset_type', None),
                        'status': review.status,
                        'reviewer': getattr(review, 'reviewer', None),
                        'requester': getattr(review, 'requester', None),
                        'created_at': getattr(review, 'created_at', None),
                        'updated_at': getattr(review, 'updated_at', None),
                    }
            except Exception:
                logger.exception("Failed to load reviews for compliance")


class EntityIterator:
    """Iterate over entities with filtering."""

    def __init__(self, loaders: List[EntityLoader]):
        self.loaders = loaders

    def iterate(
        self,
        entity_filter: EntityFilter,
        limit: Optional[int] = None,
        batch_size: int = 100
    ) -> Iterator[Dict[str, Any]]:
        """Iterate over filtered entities.

        Args:
            entity_filter: Filter criteria
            limit: Maximum number of entities to return
            batch_size: Batch size for loading

        Yields:
            Filtered entity dictionaries
        """
        count = 0

        for loader in self.loaders:
            # Check if loader supports any of the requested types
            supported = loader.get_supported_types()
            requested = [t for t in entity_filter.entity_types if t in supported]

            if not requested:
                continue

            # Load entities
            for entity in loader.load_entities(requested, batch_size):
                # Apply WHERE filter if present
                if entity_filter.where_clause_ast:
                    try:
                        evaluator = Evaluator(entity)
                        if not evaluator.evaluate(entity_filter.where_clause_ast):
                            continue
                    except Exception:
                        logger.exception(f"Failed to evaluate WHERE clause for entity {entity.get('id')}")
                        continue

                yield entity
                count += 1

                if limit and count >= limit:
                    return


def create_entity_iterator(
    db: Optional[Session] = None,
    workspace_client: Optional[Any] = None
) -> EntityIterator:
    """Create an entity iterator with standard loaders.

    Args:
        db: Database session for app entities
        workspace_client: Databricks workspace client for UC entities

    Returns:
        Configured EntityIterator
    """
    loaders = []

    if workspace_client:
        loaders.append(UnityCatalogLoader(workspace_client))

    if db:
        loaders.append(AppEntityLoader(db))

    return EntityIterator(loaders)


def parse_entity_filter(rule: str) -> EntityFilter:
    """Parse entity filter from DSL rule.

    Args:
        rule: DSL rule string with MATCH and optional WHERE clauses

    Returns:
        EntityFilter object

    Example:
        >>> rule = "MATCH (obj:Object) WHERE obj.type IN ['table', 'view']"
        >>> filter = parse_entity_filter(rule)
    """
    from src.common.compliance_dsl import parse_rule

    parsed = parse_rule(rule)

    # Extract entity types
    entity_types = []
    match_type = parsed.get('match_type')
    if match_type:
        # Generic type 'Object' means all types
        if match_type.lower() == 'object':
            entity_types = ['catalog', 'schema', 'table', 'view', 'function', 'volume',
                           'data_product', 'data_contract', 'domain', 'glossary_term']
        else:
            entity_types = [match_type.lower()]

    # If WHERE clause contains obj.type IN [...], extract specific types
    where_clause = parsed.get('where_clause')
    if where_clause:
        # Try to extract type filter from WHERE clause
        # This is a simplified extraction - in practice you might want to
        # evaluate the WHERE clause more intelligently
        pass

    return EntityFilter(
        entity_types=entity_types,
        where_clause_ast=where_clause
    )
