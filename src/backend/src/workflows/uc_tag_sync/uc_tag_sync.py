import json
import os
import re
import sys
import argparse
from typing import Any, Dict, Iterable, List, Optional, Tuple
from dataclasses import dataclass
from uuid import uuid4

from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine
from pyspark.sql import SparkSession

from databricks.sdk import WorkspaceClient
from databricks.sdk.errors import NotFound


# ============================================================================
# OAuth Token Generation & Database Connection (for Lakebase Postgres)
# ============================================================================

def get_oauth_token(ws_client: WorkspaceClient, instance_name: str) -> Tuple[str, str]:
    """Generate OAuth token for the service principal to access Lakebase Postgres.

    ``instance_name`` is either a provisioned instance name or an autoscale
    endpoint resource name (``projects/…/endpoints/…``).  The correct SDK API
    is chosen automatically.
    """
    if not instance_name or instance_name == 'None' or instance_name == '':
        raise RuntimeError(
            "Lakebase identifier is required but was not provided.\n"
            "This is auto-detected from the Databricks App resources.\n"
            "Ensure your app has a Lakebase database resource configured."
        )

    is_autoscale = instance_name.startswith("projects/")
    print(f"  Generating OAuth token for {'autoscale' if is_autoscale else 'provisioned'} Lakebase: {instance_name}")

    current_user = ws_client.current_user.me().user_name
    print(f"  Service Principal: {current_user}")

    try:
        if is_autoscale:
            cred = ws_client.postgres.generate_database_credential(
                endpoint=instance_name,
            )
        else:
            cred = ws_client.database.generate_database_credential(
                request_id=str(uuid4()),
                instance_names=[instance_name],
            )
    except AttributeError as e:
        raise RuntimeError(
            f"Failed to generate OAuth token: {e}\n"
            "This may indicate that the Databricks SDK version doesn't support database OAuth,\n"
            "or that the workspace client is not properly initialized.\n"
            "Please ensure you're using databricks-sdk >= 0.81.0."
        )

    print(f"  ✓ Successfully generated OAuth token")
    return current_user, cred.token


def build_db_url(
    host: str,
    db: str, 
    port: str, 
    schema: str,
    instance_name: str,
    ws_client: WorkspaceClient
) -> Tuple[str, str]:
    """Build PostgreSQL connection URL using OAuth authentication.
    
    Returns: (connection_url, auth_user)
    """
    
    print(f"  POSTGRES_HOST: {host}")
    print(f"  POSTGRES_DB: {db}")
    print(f"  POSTGRES_PORT: {port}")
    print(f"  POSTGRES_DB_SCHEMA: {schema}")
    print(f"  LAKEBASE_INSTANCE_NAME: {instance_name}")
    print(f"  Authentication: OAuth (Lakebase Postgres)")
    
    # Generate OAuth token
    oauth_user, oauth_token = get_oauth_token(ws_client, instance_name)
    print(f"  Using OAuth user: {oauth_user}")
    
    if not all([host, oauth_user, oauth_token, db]):
        missing = []
        if not host: missing.append("host")
        if not oauth_user: missing.append("oauth_user")
        if not oauth_token: missing.append("oauth_token")
        if not db: missing.append("db")
        raise RuntimeError(f"Missing required Postgres parameters: {', '.join(missing)}")
    
    query = f"?options=-csearch_path%3D{schema}" if schema else ""
    connection_url = f"postgresql+psycopg2://{oauth_user}:****@{host}:{port}/{db}{query}"
    print(f"  Connection URL (token redacted): {connection_url}")
    
    actual_url = f"postgresql+psycopg2://{oauth_user}:{oauth_token}@{host}:{port}/{db}{query}"
    return actual_url, oauth_user


def create_engine_from_params(
    ws_client: WorkspaceClient,
    host: str,
    db: str,
    port: str,
    schema: str,
    instance_name: str
) -> Engine:
    """Create SQLAlchemy engine using OAuth authentication."""
    if not instance_name:
        raise RuntimeError("lakebase_instance_name parameter is required")
    
    url, auth_user = build_db_url(host, db, port, schema, instance_name, ws_client)
    return create_engine(url, pool_pre_ping=True)


# --- Helpers -----------------------------------------------------------------


