"""
Shared utilities for processing semantic links from ODCS authoritativeDefinitions.

This module provides consistent handling of semantic assignments across all ODCS ingestion
routes, ensuring that business semantics are properly converted from ODCS format to the
app's native semantic links system.
"""

from typing import List, Dict, Any, Optional, Tuple

from src.controller.semantic_links_manager import SemanticLinksManager
from src.models.semantic_links import EntitySemanticLinkCreate

from src.common.logging import get_logger
logger = get_logger(__name__)

# Constants for ODCS semantic processing
SEMANTIC_ASSIGNMENT_TYPE = "http://databricks.com/ontology/uc/semanticAssignment"


def _extract_url_and_type(auth_def: Any) -> Tuple[Optional[str], Optional[str]]:
    """Return (url, type) from either a dict or a pydantic model instance.

    This helper makes semantic processing resilient to different shapes
    (dicts from parsed JSON or objects from pydantic models).
    """
    if isinstance(auth_def, dict):
        return auth_def.get('url'), auth_def.get('type')

    url = getattr(auth_def, 'url', None)
    type_ = getattr(auth_def, 'type', None)
    return url, type_


def process_contract_semantic_links(
    semantic_manager: SemanticLinksManager,
    contract_id: str,
    authoritative_definitions: List[Dict[str, Any]],
    created_by: Optional[str] = None,
    commit: bool = True,
) -> int:
    """
    Process contract-level semantic assignments from authoritativeDefinitions.

    ``commit=False`` writes the links in the caller's transaction (``SemanticLinksManager.add``).

    Args:
        semantic_manager: SemanticLinksManager instance
        contract_id: Contract ID
        authoritative_definitions: List of authoritative definitions from ODCS
        created_by: User who created the semantic links

    Returns:
        Number of semantic links created
    """
    created_count = 0

    for auth_def in authoritative_definitions or []:
        url, type_ = _extract_url_and_type(auth_def)
        if type_ == SEMANTIC_ASSIGNMENT_TYPE and url:
            try:
                iri_tail = url.split('#')[-1].split('/')[-1]
                semantic_link = EntitySemanticLinkCreate(
                    entity_id=contract_id,
                    entity_type='data_contract',
                    iri=url,
                    label=iri_tail.replace('_', ' ') if iri_tail else None
                )
                semantic_manager.add(semantic_link, created_by=created_by, commit=commit)
                created_count += 1
                logger.debug(f"Created semantic link for contract {contract_id}: {url}")
            except Exception as e:
                logger.warning(f"Failed to create semantic link for contract {contract_id}, URL {url}: {e}")

    return created_count


def process_schema_semantic_links(
    semantic_manager: SemanticLinksManager,
    contract_id: str,
    schema_name: str,
    authoritative_definitions: List[Dict[str, Any]],
    created_by: Optional[str] = None
) -> int:
    """
    Process schema-level semantic assignments from authoritativeDefinitions.

    Args:
        semantic_manager: SemanticLinksManager instance
        contract_id: Contract ID
        schema_name: Schema name
        authoritative_definitions: List of authoritative definitions from ODCS
        created_by: User who created the semantic links

    Returns:
        Number of semantic links created
    """
    created_count = 0

    for auth_def in authoritative_definitions or []:
        url, type_ = _extract_url_and_type(auth_def)
        if type_ == SEMANTIC_ASSIGNMENT_TYPE and url:
            try:
                entity_id = f"{contract_id}#{schema_name}"
                iri_tail = url.split('#')[-1].split('/')[-1]
                semantic_link = EntitySemanticLinkCreate(
                    entity_id=entity_id,
                    entity_type='data_contract_schema',
                    iri=url,
                    label=iri_tail.replace('_', ' ') if iri_tail else None
                )
                semantic_manager.add(semantic_link, created_by=created_by)
                created_count += 1
                logger.debug(f"Created semantic link for schema {entity_id}: {url}")
            except Exception as e:
                logger.warning(f"Failed to create semantic link for schema {contract_id}#{schema_name}, URL {url}: {e}")

    return created_count


