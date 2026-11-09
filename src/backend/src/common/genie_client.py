"""
Genie Spaces Client

This module provides utility functions for integrating with Databricks Genie Spaces API.
Handles space creation, dataset collection, and metadata formatting.
"""

import json

from databricks.sdk import WorkspaceClient
from typing import List, Dict, Optional, Any
from sqlalchemy.orm import Session

from src.common.logging import get_logger

logger = get_logger(__name__)


async def create_genie_space(
    ws_client: WorkspaceClient,
    name: str,
    datasets: List[str],
    description: Optional[str] = None,
    instructions: Optional[str] = None,
    warehouse_id: Optional[str] = None
) -> Dict[str, Any]:
    """
    Create a Genie Space using Databricks API.

    Args:
        ws_client: Databricks workspace client
        name: Space display name
        datasets: List of catalog.schema.table identifiers
        description: Optional space description
        instructions: Optional context/instructions (metadata)
        warehouse_id: SQL warehouse backing the space; falls back to
            settings.DATABRICKS_WAREHOUSE_ID (required by the API)

    Returns:
        Dict with space_id, space_url, status

    Raises:
        Exception: On API failure
    """
    try:
        # API Reference: https://docs.databricks.com/api/workspace/genie/createspace
        # The API requires: title/description/warehouse_id at the top level and
        # the space definition as a JSON string in 'serialized_space'
        # ({version: 2, data_sources.tables[].identifier, instructions.text_instructions}).
        if not warehouse_id:
            from src.common.config import get_settings
            warehouse_id = get_settings().DATABRICKS_WAREHOUSE_ID
        if not warehouse_id:
            raise ValueError(
                "No SQL warehouse configured: Genie spaces require warehouse_id "
                "(set DATABRICKS_WAREHOUSE_ID on the app)"
            )

        space_def: Dict[str, Any] = {
            "version": 2,
            "config": {},
            # The API requires tables sorted by identifier
            "data_sources": {"tables": [{"identifier": ds} for ds in sorted(datasets)]},
        }
        # Add instructions/context (truncate to safe length)
        if instructions:
            space_def["instructions"] = {
                "text_instructions": [{"content": [instructions[:5000]]}]
            }

        payload = {
            "title": name,
            "description": description or "",
            "warehouse_id": warehouse_id,
            "serialized_space": json.dumps(space_def),
        }

        logger.info(f"Creating Genie Space with {len(datasets)} datasets: {name}")
        logger.debug(f"Genie Space payload: {payload}")

        # Call Databricks Genie Spaces API
        response = ws_client.api_client.do(
            method='POST',
            path='/api/2.0/genie/spaces',
            body=payload,
            headers={'Content-Type': 'application/json'}
        )

        # Extract space ID and URL from response
        space_id = response.get('space_id') or response.get('id')
        if not space_id:
            raise ValueError("No space_id returned from Genie API")

        workspace_url = ws_client.config.host
        # Remove trailing slash if present
        workspace_url = workspace_url.rstrip('/')
        space_url = f"{workspace_url}/genie/{space_id}"

        logger.info(f"Successfully created Genie Space: {space_id}")
        logger.info(f"Genie Space URL: {space_url}")

        return {
            'space_id': space_id,
            'space_url': space_url,
            'status': 'active'
        }

    except Exception as e:
        logger.error(f"Failed to create Genie Space: {e}", exc_info=True)
        raise


def collect_datasets_from_products(product_ids: List[str], db: Session) -> List[str]:
    """
    Collect all dataset identifiers from Data Product output ports.

    Args:
        product_ids: List of Data Product UUIDs
        db: Database session

    Returns:
        List of catalog.schema.table identifiers (deduplicated)
    """
    from src.repositories.data_products_repository import data_product_repo

    datasets = []
    logger.info(f"Collecting datasets from {len(product_ids)} products")

    for product_id in product_ids:
        try:
            product_db = data_product_repo.get(db, id=product_id)
            if not product_db:
                logger.warning(f"Product not found: {product_id}")
                continue

            logger.debug(f"Processing product: {product_db.name} ({product_id})")

            for port in product_db.output_ports:
                # Prefer exact table FQNs from the port contract's schema
                # objects: asset_identifier is often schema-level
                # (catalog.schema), which the Genie API rejects as an
                # invalid table identifier.
                added = False
                contract_id = getattr(port, 'contract_id', None)
                if contract_id:
                    from src.db_models.data_contracts import SchemaObjectDb
                    schema_objects = (db.query(SchemaObjectDb)
                                      .filter(SchemaObjectDb.contract_id == contract_id)
                                      .all())
                    for so in schema_objects:
                        fqn = so.physical_name
                        if fqn and fqn.count('.') == 2:
                            datasets.append(fqn)
                            added = True
                            logger.debug(f"Added dataset {fqn} from contract of port {port.name}")
                if (not added and port.asset_type in ['table', 'view']
                        and port.asset_identifier
                        and port.asset_identifier.count('.') == 2):
                    datasets.append(port.asset_identifier)
                    added = True
                    logger.debug(f"Added dataset: {port.asset_identifier} from port {port.name}")
                if not added:
                    logger.debug(f"Skipping port {port.name}: type={port.asset_type}, identifier={port.asset_identifier}")

        except Exception as e:
            logger.error(f"Error collecting datasets from product {product_id}: {e}", exc_info=True)
            # Continue processing other products

    # Deduplicate while preserving order
    unique_datasets = list(dict.fromkeys(datasets))
    logger.info(f"Collected {len(unique_datasets)} unique datasets from {len(datasets)} total")

    return unique_datasets