def slugify_iri(iri: str) -> str:
    last = iri.rstrip('/').split('/')[-1]
    last = last.split('#')[-1]
    return re.sub(r"[^a-z0-9-]", "-", last.lower()).strip('-')


def qualify_uc_name(physical_name: str, default_catalog: Optional[str], default_schema: Optional[str]) -> Optional[str]:
    if not physical_name:
        return None
    parts = physical_name.split(".")
    if len(parts) == 3:
        return physical_name
    if len(parts) == 2 and default_catalog:
        return f"{default_catalog}.{physical_name}"
    if len(parts) == 1 and default_catalog and default_schema:
        return f"{default_catalog}.{default_schema}.{physical_name}"
    return None


@dataclass
class SemanticLink:
    """Semantic link information"""
    iri: str
    label: Optional[str]
    slug: str


@dataclass
class DatasetTagInfo:
    fqn: str
    catalog: str
    schema: str
    table: str
    # Contract metadata
    contract_id: Optional[str]
    contract_name: Optional[str]
    contract_version: Optional[str]
    contract_status: Optional[str]
    # Product metadata
    product_id: Optional[str]
    product_name: Optional[str]
    product_version: Optional[str]
    product_status: Optional[str]
    # Domain metadata (prefer contract domain, fallback to product domain)
    domain_id: Optional[str]
    domain_name: Optional[str]
    # Semantic links
    semantic_links: List[SemanticLink]
    # Asset metadata (populated when sourced from assets table)
    asset_id: Optional[str] = None
    asset_type_name: Optional[str] = None


def read_contracts_and_links(engine: Engine, limit: Optional[int] = None) -> List[Dict[str, Any]]:
    sql = (
        """
        SELECT c.id AS contract_id,
               c.name AS contract_name,
               c.version AS contract_version,
               c.status AS contract_status,
               c.data_product AS product_name_from_contract,
               c.domain_id AS contract_domain_id,
               o.id   AS object_id,
               o.name AS schema_name,
               o.physical_name,
               el.iri AS schema_semantic_iri,
               el.label AS schema_semantic_label,
               d.id AS domain_id,
               d.name AS domain_name,
               p.id AS product_id,
               p.name AS product_name,
               p.version AS product_version,
               p.status AS product_status,
               p.domain AS product_domain
        FROM data_contracts c
        JOIN data_contract_schema_objects o ON o.contract_id = c.id
        LEFT JOIN entity_semantic_links el
          ON el.entity_type = 'data_contract_schema'
         AND el.entity_id = c.id || '#' || o.name
        LEFT JOIN data_domains d ON c.domain_id = d.id
        LEFT JOIN data_product_output_ports op ON op.contract_id = c.id AND op.asset_identifier = o.physical_name
        LEFT JOIN data_products p ON op.product_id = p.id
        """
        + (" LIMIT :limit" if limit else "")
    )
    params = {"limit": int(limit)} if limit else {}
    with engine.connect() as conn:
        rows = [dict(r._mapping) for r in conn.execute(text(sql), params)]
    return rows