def process_property_semantic_links(
    semantic_manager: SemanticLinksManager,
    contract_id: str,
    schema_name: str,
    property_name: str,
    authoritative_definitions: List[Dict[str, Any]],
    created_by: Optional[str] = None
) -> int:
    """
    Process property-level semantic assignments from authoritativeDefinitions.

    Args:
        semantic_manager: SemanticLinksManager instance
        contract_id: Contract ID
        schema_name: Schema name
        property_name: Property name
        authoritative_definitions: List of authoritative definitions from ODCS
        created_by: User who created the semantic links

    Returns:
        Number of semantic links created
    """
    created_count = 0

    for auth_def in authoritative_definitions or []:
        url, type_ = _extract_url_and_type(auth_def)
        if type_ == SEMANTIC_ASSIGNMENT_TYPE and url:
            try:
                entity_id = f"{contract_id}#{schema_name}#{property_name}"
                iri_tail = url.split('#')[-1].split('/')[-1]
                semantic_link = EntitySemanticLinkCreate(
                    entity_id=entity_id,
                    entity_type='data_contract_property',
                    iri=url,
                    label=iri_tail.replace('_', ' ') if iri_tail else None
                )
                semantic_manager.add(semantic_link, created_by=created_by)
                created_count += 1
                logger.debug(f"Created semantic link for property {entity_id}: {url}")
            except Exception as e:
                logger.warning(f"Failed to create semantic link for property {contract_id}#{schema_name}#{property_name}, URL {url}: {e}")

    return created_count


def process_all_semantic_links_from_odcs(
    semantic_manager: SemanticLinksManager,
    contract_id: str,
    parsed_odcs: Dict[str, Any],
    created_by: Optional[str] = None
) -> int:
    """
    Process all semantic assignments from a parsed ODCS contract.

    This function handles contract-level, schema-level, and property-level semantic
    assignments in a single call, ensuring consistency across all ODCS ingestion routes.

    Args:
        semantic_manager: SemanticLinksManager instance
        contract_id: Contract ID
        parsed_odcs: Parsed ODCS contract data
        created_by: User who created the semantic links

    Returns:
        Total number of semantic links created
    """
    total_created = 0

    # Process contract-level semantic assignments
    contract_auth_defs = parsed_odcs.get('authoritativeDefinitions', [])
    total_created += process_contract_semantic_links(
        semantic_manager, contract_id, contract_auth_defs, created_by
    )

    # Process schema-level and property-level semantic assignments
    schema_data = parsed_odcs.get('schema', [])
    if isinstance(schema_data, list):
        for schema_obj_data in schema_data:
            if not isinstance(schema_obj_data, dict):
                continue

            schema_name = schema_obj_data.get('name', 'table')

            # Process schema-level semantic assignments
            schema_auth_defs = schema_obj_data.get('authoritativeDefinitions', [])
            total_created += process_schema_semantic_links(
                semantic_manager, contract_id, schema_name, schema_auth_defs, created_by
            )

            # Process property-level semantic assignments
            properties = schema_obj_data.get('properties', [])
            if isinstance(properties, list):
                for prop_data in properties:
                    if not isinstance(prop_data, dict):
                        continue

                    property_name = prop_data.get('name', 'column')
                    prop_auth_defs = prop_data.get('authoritativeDefinitions', [])
                    total_created += process_property_semantic_links(
                        semantic_manager, contract_id, schema_name, property_name, prop_auth_defs, created_by
                    )

    if total_created > 0:
        logger.info(f"Created {total_created} semantic links for contract {contract_id}")

    return total_created


def get_semantic_assignment_type() -> str:
    """
    Get the standardized semantic assignment type constant.

    Returns:
        The ODCS type used to identify semantic assignments that should be
        converted to app-native semantic links.
    """
    return SEMANTIC_ASSIGNMENT_TYPE