def collect_rich_text_metadata(product_ids: List[str], db: Session) -> Dict[str, List]:
    """
    Collect RichTextMetadataDb entries for products and their linked contracts.

    Args:
        product_ids: List of Data Product UUIDs
        db: Database session

    Returns:
        Dict mapping entity_id to list of metadata entries
    """
    from src.repositories.data_products_repository import data_product_repo
    from src.db_models.metadata import RichTextMetadataDb

    metadata_map = {}
    logger.info(f"Collecting rich text metadata for {len(product_ids)} products")

    for product_id in product_ids:
        try:
            # Get product-level metadata
            product_metadata = db.query(RichTextMetadataDb).filter(
                RichTextMetadataDb.entity_type == 'data_product',
                RichTextMetadataDb.entity_id == product_id
            ).all()

            if product_metadata:
                metadata_map[product_id] = product_metadata
                logger.debug(f"Found {len(product_metadata)} metadata entries for product {product_id}")

            # Get contract metadata from output ports
            product_db = data_product_repo.get(db, id=product_id)
            if product_db:
                for port in product_db.output_ports:
                    if port.contract_id:
                        contract_metadata = db.query(RichTextMetadataDb).filter(
                            RichTextMetadataDb.entity_type == 'data_contract',
                            RichTextMetadataDb.entity_id == port.contract_id
                        ).all()

                        if contract_metadata:
                            metadata_map[port.contract_id] = contract_metadata
                            logger.debug(f"Found {len(contract_metadata)} metadata entries for contract {port.contract_id}")

        except Exception as e:
            logger.error(f"Error collecting metadata for product {product_id}: {e}", exc_info=True)
            # Continue processing other products

    logger.info(f"Collected metadata for {len(metadata_map)} entities")
    return metadata_map


def format_metadata_for_genie(
    metadata_map: Dict[str, List],
    products: List,
    max_length: int = 5000,
    product_domains: Optional[Dict[str, str]] = None,
) -> str:
    """
    Format collected metadata as markdown instructions for Genie.

    Args:
        metadata_map: Dict of entity_id -> metadata entries
        products: List of DataProductDb objects
        max_length: Maximum character length (default 5000)
        product_domains: Optional {product_id: primary domain name}. Domain moved to the
            entity_domain_associations junction (the legacy DataProductDb.domain column was
            dropped), so the caller resolves it and passes it in here.

    Returns:
        Formatted markdown string
    """
    sections = []
    logger.info(f"Formatting metadata for {len(products)} products")

    # Add product information
    for product in products:
        section_parts = [f"## Data Product: {product.name}\n"]

        # Add product description if available
        if hasattr(product, 'description') and product.description:
            section_parts.append(f"**Description**: {product.description}\n")

        # Add product domain if available (resolved from the junction by the caller).
        primary_domain = (product_domains or {}).get(str(product.id))
        if primary_domain:
            section_parts.append(f"**Domain**: {primary_domain}\n")

        section_parts.append("\n")

        # Add rich text metadata for this product
        if product.id in metadata_map:
            for meta in metadata_map[product.id]:
                section_parts.append(f"### {meta.title}\n\n")

                if meta.short_description:
                    section_parts.append(f"{meta.short_description}\n\n")

                if meta.content_markdown:
                    # Limit individual content to reasonable size
                    content = meta.content_markdown
                    if len(content) > 1000:
                        content = content[:997] + "..."
                    section_parts.append(f"{content}\n\n")

        sections.append("".join(section_parts))

    # Combine all sections
    formatted = "\n".join(sections)

    # Truncate if needed
    if len(formatted) > max_length:
        formatted = formatted[:max_length - 3] + "..."
        logger.warning(f"Metadata truncated from {len(formatted)} to {max_length} characters")

    logger.info(f"Formatted metadata: {len(formatted)} characters")
    return formatted