def build_dataset_tag_infos(rows: List[Dict[str, Any]], default_catalog: Optional[str], default_schema: Optional[str]) -> List[DatasetTagInfo]:
    # Aggregate data per object (multiple rows per object due to semantic links)
    by_object: Dict[str, Dict[str, Any]] = {}
    for r in rows:
        key = r["object_id"]
        obj = by_object.setdefault(
            key,
            {
                "physical_name": r.get("physical_name"),
                "contract_id": r.get("contract_id"),
                "contract_name": r.get("contract_name"),
                "contract_version": r.get("contract_version"),
                "contract_status": r.get("contract_status"),
                "product_id": r.get("product_id"),
                "product_name": r.get("product_name") or r.get("product_name_from_contract"),
                "product_version": r.get("product_version"),
                "product_status": r.get("product_status"),
                "domain_id": r.get("domain_id"),
                "domain_name": r.get("domain_name"),
                "product_domain": r.get("product_domain"),
                "semantic_links": [],
            },
        )

        # Add semantic link if present
        iri = r.get("schema_semantic_iri")
        if iri:
            label = r.get("schema_semantic_label")
            slug = slugify_iri(str(iri))
            # Avoid duplicates
            if not any(link["iri"] == iri for link in obj["semantic_links"]):
                obj["semantic_links"].append({
                    "iri": str(iri),
                    "label": str(label) if label else None,
                    "slug": slug
                })

    out: List[DatasetTagInfo] = []
    for _obj_id, data in by_object.items():
        qualified = qualify_uc_name(str(data.get("physical_name") or ""), default_catalog, default_schema)
        if not qualified:
            continue
        parts = qualified.split(".")
        if len(parts) != 3:
            continue
        cat, sch, tbl = parts

        # Prefer contract domain, fallback to product domain (string field)
        domain_id = data.get("domain_id")
        domain_name = data.get("domain_name")
        if not domain_name and data.get("product_domain"):
            # Product domain is a string field, not FK
            domain_name = data.get("product_domain")

        semantic_links = [
            SemanticLink(iri=link["iri"], label=link["label"], slug=link["slug"])
            for link in data["semantic_links"]
        ]

        out.append(
            DatasetTagInfo(
                fqn=qualified,
                catalog=cat,
                schema=sch,
                table=tbl,
                contract_id=str(data.get("contract_id") or "") or None,
                contract_name=str(data.get("contract_name") or "") or None,
                contract_version=str(data.get("contract_version") or "") or None,
                contract_status=str(data.get("contract_status") or "") or None,
                product_id=str(data.get("product_id") or "") or None,
                product_name=str(data.get("product_name") or "") or None,
                product_version=str(data.get("product_version") or "") or None,
                product_status=str(data.get("product_status") or "") or None,
                domain_id=str(domain_id) if domain_id else None,
                domain_name=str(domain_name) if domain_name else None,
                semantic_links=semantic_links,
            )
        )
    return out


def read_assets_and_links(engine: Engine, limit: Optional[int] = None) -> List[Dict[str, Any]]:
    """Read UC-taggable assets (Table, View) with their domain, contract, product, and semantic link metadata."""
    sql = (
        """
        SELECT a.id::text    AS asset_id,
               a.name        AS asset_name,
               a.location    AS physical_name,
               at.name       AS asset_type_name,
               a.domain_id   AS asset_domain_id,
               d.id          AS domain_id,
               d.name        AS domain_name,
               er.target_id  AS contract_id,
               c.name        AS contract_name,
               c.version     AS contract_version,
               c.status      AS contract_status,
               p.id          AS product_id,
               p.name        AS product_name,
               p.version     AS product_version,
               p.status      AS product_status,
               p.domain      AS product_domain,
               esl.iri       AS asset_semantic_iri,
               esl.label     AS asset_semantic_label
        FROM assets a
        JOIN asset_types at ON a.asset_type_id = at.id
        LEFT JOIN data_domains d ON a.domain_id = d.id
        LEFT JOIN entity_relationships er
          ON er.source_id = a.id::text
         AND er.source_type IN ('Table', 'View')
         AND er.target_type = 'DataContract'
         AND er.relationship_type = 'implementsContract'
        LEFT JOIN data_contracts c ON er.target_id = c.id
        LEFT JOIN data_product_output_ports op
          ON op.contract_id = c.id
         AND op.asset_identifier = a.location
        LEFT JOIN data_products p ON op.product_id = p.id
        LEFT JOIN entity_semantic_links esl
          ON esl.entity_id = a.id::text
         AND esl.entity_type = 'asset'
        WHERE at.name IN ('Table', 'View')
          AND a.status = 'active'
          AND a.location IS NOT NULL
        """
        + (" LIMIT :limit" if limit else "")
    )
    params = {"limit": int(limit)} if limit else {}
    with engine.connect() as conn:
        rows = [dict(r._mapping) for r in conn.execute(text(sql), params)]
    return rows


def build_asset_tag_infos(rows: List[Dict[str, Any]], default_catalog: Optional[str], default_schema: Optional[str]) -> List[DatasetTagInfo]:
    """Convert asset query rows into DatasetTagInfo objects, aggregating semantic links."""
    by_asset: Dict[str, Dict[str, Any]] = {}
    for r in rows:
        key = r["asset_id"]
        obj = by_asset.setdefault(
            key,
            {
                "asset_id": r.get("asset_id"),
                "asset_type_name": r.get("asset_type_name"),
                "physical_name": r.get("physical_name"),
                "contract_id": r.get("contract_id"),
                "contract_name": r.get("contract_name"),
                "contract_version": r.get("contract_version"),
                "contract_status": r.get("contract_status"),
                "product_id": r.get("product_id"),
                "product_name": r.get("product_name"),
                "product_version": r.get("product_version"),
                "product_status": r.get("product_status"),
                "domain_id": r.get("domain_id"),
                "domain_name": r.get("domain_name"),
                "product_domain": r.get("product_domain"),
                "semantic_links": [],
            },
        )

        iri = r.get("asset_semantic_iri")
        if iri:
            label = r.get("asset_semantic_label")
            slug = slugify_iri(str(iri))
            if not any(link["iri"] == iri for link in obj["semantic_links"]):
                obj["semantic_links"].append({
                    "iri": str(iri),
                    "label": str(label) if label else None,
                    "slug": slug,
                })

    out: List[DatasetTagInfo] = []
    for _asset_id, data in by_asset.items():
        qualified = qualify_uc_name(str(data.get("physical_name") or ""), default_catalog, default_schema)
        if not qualified:
            continue
        parts = qualified.split(".")
        if len(parts) != 3:
            continue
        cat, sch, tbl = parts

        domain_id = data.get("domain_id")
        domain_name = data.get("domain_name")
        if not domain_name and data.get("product_domain"):
            domain_name = data.get("product_domain")

        semantic_links = [
            SemanticLink(iri=link["iri"], label=link["label"], slug=link["slug"])
            for link in data["semantic_links"]
        ]

        out.append(
            DatasetTagInfo(
                fqn=qualified,
                catalog=cat,
                schema=sch,
                table=tbl,
                contract_id=str(data.get("contract_id") or "") or None,
                contract_name=str(data.get("contract_name") or "") or None,
                contract_version=str(data.get("contract_version") or "") or None,
                contract_status=str(data.get("contract_status") or "") or None,
                product_id=str(data.get("product_id") or "") or None,
                product_name=str(data.get("product_name") or "") or None,
                product_version=str(data.get("product_version") or "") or None,
                product_status=str(data.get("product_status") or "") or None,
                domain_id=str(domain_id) if domain_id else None,
                domain_name=str(domain_name) if domain_name else None,
                semantic_links=semantic_links,
                asset_id=str(data.get("asset_id") or "") or None,
                asset_type_name=str(data.get("asset_type_name") or "") or None,
            )
        )
    return out


def merge_dataset_tag_infos(contract_datasets: List[DatasetTagInfo], asset_datasets: List[DatasetTagInfo]) -> List[DatasetTagInfo]:
    """Merge contract-based and asset-based DatasetTagInfo lists, deduplicating by FQN.

    When both sources provide an entry for the same FQN, fields from the richer
    source win per-field, and semantic links are unioned.
    """
    by_fqn: Dict[str, DatasetTagInfo] = {}

    for d in contract_datasets:
        by_fqn[d.fqn] = d

    for d in asset_datasets:
        existing = by_fqn.get(d.fqn)
        if existing is None:
            by_fqn[d.fqn] = d
        else:
            # Merge: prefer non-None values, union semantic links
            existing.contract_id = existing.contract_id or d.contract_id
            existing.contract_name = existing.contract_name or d.contract_name
            existing.contract_version = existing.contract_version or d.contract_version
            existing.contract_status = existing.contract_status or d.contract_status
            existing.product_id = existing.product_id or d.product_id
            existing.product_name = existing.product_name or d.product_name
            existing.product_version = existing.product_version or d.product_version
            existing.product_status = existing.product_status or d.product_status
            existing.domain_id = existing.domain_id or d.domain_id
            existing.domain_name = existing.domain_name or d.domain_name
            existing.asset_id = existing.asset_id or d.asset_id
            existing.asset_type_name = existing.asset_type_name or d.asset_type_name
            # Union semantic links
            existing_iris = {link.iri for link in existing.semantic_links}
            for link in d.semantic_links:
                if link.iri not in existing_iris:
                    existing.semantic_links.append(link)

    return list(by_fqn.values())


# Tag formatting and validation helpers --------------------------------------------

def sanitize_tag_key(key: str) -> str:
    """Sanitize tag key by replacing UC-invalid characters with underscores.

    UC tag keys cannot contain: commas, periods, colons, hyphens, forward slashes,
    backticks, equals signs. Also strip leading/trailing spaces.
    """
    invalid_chars = [',', '.', ':', '-', '/', '`', '=']
    sanitized = key.strip()
    for char in invalid_chars:
        sanitized = sanitized.replace(char, '_')
    return sanitized


def format_tag_string(format_str: str, variables: Dict[str, Optional[str]]) -> Optional[str]:
    """Format a tag key or value string by replacing {VARIABLE} placeholders.

    Args:
        format_str: Format string with {VARIABLE} placeholders
        variables: Dictionary mapping variable names to values

    Returns:
        Formatted string, or None if any required variable is missing/None
    """
    result = format_str
    for var_name, var_value in variables.items():
        placeholder = f"{{{var_name}}}"
        if placeholder in result:
            if var_value is None:
                # Required variable is missing
                return None
            result = result.replace(placeholder, var_value)
    return result


def build_variables_for_dataset(d: DatasetTagInfo, link: Optional[SemanticLink] = None) -> Dict[str, Optional[str]]:
    """Build variable dictionary for tag formatting.

    Args:
        d: Dataset tag info
        link: Optional semantic link (for semantic_assignment entity type)

    Returns:
        Dictionary mapping variable names to values
    """
    variables = {
        # Contract variables
        "CONTRACT.ID": d.contract_id,
        "CONTRACT.NAME": d.contract_name,
        "CONTRACT.VERSION": d.contract_version,
        "CONTRACT.STATUS": d.contract_status,
        # Product variables
        "PRODUCT.ID": d.product_id,
        "PRODUCT.NAME": d.product_name,
        "PRODUCT.VERSION": d.product_version,
        "PRODUCT.STATUS": d.product_status,
        # Domain variables
        "DOMAIN.ID": d.domain_id,
        "DOMAIN.NAME": d.domain_name,
        # Asset variables
        "ASSET.ID": d.asset_id,
        "ASSET.TYPE": d.asset_type_name,
        "ASSET.FQN": d.fqn,
    }

    # Add semantic link variables if provided
    if link:
        variables.update({
            "LINK.IRI": link.iri,
            "LINK.LABEL": link.label,
            "LINK.SLUG": link.slug,
        })

    return variables


# Databricks governed tags helpers ------------------------------------------------

def ensure_tag_key(ws: WorkspaceClient, key: str) -> None:
    # SDK doesn't yet expose create-if-missing uniformly for all backends; attempt idempotent create.
    try:
        ws.tags.create(key=key)
    except Exception:
        # Assume it exists already or creation is not required in this workspace
        pass


def get_existing_prefixed_tags(spark: SparkSession, object_type: str, object_name: str, prefix: str) -> Dict[str, Optional[str]]:
    """Read existing tags via information_schema views.

    object_type: CATALOG | SCHEMA | TABLE
    object_name: fully-qualified UC name (catalog.schema.table for TABLE, etc.)
    """
    parts = object_name.split(".")
    catalog = parts[0]

    if object_type == "CATALOG":
        q = (
            f"SELECT tag_name, tag_value "
            f"FROM `{catalog}`.information_schema.catalog_tags "
            f"WHERE catalog_name = '{catalog}'"
        )
    elif object_type == "SCHEMA":
        schema = parts[1] if len(parts) > 1 else ""
        q = (
            f"SELECT tag_name, tag_value "
            f"FROM `{catalog}`.information_schema.schema_tags "
            f"WHERE catalog_name = '{catalog}' AND schema_name = '{schema}'"
        )
    elif object_type == "TABLE":
        schema = parts[1] if len(parts) > 1 else ""
        table = parts[2] if len(parts) > 2 else ""
        q = (
            f"SELECT tag_name, tag_value "
            f"FROM `{catalog}`.information_schema.table_tags "
            f"WHERE catalog_name = '{catalog}' AND schema_name = '{schema}' AND table_name = '{table}'"
        )
    else:
        return {}

    rows = spark.sql(q).collect()
    existing: Dict[str, Optional[str]] = {}
    for r in rows:
        key = str(r["tag_name"])
        if key.startswith(prefix):
            existing[key] = r["tag_value"]
    return existing


def assign_tag(spark: SparkSession, object_type: str, object_name: str, key: str, value: Optional[str]) -> None:
    v = value if value is not None else ""
    escaped = v.replace("'", "''")
    spark.sql(f"ALTER {object_type} {object_name} SET TAGS ('{key}' = '{escaped}')")


def unassign_tag(spark: SparkSession, object_type: str, object_name: str, key: str) -> None:
    spark.sql(f"ALTER {object_type} {object_name} UNSET TAGS ('{key}')")


def reconcile_tags(ws: WorkspaceClient, spark: SparkSession, object_type: str, object_name: str, desired: Dict[str, Optional[str]], prefix: str, dry_run: bool = False) -> Tuple[int, int, List[str]]:
    existing = get_existing_prefixed_tags(spark, object_type, object_name, prefix)
    to_remove = [k for k in existing.keys() if k not in desired]
    to_upsert = {k: v for k, v in desired.items() if existing.get(k) != v}

    updated = 0
    removed = 0
    errors: List[str] = []
    if dry_run:
        if to_remove or to_upsert:
            print(f"[DRY-RUN] {object_type} {object_name} remove={to_remove} upsert={to_upsert}")
        return (0, 0, [])

    for k in to_remove:
        try:
            unassign_tag(spark, object_type, object_name, k)
            removed += 1
        except Exception as e:
            msg = f"Failed to remove tag {k} from {object_type} {object_name}: {e}"
            print(f"[WARN] {msg}")
            errors.append(msg)

    for k, v in to_upsert.items():
        try:
            ensure_tag_key(ws, k)
            assign_tag(spark, object_type, object_name, k, v)
            updated += 1
        except Exception as e:
            msg = f"Failed to assign tag {k}={v} to {object_type} {object_name}: {e}"
            print(f"[WARN] {msg}")
            errors.append(msg)

    return (updated, removed, errors)


def aggregate_parent_desired(dataset_items: List[DatasetTagInfo], tag_sync_configs: List[Dict[str, Any]]) -> Tuple[Dict[str, Dict[str, Optional[str]]], Dict[str, Dict[str, Optional[str]]]]:
    """Aggregate tags for parent schema and catalog levels.

    For now, we aggregate all dataset tags to their parent levels.
    This could be made more sophisticated in the future.

    Args:
        dataset_items: List of dataset tag infos
        tag_sync_configs: Tag sync configuration

    Returns:
        Tuple of (schema_tags, catalog_tags) where each is a dict mapping FQN to tag dict
    """
    schema_to_tags: Dict[str, Dict[str, set]] = {}
    catalog_to_tags: Dict[str, Dict[str, set]] = {}

    for d in dataset_items:
        schema_fqn = f"{d.catalog}.{d.schema}"

        # Build desired tags for this dataset
        desired = build_desired_for_dataset(d, tag_sync_configs)

        # Aggregate to parent levels
        for tag_key, tag_value in desired.items():
            if tag_value:
                # Add to schema level
                schema_vals = schema_to_tags.setdefault(schema_fqn, {})
                schema_vals.setdefault(tag_key, set()).add(tag_value)

                # Add to catalog level
                catalog_vals = catalog_to_tags.setdefault(d.catalog, {})
                catalog_vals.setdefault(tag_key, set()).add(tag_value)

    # Collapse sets to comma-separated strings
    def collapse(map_in: Dict[str, Dict[str, set]]) -> Dict[str, Dict[str, Optional[str]]]:
        out: Dict[str, Dict[str, Optional[str]]] = {}
        for res, vals in map_in.items():
            m: Dict[str, Optional[str]] = {}
            for k, v in vals.items():
                if isinstance(v, set):
                    m[k] = ",".join(sorted(v)) if v else None
            out[res] = m
        return out

    return collapse(schema_to_tags), collapse(catalog_to_tags)


def build_desired_for_dataset(d: DatasetTagInfo, tag_sync_configs: List[Dict[str, Any]]) -> Dict[str, Optional[str]]:
    """Build desired tags for a dataset based on configuration.

    Args:
        d: Dataset tag info
        tag_sync_configs: List of tag sync configuration dictionaries

    Returns:
        Dictionary of tag key -> value mappings
    """
    desired: Dict[str, Optional[str]] = {}

    for config in tag_sync_configs:
        entity_type = config.get("entity_type")
        enabled = config.get("enabled", True)

        if not enabled:
            continue

        tag_key_format = config.get("tag_key_format", "")
        tag_value_format = config.get("tag_value_format", "")

        if entity_type == "semantic_assignment":
            # Create one tag per semantic link
            for link in d.semantic_links:
                variables = build_variables_for_dataset(d, link=link)
                tag_key = format_tag_string(tag_key_format, variables)
                tag_value = format_tag_string(tag_value_format, variables)

                if tag_key and tag_value:
                    # Sanitize key for UC constraints
                    tag_key = sanitize_tag_key(tag_key)
                    desired[tag_key] = tag_value

        elif entity_type == "data_domain":
            if d.domain_name:
                variables = build_variables_for_dataset(d)
                tag_key = format_tag_string(tag_key_format, variables)
                tag_value = format_tag_string(tag_value_format, variables)

                if tag_key and tag_value:
                    tag_key = sanitize_tag_key(tag_key)
                    desired[tag_key] = tag_value

        elif entity_type == "data_contract":
            if d.contract_name:
                variables = build_variables_for_dataset(d)
                tag_key = format_tag_string(tag_key_format, variables)
                tag_value = format_tag_string(tag_value_format, variables)

                if tag_key and tag_value:
                    tag_key = sanitize_tag_key(tag_key)
                    desired[tag_key] = tag_value

        elif entity_type == "data_product":
            if d.product_name:
                variables = build_variables_for_dataset(d)
                tag_key = format_tag_string(tag_key_format, variables)
                tag_value = format_tag_string(tag_value_format, variables)

                if tag_key and tag_value:
                    tag_key = sanitize_tag_key(tag_key)
                    desired[tag_key] = tag_value

        elif entity_type == "asset":
            if d.asset_type_name:
                variables = build_variables_for_dataset(d)
                tag_key = format_tag_string(tag_key_format, variables)
                tag_value = format_tag_string(tag_value_format, variables)

                if tag_key and tag_value:
                    tag_key = sanitize_tag_key(tag_key)
                    desired[tag_key] = tag_value

    return desired


def main() -> None:
    parser = argparse.ArgumentParser(description="Sync Ontos metadata to UC governed tags")
    parser.add_argument("--tag_sync_configs", type=str, default="[]")
    parser.add_argument("--prefix", type=str, default="x_ontos_")
    parser.add_argument("--dry_run", type=str, default="false")
    parser.add_argument("--default_catalog", type=str, default="")
    parser.add_argument("--default_schema", type=str, default="")
    parser.add_argument("--limit", type=str, default="")
    parser.add_argument("--verbose", type=str, default="false")
    parser.add_argument("--lakebase_instance_name", type=str, required=True)
    parser.add_argument("--postgres_host", type=str, required=True)
    parser.add_argument("--postgres_db", type=str, required=True)
    parser.add_argument("--postgres_port", type=str, default="5432")
    parser.add_argument("--postgres_schema", type=str, default="public")
    # Telemetry parameters (passed from app)
    parser.add_argument("--product_name", type=str, default="ontos")
    parser.add_argument("--product_version", type=str, default="0.0.0")
    args, _ = parser.parse_known_args()

    # Parse tag sync configs
    tag_sync_configs = json.loads(args.tag_sync_configs) if args.tag_sync_configs else []

    # Compute tag prefix for filtering existing tags (find common prefix from all tag keys)
    # Fall back to legacy prefix parameter if no configs
    tag_prefixes = set()
    for config in tag_sync_configs:
        if config.get("enabled", True):
            key_format = config.get("tag_key_format", "")
            # Extract prefix before first variable placeholder
            if "{" in key_format:
                tag_prefixes.add(key_format.split("{")[0])
            else:
                tag_prefixes.add(key_format)

    # Use common prefix if all start with same prefix, otherwise use legacy prefix
    if tag_prefixes:
        common_prefix = ""
        sorted_prefixes = sorted(tag_prefixes)
        if len(sorted_prefixes) > 0:
            # Find longest common prefix
            first = sorted_prefixes[0]
            last = sorted_prefixes[-1]
            for i, char in enumerate(first):
                if i < len(last) and char == last[i]:
                    common_prefix += char
                else:
                    break
        prefix = common_prefix if common_prefix else args.prefix
    else:
        prefix = args.prefix

    dry_run: bool = args.dry_run.lower() in ("true", "1", "yes")
    default_catalog = args.default_catalog if args.default_catalog else None
    default_schema = args.default_schema if args.default_schema else None
    limit = int(args.limit) if args.limit and args.limit.isdigit() else None
    verbose = args.verbose.lower() in ("true", "1", "yes")

    print("=" * 80)
    print("UC Tag Sync workflow started")
    print("=" * 80)
    print(f"\nJob Parameters:")
    print(f"  Tag sync configs: {len(tag_sync_configs)} entity types configured")
    print(f"  Computed prefix: {prefix}")
    print(f"  Dry run: {dry_run}")
    print(f"  Default catalog: {default_catalog}")
    print(f"  Default schema: {default_schema}")
    print(f"  Limit: {limit}")
    print(f"  Verbose: {verbose}")
    print(f"  Lakebase instance name: {args.lakebase_instance_name}")

    # Initialize Workspace Client (needed for OAuth authentication)
    print("\nInitializing Databricks Workspace Client...")
    ws = WorkspaceClient(product=args.product_name, product_version=args.product_version)
    print("✓ Workspace client initialized")

    # Connect to database using OAuth
    print("\nConnecting to database...")
    engine = create_engine_from_params(
        ws_client=ws,
        host=args.postgres_host,
        db=args.postgres_db,
        port=args.postgres_port,
        schema=args.postgres_schema,
        instance_name=args.lakebase_instance_name
    )
    print("✓ Database connection established successfully")

    # Initialize Spark
    print("\nInitializing Spark Session...")
    spark = SparkSession.builder.appName("UC-Tag-Sync").getOrCreate()
    print("✓ Spark session initialized")

    # Read from both data sources: contracts and assets
    print("\nReading contract-based metadata...")
    contract_rows = read_contracts_and_links(engine, limit=limit)
    contract_datasets = build_dataset_tag_infos(contract_rows, default_catalog, default_schema)
    print(f"  Found {len(contract_datasets)} datasets from contracts")

    print("Reading asset-based metadata...")
    asset_rows = read_assets_and_links(engine, limit=limit)
    asset_datasets = build_asset_tag_infos(asset_rows, default_catalog, default_schema)
    print(f"  Found {len(asset_datasets)} datasets from assets")

    datasets = merge_dataset_tag_infos(contract_datasets, asset_datasets)

    updated_total = removed_total = 0
    all_errors: List[str] = []

    print(f"\nProcessing {len(datasets)} datasets (merged)...")

    # Dataset-level
    for d in datasets:
        desired = build_desired_for_dataset(d, tag_sync_configs)
        if not desired:
            continue
        u, r, errs = reconcile_tags(ws, spark, "TABLE", d.fqn, desired, prefix, dry_run=dry_run)
        updated_total += u
        removed_total += r
        all_errors.extend(errs)
        if verbose:
            print(f"Dataset {d.fqn}: updated={u} removed={r}")

    # Aggregate parent desired values
    schema_desired, catalog_desired = aggregate_parent_desired(datasets, tag_sync_configs)

    # Schema-level
    for schema_fqn, desired in schema_desired.items():
        if not desired:
            continue
        u, r, errs = reconcile_tags(ws, spark, "SCHEMA", schema_fqn, desired, prefix, dry_run=dry_run)
        updated_total += u
        removed_total += r
        all_errors.extend(errs)

    # Catalog-level
    for catalog_name, desired in catalog_desired.items():
        if not desired:
            continue
        u, r, errs = reconcile_tags(ws, spark, "CATALOG", catalog_name, desired, prefix, dry_run=dry_run)
        updated_total += u
        removed_total += r
        all_errors.extend(errs)

    print("\n" + "=" * 80)
    print(f"Summary: updated={updated_total} removed={removed_total} errors={len(all_errors)}")

    if all_errors:
        print(f"\n{len(all_errors)} error(s) occurred during tag sync:")
        for err in all_errors:
            print(f"  - {err}")
        print("=" * 80)
        sys.exit(1)

    print("✓ UC Tag Sync workflow completed successfully!")
    print("=" * 80)


if __name__ == "__main__":
    main()


