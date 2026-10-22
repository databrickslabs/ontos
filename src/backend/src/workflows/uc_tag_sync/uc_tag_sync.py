import json
import os
import re
import sys
import argparse
from typing import Any, Dict, Iterable, List, Optional, Tuple
from dataclasses import dataclass, field
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
    # Domain metadata: primary domain (prefer contract, fallback to product).
    # With multi-domain assignment the primary feeds the single-value ``data_domain``
    # tag; ``additional_domain_names`` carries the non-primary domains, each emitted as
    # its own numbered tag (``data_domain_1``, ``data_domain_2``, ...) since a UC
    # securable holds one value per tag key. See DomainExportAdapter.uc_tags.
    domain_id: Optional[str]
    domain_name: Optional[str]
    # Semantic links
    semantic_links: List[SemanticLink]
    # Asset metadata (populated when sourced from assets table)
    asset_id: Optional[str] = None
    asset_type_name: Optional[str] = None
    # Additional (non-primary) domain names for the chosen domain source.
    additional_domain_names: List[str] = field(default_factory=list)


def read_contracts_and_links(engine: Engine, limit: Optional[int] = None) -> List[Dict[str, Any]]:
    sql = (
        """
        SELECT c.id AS contract_id,
               c.name AS contract_name,
               c.version AS contract_version,
               c.status AS contract_status,
               c.data_product AS product_name_from_contract,
               o.id   AS object_id,
               o.name AS schema_name,
               o.physical_name,
               el.iri AS schema_semantic_iri,
               el.label AS schema_semantic_label,
               d.id AS domain_id,
               d.name AS domain_name,
               (SELECT array_agg(dd.name ORDER BY dd.name)
                  FROM entity_domain_associations eda2
                  JOIN data_domains dd ON dd.id = eda2.domain_id
                 WHERE eda2.entity_type = 'data_contract'
                   AND eda2.entity_id = c.id
                   AND eda2.is_primary = FALSE) AS contract_additional_domains,
               p.id AS product_id,
               p.name AS product_name,
               p.version AS product_version,
               p.status AS product_status,
               pd.name AS product_domain,
               (SELECT array_agg(dd.name ORDER BY dd.name)
                  FROM entity_domain_associations eda3
                  JOIN data_domains dd ON dd.id = eda3.domain_id
                 WHERE eda3.entity_type = 'data_product'
                   AND eda3.entity_id = p.id
                   AND eda3.is_primary = FALSE) AS product_additional_domains
        FROM data_contracts c
        JOIN data_contract_schema_objects o ON o.contract_id = c.id
        LEFT JOIN entity_semantic_links el
          ON el.entity_type = 'data_contract_schema'
         AND el.entity_id = c.id || '#' || o.name
        LEFT JOIN entity_domain_associations eda
          ON eda.entity_type = 'data_contract'
         AND eda.entity_id = c.id
         AND eda.is_primary = TRUE
        LEFT JOIN data_domains d ON d.id = eda.domain_id
        LEFT JOIN data_product_output_ports op ON op.contract_id = c.id AND op.asset_identifier = o.physical_name
        LEFT JOIN data_products p ON op.product_id = p.id
        LEFT JOIN entity_domain_associations pda
          ON pda.entity_type = 'data_product'
         AND pda.entity_id = p.id
         AND pda.is_primary = TRUE
        LEFT JOIN data_domains pd ON pd.id = pda.domain_id
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
                "contract_additional_domains": r.get("contract_additional_domains") or [],
                "product_domain": r.get("product_domain"),
                "product_additional_domains": r.get("product_additional_domains") or [],
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

        # Prefer contract domain, fallback to product domain. Additional (non-primary)
        # domains follow whichever source supplied the primary domain.
        domain_id = data.get("domain_id")
        domain_name = data.get("domain_name")
        additional_domains = list(data.get("contract_additional_domains") or [])
        if not domain_name and data.get("product_domain"):
            domain_name = data.get("product_domain")
            additional_domains = list(data.get("product_additional_domains") or [])

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
                additional_domain_names=[str(n) for n in additional_domains if n],
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
               d.id          AS domain_id,
               d.name        AS domain_name,
               (SELECT array_agg(dd.name ORDER BY dd.name)
                  FROM entity_domain_associations eda2
                  JOIN data_domains dd ON dd.id = eda2.domain_id
                 WHERE eda2.entity_type = 'asset'
                   AND eda2.entity_id = a.id::text
                   AND eda2.is_primary = FALSE) AS asset_additional_domains,
               er.target_id  AS contract_id,
               c.name        AS contract_name,
               c.version     AS contract_version,
               c.status      AS contract_status,
               p.id          AS product_id,
               p.name        AS product_name,
               p.version     AS product_version,
               p.status      AS product_status,
               pd.name       AS product_domain,
               (SELECT array_agg(dd.name ORDER BY dd.name)
                  FROM entity_domain_associations eda3
                  JOIN data_domains dd ON dd.id = eda3.domain_id
                 WHERE eda3.entity_type = 'data_product'
                   AND eda3.entity_id = p.id
                   AND eda3.is_primary = FALSE) AS product_additional_domains,
               esl.iri       AS asset_semantic_iri,
               esl.label     AS asset_semantic_label
        FROM assets a
        JOIN asset_types at ON a.asset_type_id = at.id
        LEFT JOIN entity_domain_associations ada
          ON ada.entity_type = 'asset'
         AND ada.entity_id = a.id::text
         AND ada.is_primary = TRUE
        LEFT JOIN data_domains d ON d.id = ada.domain_id
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
        LEFT JOIN entity_domain_associations pda
          ON pda.entity_type = 'data_product'
         AND pda.entity_id = p.id
         AND pda.is_primary = TRUE
        LEFT JOIN data_domains pd ON pd.id = pda.domain_id
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
                "asset_additional_domains": r.get("asset_additional_domains") or [],
                "product_domain": r.get("product_domain"),
                "product_additional_domains": r.get("product_additional_domains") or [],
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
        additional_domains = list(data.get("asset_additional_domains") or [])
        if not domain_name and data.get("product_domain"):
            domain_name = data.get("product_domain")
            additional_domains = list(data.get("product_additional_domains") or [])

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
                additional_domain_names=[str(n) for n in additional_domains if n],
            )
        )
    return out


# Direct physical links ---------------------------------------------------------
#
# Concepts can be linked straight to Unity Catalog objects (``entity_type`` =
# ``uc_catalog`` | ``uc_schema`` | ``uc_table`` | ``uc_column``) without a contract or
# asset wrapper. ``entity_id`` is the UC fully-qualified name.

DIRECT_UC_ENTITY_TYPES = ("uc_catalog", "uc_schema", "uc_table", "uc_column")


@dataclass
class ColumnTagInfo:
    """Semantic links attached directly to one UC column."""
    table_fqn: str
    column: str
    semantic_links: List[SemanticLink] = field(default_factory=list)

    @property
    def fqn(self) -> str:
        return f"{self.table_fqn}.{self.column}"


@dataclass
class DirectLinkInfos:
    """Result of converting direct UC link rows, grouped by UC object level."""
    tables: List[DatasetTagInfo] = field(default_factory=list)
    columns: List[ColumnTagInfo] = field(default_factory=list)
    # fqn ("catalog.schema" / "catalog") -> semantic links
    schemas: Dict[str, List[SemanticLink]] = field(default_factory=dict)
    catalogs: Dict[str, List[SemanticLink]] = field(default_factory=dict)


def read_direct_uc_links(engine: Engine, limit: Optional[int] = None) -> List[Dict[str, Any]]:
    """Read semantic links attached directly to UC catalogs, schemas, tables and columns."""
    sql = (
        """
        SELECT esl.entity_type AS entity_type,
               esl.entity_id   AS entity_id,
               esl.iri         AS iri,
               esl.label       AS label
        FROM entity_semantic_links esl
        WHERE esl.entity_type IN ('uc_catalog', 'uc_schema', 'uc_table', 'uc_column')
        ORDER BY esl.entity_type, esl.entity_id, esl.iri
        """
        + (" LIMIT :limit" if limit else "")
    )
    params = {"limit": int(limit)} if limit else {}
    with engine.connect() as conn:
        rows = [dict(r._mapping) for r in conn.execute(text(sql), params)]
    return rows


def _normalize_uc_name(name: Any) -> str:
    # UC object names are case-insensitive and stored lower-case; normalizing keeps two
    # spellings of one table from becoming two reconcile targets (which would flap).
    return ".".join(p.strip().strip("`") for p in str(name or "").strip().split(".")).lower()


def _add_link(links: List[SemanticLink], iri: Any, label: Any) -> None:
    if not iri:
        return
    iri = str(iri)
    if any(link.iri == iri for link in links):
        return
    links.append(SemanticLink(iri=iri, label=str(label) if label else None, slug=slugify_iri(iri)))


def build_direct_link_infos(
    rows: List[Dict[str, Any]], default_catalog: Optional[str], default_schema: Optional[str]
) -> DirectLinkInfos:
    """Convert direct UC link rows into table datasets, column links and parent-level links.

    Rows whose ``entity_id`` cannot be resolved to a fully-qualified UC name are skipped.
    """
    tables: Dict[str, DatasetTagInfo] = {}
    columns: Dict[Tuple[str, str], ColumnTagInfo] = {}
    out = DirectLinkInfos()
    catalog_default = default_catalog.lower() if default_catalog else None
    schema_default = default_schema.lower() if default_schema else None

    for r in rows:
        etype = r.get("entity_type")
        name = _normalize_uc_name(r.get("entity_id"))
        if not name:
            continue
        iri, label = r.get("iri"), r.get("label")

        if etype == "uc_catalog":
            if "." in name:
                continue
            _add_link(out.catalogs.setdefault(name, []), iri, label)
        elif etype == "uc_schema":
            if len(name.split(".")) == 1 and default_catalog:
                name = f"{default_catalog.lower()}.{name}"
            if len(name.split(".")) != 2:
                continue
            _add_link(out.schemas.setdefault(name, []), iri, label)
        elif etype == "uc_table":
            qualified = qualify_uc_name(name, catalog_default, schema_default)
            if not qualified or len(qualified.split(".")) != 3:
                continue
            ds = tables.get(qualified)
            if ds is None:
                cat, sch, tbl = qualified.split(".")
                ds = tables[qualified] = DatasetTagInfo(
                    fqn=qualified, catalog=cat, schema=sch, table=tbl,
                    contract_id=None, contract_name=None,
                    contract_version=None, contract_status=None,
                    product_id=None, product_name=None, product_version=None, product_status=None,
                    domain_id=None, domain_name=None, semantic_links=[],
                )
            _add_link(ds.semantic_links, iri, label)
        elif etype == "uc_column":
            table_part, _, column = name.rpartition(".")
            qualified = qualify_uc_name(table_part, catalog_default, schema_default)
            if not qualified or not column or len(qualified.split(".")) != 3:
                continue
            col = columns.setdefault(
                (qualified, column), ColumnTagInfo(table_fqn=qualified, column=column)
            )
            _add_link(col.semantic_links, iri, label)

    out.tables = list(tables.values())
    out.columns = list(columns.values())
    return out


def build_desired_for_links(
    links: List[SemanticLink], tag_sync_configs: List[Dict[str, Any]]
) -> Dict[str, Optional[str]]:
    """Build desired ``semantic_assignment`` tags for an object that only has semantic links.

    Used for columns and for directly-linked schemas/catalogs, where contract, product,
    domain and asset metadata do not exist. Uses the same key/value formatting as tables.
    """
    desired: Dict[str, Optional[str]] = {}
    for config in tag_sync_configs:
        if config.get("entity_type") != "semantic_assignment" or not config.get("enabled", True):
            continue
        for link in links:
            variables = {"LINK.IRI": link.iri, "LINK.LABEL": link.label, "LINK.SLUG": link.slug}
            key = format_tag_string(config.get("tag_key_format", ""), variables)
            value = format_tag_string(config.get("tag_value_format", ""), variables)
            if key and value:
                desired[sanitize_tag_key(key)] = value
    return desired



def merge_dataset_tag_infos(
    contract_datasets: List[DatasetTagInfo],
    asset_datasets: List[DatasetTagInfo],
    direct_datasets: Optional[List[DatasetTagInfo]] = None,
) -> List[DatasetTagInfo]:
    """Merge contract-, asset- and direct-link DatasetTagInfo lists, deduplicating by FQN.

    When both sources provide an entry for the same FQN, fields from the richer
    source win per-field, and semantic links are unioned.
    """
    by_fqn: Dict[str, DatasetTagInfo] = {}

    # UC names are case-insensitive: key (and parent aggregation) on lower case so the
    # same table reached through differently-cased sources is reconciled once.
    for d in list(contract_datasets) + list(asset_datasets) + list(direct_datasets or []):
        d.fqn, d.catalog, d.schema, d.table = (
            d.fqn.lower(), d.catalog.lower(), d.schema.lower(), d.table.lower()
        )

    # Contracts first, so their fields win when another source has the same FQN
    for d in list(contract_datasets) + list(asset_datasets) + list(direct_datasets or []):
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
            existing.asset_id = existing.asset_id or d.asset_id
            existing.asset_type_name = existing.asset_type_name or d.asset_type_name
            # Domain: a primary and its additional domains belong to the SAME source.
            # - existing has no primary yet  -> adopt d's primary + its additionals.
            # - both sources share the same primary -> union the additionals (both are
            #   legitimate additional domains for this FQN).
            # - primaries differ -> keep existing's; do NOT attach d's additionals to a
            #   different source's primary.
            if not existing.domain_name and d.domain_name:
                existing.domain_id = d.domain_id
                existing.domain_name = d.domain_name
                existing.additional_domain_names = list(d.additional_domain_names)
            elif existing.domain_name and d.domain_name == existing.domain_name:
                for name in d.additional_domain_names:
                    if name not in existing.additional_domain_names:
                        existing.additional_domain_names.append(name)
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

    object_type: CATALOG | SCHEMA | TABLE | COLUMN
    object_name: fully-qualified UC name (catalog.schema.table for TABLE,
                 catalog.schema.table.column for COLUMN, etc.)
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
    elif object_type == "COLUMN":
        schema = parts[1] if len(parts) > 1 else ""
        table = parts[2] if len(parts) > 2 else ""
        column = parts[3] if len(parts) > 3 else ""
        q = (
            f"SELECT tag_name, tag_value "
            f"FROM `{catalog}`.information_schema.column_tags "
            f"WHERE catalog_name = '{catalog}' AND schema_name = '{schema}' "
            f"AND table_name = '{table}' AND column_name = '{column}'"
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


def alter_target(object_type: str, object_name: str) -> str:
    """Return the ``ALTER`` target clause for a UC object.

    Columns are altered through their table: ``TABLE c.s.t ALTER COLUMN `col```.
    """
    if object_type == "COLUMN":
        table_fqn, _, column = object_name.rpartition(".")
        return f"TABLE {table_fqn} ALTER COLUMN `{column.replace('`', '``')}`"
    return f"{object_type} {object_name}"


def assign_tag(spark: SparkSession, object_type: str, object_name: str, key: str, value: Optional[str]) -> None:
    v = value if value is not None else ""
    escaped = v.replace("'", "''")
    spark.sql(f"ALTER {alter_target(object_type, object_name)} SET TAGS ('{key}' = '{escaped}')")


def unassign_tag(spark: SparkSession, object_type: str, object_name: str, key: str) -> None:
    spark.sql(f"ALTER {alter_target(object_type, object_name)} UNSET TAGS ('{key}')")


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


# Delivery state storage (tags delivered by this job) ----

# Tags this job delivered, by UC object:
# object type -> object FQN -> tag key -> tag value.
DeliveryState = Dict[str, Dict[str, Dict[str, Optional[str]]]]

DELIVERY_OBJECT_TYPES = ("TABLE", "COLUMN", "SCHEMA", "CATALOG")


def read_delivery_state(engine: Engine) -> Optional[DeliveryState]:
    """Read the tags the previous run delivered from app_settings.

    Returns None when the state can't be read, so the caller can tell "nothing
    was delivered" (an empty dict) apart from "unknown".
    """
    try:
        with engine.connect() as conn:
            row = conn.execute(
                text(
                    "SELECT value FROM app_settings WHERE key = "
                    "'uc_tag_sync_delivery_state'"
                )
            ).first()
            if not row or not row[0]:
                return {}
            data = json.loads(row[0])
            return data.get("objects", {})
    except Exception as e:
        msg = f"Failed to read UC tag delivery state: {e}"
        print(f"[WARN] {msg}")
        return None


def save_delivery_state(
    engine: Engine, state: DeliveryState, prefix: str, replace: bool = True
) -> Optional[str]:
    """Store what this run delivered in app_settings, for the next run.

    Returns an error message on failure.

    prefix is stored to detect prefix changes between runs.
    """
    payload = {"version": 1, "prefix": prefix, "objects": state}
    try:
        with engine.begin() as conn:
            # Use CURRENT_TIMESTAMP for better database compatibility
            conn.execute(
                text(
                    "INSERT INTO app_settings (key, value, updated_at) "
                    "VALUES (:key, :value, CURRENT_TIMESTAMP) "
                    "ON CONFLICT (key) DO UPDATE "
                    "SET value = EXCLUDED.value, "
                    "updated_at = CURRENT_TIMESTAMP"
                ),
                {"key": "uc_tag_sync_delivery_state", "value": json.dumps(payload)},
            )
    except Exception as e:
        msg = f"Failed to save UC tag delivery state: {e}"
        print(f"[WARN] {msg}")
        return msg
    return None


def remove_delivered_tags(
    spark: SparkSession,
    object_type: str,
    object_name: str,
    delivered: Dict[str, Optional[str]],
    prefix: str,
    dry_run: bool = False,
) -> Tuple[int, List[str], Dict[str, Optional[str]]]:
    """Remove tags this job delivered from an object that no longer has a link.

    Only the delivered keys are removed; other tags on the object stay. Returns
    (removed, errors, still_delivered): still_delivered holds the keys that
    couldn't be checked or removed, so the next run tries again.
    """
    try:
        existing = get_existing_prefixed_tags(spark, object_type, object_name, prefix)
    except Exception as e:
        msg = f"[WARN] Failed to read tags of {object_type} {object_name}: {e}"
        print(msg)
        return (0, [], dict(delivered))
    to_remove = [k for k in delivered if k in existing]
    if dry_run:
        if to_remove:
            print(f"[DRY-RUN] {object_type} {object_name} remove={to_remove}")
        return (0, [], {})

    removed = 0
    errors: List[str] = []
    still_delivered: Dict[str, Optional[str]] = {}
    for k in to_remove:
        try:
            unassign_tag(spark, object_type, object_name, k)
            removed += 1
        except Exception as e:
            msg = f"Failed to remove tag {k} from {object_type} {object_name}: {e}"
            print(f"[WARN] {msg}")
            errors.append(msg)
            still_delivered[k] = delivered[k]
    return (removed, errors, still_delivered)


@dataclass
class SyncResult:
    updated: int = 0
    removed: int = 0
    errors: List[str] = field(default_factory=list)
    delivered: DeliveryState = field(
        default_factory=lambda: {t: {} for t in DELIVERY_OBJECT_TYPES}
    )


def read_cleanup_legacy_status(engine: Engine) -> Dict[str, Any]:
    """Read legacy cleanup status from app_settings."""
    try:
        with engine.connect() as conn:
            row = conn.execute(
                text(
                    "SELECT value FROM app_settings WHERE key = "
                    "'uc_tag_sync_cleanup_legacy_status'"
                )
            ).first()
            if row and row[0]:
                return json.loads(row[0])
    except Exception:
        pass
    return {}


def mark_cleanup_legacy_checked(engine: Engine, dry_run: bool = False) -> None:
    """Mark that we've checked for legacy tags (first-run log done)."""
    if dry_run:
        return
    try:
        status = read_cleanup_legacy_status(engine)
        status["checked_first_run"] = True
        with engine.begin() as conn:
            conn.execute(
                text(
                    "INSERT INTO app_settings (key, value, updated_at) "
                    "VALUES (:key, :value, CURRENT_TIMESTAMP) "
                    "ON CONFLICT (key) DO UPDATE "
                    "SET value = EXCLUDED.value, updated_at = "
                    "CURRENT_TIMESTAMP"
                ),
                {
                    "key": "uc_tag_sync_cleanup_legacy_status",
                    "value": json.dumps(status),
                },
            )
    except Exception:
        pass


def mark_cleanup_legacy_done(engine: Engine) -> None:
    """Mark that legacy cleanup has been performed (one-time)."""
    try:
        with engine.begin() as conn:
            conn.execute(
                text(
                    "INSERT INTO app_settings (key, value, updated_at) "
                    "VALUES (:key, :value, CURRENT_TIMESTAMP) "
                    "ON CONFLICT (key) DO UPDATE "
                    "SET value = EXCLUDED.value, updated_at = "
                    "CURRENT_TIMESTAMP"
                ),
                {
                    "key": "uc_tag_sync_cleanup_legacy_status",
                    "value": json.dumps({"cleanup_done": True}),
                },
            )
    except Exception:
        pass


def _build_desired_set(
    datasets: List[DatasetTagInfo],
    direct: "DirectLinkInfos",
    current: Optional[DeliveryState] = None,
) -> Dict[Tuple[str, str], bool]:
    """Build set of (object_type, fqn) pairs that currently have desired tags.

    Returns dict mapping (object_type, fqn) -> True for quick lookup.
    """
    desired: Dict[Tuple[str, str], bool] = {}

    # Tables from datasets
    for d in datasets:
        desired[(("TABLE", d.fqn.lower()))] = True

    # Tables from direct links
    for d in direct.tables:
        desired[("TABLE", d.fqn.lower())] = True

    # Schemas from direct links
    for schema_fqn in direct.schemas.keys():
        desired[("SCHEMA", schema_fqn.lower())] = True

    # Catalogs from direct links
    for catalog_fqn in direct.catalogs.keys():
        desired[("CATALOG", catalog_fqn.lower())] = True

    # Columns from direct links
    for col in direct.columns:
        desired[("COLUMN", col.fqn.lower())] = True

    # Everything this run delivered: inherited schema/catalog tags, contract columns
    for object_type, objects in (current or {}).items():
        for fqn in objects:
            desired[(object_type, fqn.lower())] = True

    return desired


def _bulk_read_prefixed_tags_per_catalog(
    spark: SparkSession,
    catalog: str,
    prefix: str,
) -> Dict[Tuple[str, str], Dict[str, Optional[str]]]:
    """Bulk read prefixed tags at all four levels for a catalog.

    Returns dict mapping (object_type, fqn) -> {tag_key: tag_value, ...}
    for all objects in this catalog with the given prefix.
    """
    result: Dict[Tuple[str, str], Dict[str, Optional[str]]] = {}

    # Read CATALOG tags
    try:
        catalog_tags = get_existing_prefixed_tags(spark, "CATALOG", catalog, prefix)
        if catalog_tags:
            result[("CATALOG", catalog.lower())] = catalog_tags
    except Exception:
        pass

    # Read SCHEMA tags - need to query information_schema
    try:
        q = (
            f"SELECT schema_name, tag_name, tag_value "
            f"FROM `{catalog}`.information_schema.schema_tags "
            f"WHERE catalog_name = '{catalog}'"
        )
        rows = spark.sql(q).collect()
        schemas_by_tag: Dict[str, Dict[str, Dict[str, Optional[str]]]] = {}
        for r in rows:
            schema_name = str(r["schema_name"]).lower()
            tag_name = str(r["tag_name"])
            if tag_name.startswith(prefix):
                tag_value = r["tag_value"]
                schema_fqn = f"{catalog.lower()}.{schema_name}"
                if (("SCHEMA", schema_fqn)) not in result:
                    result[("SCHEMA", schema_fqn)] = {}
                result[("SCHEMA", schema_fqn)][tag_name] = tag_value
    except Exception:
        pass

    # Read TABLE tags
    try:
        q = (
            f"SELECT schema_name, table_name, tag_name, tag_value "
            f"FROM `{catalog}`.information_schema.table_tags "
            f"WHERE catalog_name = '{catalog}'"
        )
        rows = spark.sql(q).collect()
        for r in rows:
            schema_name = str(r["schema_name"]).lower()
            table_name = str(r["table_name"]).lower()
            tag_name = str(r["tag_name"])
            if tag_name.startswith(prefix):
                tag_value = r["tag_value"]
                table_fqn = f"{catalog.lower()}.{schema_name}.{table_name}"
                if (("TABLE", table_fqn)) not in result:
                    result[("TABLE", table_fqn)] = {}
                result[("TABLE", table_fqn)][tag_name] = tag_value
    except Exception:
        pass

    # Read COLUMN tags
    try:
        q = (
            f"SELECT schema_name, table_name, column_name, tag_name, tag_value "
            f"FROM `{catalog}`.information_schema.column_tags "
            f"WHERE catalog_name = '{catalog}'"
        )
        rows = spark.sql(q).collect()
        for r in rows:
            schema_name = str(r["schema_name"]).lower()
            table_name = str(r["table_name"]).lower()
            column_name = str(r["column_name"]).lower()
            tag_name = str(r["tag_name"])
            if tag_name.startswith(prefix):
                tag_value = r["tag_value"]
                column_fqn = (
                    f"{catalog.lower()}.{schema_name}."
                    f"{table_name}.{column_name}"
                )
                if (("COLUMN", column_fqn)) not in result:
                    result[("COLUMN", column_fqn)] = {}
                result[("COLUMN", column_fqn)][tag_name] = tag_value
    except Exception:
        pass

    return result


def handle_legacy_tag_cleanup(
    spark: SparkSession,
    engine: Engine,
    datasets: List[DatasetTagInfo],
    direct: "DirectLinkInfos",
    prefix: str,
    previous: Optional[DeliveryState],
    cleanup_enabled: bool,
    is_partial_read: bool,
    dry_run: bool = False,
    current: Optional[DeliveryState] = None,
) -> Tuple[int, List[str]]:
    """Handle optional cleanup of legacy tags (delivered before this feature).

    ``current`` is what this run delivered: every object in it keeps its tags,
    including schemas and catalogs that inherit tags from their tables.

    When cleanup_enabled is False and this is first full run, log candidates
    for operator review and mark "checked" so we don't repeat.
    When cleanup_enabled is True, remove legacy tags from unlinked objects
    (only default prefix, only in catalogs this instance links, only when not
    already done, only on full run).

    Returns (removed_count, errors).
    Errors mean cleanup did not complete; caller should not mark done.
    """
    default_prefix = "x_ontos_"

    # Only works with default prefix
    if cleanup_enabled and prefix != default_prefix:
        msg = f"[WARN] --cleanup_legacy_tags only works with default prefix "
        msg += f"'{default_prefix}', not '{prefix}'. Refusing cleanup."
        print(msg)
        return (0, [msg])

    # Collect linked catalogs
    linked_catalogs = set()
    for d in datasets:
        linked_catalogs.add(d.catalog.lower())

    if not linked_catalogs:
        return (0, [])

    removed_count = 0
    errors: List[str] = []

    cleanup_status = read_cleanup_legacy_status(engine)

    # Only proceed if: cleanup_enabled && full run && not already done && previous is readable
    if cleanup_enabled:
        if is_partial_read:
            print("[INFO] --limit is set: legacy tag cleanup skipped on partial runs")
            return (0, [])
        if previous is None:
            print("[INFO] Previous delivery state unavailable: legacy cleanup skipped")
            return (0, [])
        if cleanup_status.get("cleanup_done"):
            print("[INFO] Legacy cleanup already completed; skipping")
            return (0, [])

        # Build current desired set
        desired = _build_desired_set(datasets, direct, current)

        print(f"[INFO] Cleaning up legacy tags with prefix '{default_prefix}'...")

        # For each catalog, find and remove candidates
        for cat in linked_catalogs:
            try:
                # Bulk read all prefixed tags at all levels
                existing_tags = _bulk_read_prefixed_tags_per_catalog(
                    spark, cat, default_prefix
                )

                # Find candidates: objects with prefix tags but NO current link
                # and tags NOT already recorded in delivery state
                for (obj_type, fqn), tags_dict in existing_tags.items():
                    for tag_key in tags_dict.keys():
                        # Skip if object has current link (is in desired set)
                        if (obj_type, fqn) in desired:
                            continue

                        # Skip if tag already recorded in delivery state
                        # (those are handled by normal cleanup)
                        if (
                            obj_type in previous
                            and fqn in previous[obj_type]
                            and tag_key in previous[obj_type][fqn]
                        ):
                            continue

                        # This is a candidate for removal
                        try:
                            if dry_run:
                                print(
                                    f"[DRY-RUN] {obj_type} {fqn} remove="
                                    f"['{tag_key}']"
                                )
                            else:
                                unassign_tag(spark, obj_type, fqn, tag_key)
                                removed_count += 1
                                print(
                                    f"[INFO] Removed legacy tag '{tag_key}' "
                                    f"from {obj_type} {fqn}"
                                )
                        except Exception as e:
                            if not dry_run:
                                msg = (
                                    f"Failed to remove legacy tag '{tag_key}' from "
                                    f"{obj_type} {fqn}: {e}"
                                )
                                print(f"[WARN] {msg}")
                                errors.append(msg)

            except Exception as e:
                # Catalog might not exist, log but continue
                msg = f"Error reading tags for catalog {cat}: {e}"
                print(f"[WARN] {msg}")
                errors.append(msg)

        # Mark done only if no errors
        if not dry_run and not errors:
            mark_cleanup_legacy_done(engine)
            print(
                f"[INFO] Legacy cleanup complete: {removed_count} tags removed"
            )
        elif errors:
            print(
                f"[WARN] Legacy cleanup had {len(errors)} error(s); will retry "
                f"next run"
            )

    # Flag off: log candidates on first full run and mark "checked"
    elif not cleanup_enabled and not is_partial_read and previous is not None:
        if not cleanup_status.get("checked_first_run"):
            # First full run without cleanup: scan and log candidates
            desired = _build_desired_set(datasets, direct, current)
            candidates_found = 0
            candidate_samples: List[str] = []

            for cat in linked_catalogs:
                try:
                    existing_tags = _bulk_read_prefixed_tags_per_catalog(
                        spark, cat, default_prefix
                    )

                    for (obj_type, fqn), tags_dict in existing_tags.items():
                        for tag_key in tags_dict.keys():
                            # Skip if in desired set or already in delivery state
                            if (obj_type, fqn) in desired:
                                continue
                            if (
                                obj_type in previous
                                and fqn in previous[obj_type]
                                and tag_key in previous[obj_type][fqn]
                            ):
                                continue

                            candidates_found += 1
                            if len(candidate_samples) < 5:
                                candidate_samples.append(
                                    f"{obj_type} {fqn}: {tag_key}"
                                )

                except Exception:
                    pass

            if candidates_found > 0:
                sample_str = ", ".join(candidate_samples[:5])
                print(
                    f"[INFO] Found {candidates_found} legacy tags with prefix "
                    f"'{default_prefix}'"
                )
                print(f"[INFO]   Samples: {sample_str}")
                print(
                    f"[INFO] Run with --cleanup_legacy_tags=true to remove them"
                )

            # Mark "checked" so we don't repeat this scan
            if not dry_run:
                mark_cleanup_legacy_checked(engine, dry_run=dry_run)

    return (removed_count, errors)


def sync_tags(
    ws: WorkspaceClient,
    spark: SparkSession,
    datasets: List[DatasetTagInfo],
    direct: "DirectLinkInfos",
    tag_sync_configs: List[Dict[str, Any]],
    prefix: str,
    previous: Optional[DeliveryState],
    dry_run: bool = False,
    verbose: bool = False,
) -> SyncResult:
    """Reconcile UC tags for every linked object, then clean up lost links.

    previous is what the last run delivered. Objects in it that have no desired
    tags this run get the delivered keys removed. Pass None to skip that cleanup
    (state unknown, or a partial --limit read where a missing object doesn't
    mean unlinked).
    """
    result = SyncResult()

    def apply(
        object_type: str, fqn: str, desired: Dict[str, Optional[str]]
    ) -> Tuple[int, int]:
        u, r, errs = reconcile_tags(ws, spark, object_type, fqn, desired, prefix,
                                    dry_run=dry_run)
        result.updated += u
        result.removed += r
        result.errors.extend(errs)
        result.delivered[object_type].setdefault(fqn, {}).update(desired)
        return u, r

    # Dataset-level
    for d in datasets:
        desired = build_desired_for_dataset(d, tag_sync_configs)
        if not desired:
            continue
        u, r = apply("TABLE", d.fqn, desired)
        if verbose:
            print(f"Dataset {d.fqn}: updated={u} removed={r}")

    # Aggregate parent desired values
    schema_desired, catalog_desired = aggregate_parent_desired(
        datasets,
        tag_sync_configs,
        direct_schema_desired={
            f: build_desired_for_links(l, tag_sync_configs)
            for f, l in direct.schemas.items()
        },
        direct_catalog_desired={
            f: build_desired_for_links(l, tag_sync_configs)
            for f, l in direct.catalogs.items()
        },
    )

    # Column-level (concepts linked directly to a UC column)
    for col in direct.columns:
        desired = build_desired_for_links(col.semantic_links, tag_sync_configs)
        if not desired:
            continue
        u, r = apply("COLUMN", col.fqn, desired)
        if verbose:
            print(f"Column {col.fqn}: updated={u} removed={r}")

    # Schema-level
    for schema_fqn, desired in schema_desired.items():
        if desired:
            apply("SCHEMA", schema_fqn, desired)

    # Catalog-level
    for catalog_name, desired in catalog_desired.items():
        if desired:
            apply("CATALOG", catalog_name, desired)

    # Objects that had tags delivered last run but have no link now: nothing
    # above reconciles them, so remove what this job delivered there.
    if previous is None:
        return result
    for object_type in DELIVERY_OBJECT_TYPES:
        for fqn, tags in previous.get(object_type, {}).items():
            if fqn in result.delivered[object_type]:
                continue
            r, errs, still_delivered = remove_delivered_tags(
                spark, object_type, fqn, tags, prefix, dry_run=dry_run
            )
            result.removed += r
            result.errors.extend(errs)
            if still_delivered:
                result.delivered[object_type][fqn] = still_delivered
            if verbose:
                print(f"{object_type} {fqn} (no link left): removed={r}")
    return result


def aggregate_parent_desired(
    dataset_items: List[DatasetTagInfo],
    tag_sync_configs: List[Dict[str, Any]],
    direct_schema_desired: Optional[Dict[str, Dict[str, Optional[str]]]] = None,
    direct_catalog_desired: Optional[Dict[str, Dict[str, Optional[str]]]] = None,
) -> Tuple[Dict[str, Dict[str, Optional[str]]], Dict[str, Dict[str, Optional[str]]]]:
    """Aggregate tags for parent schema and catalog levels.

    For now, we aggregate all dataset tags to their parent levels.
    This could be made more sophisticated in the future.

    Args:
        dataset_items: List of dataset tag infos
        tag_sync_configs: Tag sync configuration
        direct_schema_desired: Optional tags from concepts linked directly to schemas
            (schema FQN -> tag dict); merged with the aggregated values
        direct_catalog_desired: Same, for catalogs (catalog name -> tag dict)

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

    # Fold in tags from concepts linked directly to a schema/catalog. They share the
    # aggregated tag keys, so values are unioned and the comma-joined result stays stable.
    for fqn, tags in (direct_schema_desired or {}).items():
        for tag_key, tag_value in tags.items():
            if tag_value:
                schema_to_tags.setdefault(fqn, {}).setdefault(tag_key, set()).add(tag_value)
    for fqn, tags in (direct_catalog_desired or {}).items():
        for tag_key, tag_value in tags.items():
            if tag_value:
                catalog_to_tags.setdefault(fqn, {}).setdefault(tag_key, set()).add(tag_value)

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

                    # Additional (non-primary) domains are emitted as separate UC
                    # tags, one per assignment (PRD story 26). A UC securable holds
                    # one value per tag key, so each additional domain gets its own
                    # numbered key derived from the primary key (``data_domain_1``,
                    # ``data_domain_2``, ...) written after the primary. Names are
                    # sorted for deterministic key assignment. The running index skips
                    # any key already present in ``desired`` (e.g. one produced by
                    # another tag-sync config) so a numbered key never silently
                    # clobbers an unrelated tag.
                    idx = 1
                    for name in sorted(d.additional_domain_names):
                        additional_key = sanitize_tag_key(f"{tag_key}_{idx}")
                        while additional_key in desired:
                            idx += 1
                            additional_key = sanitize_tag_key(f"{tag_key}_{idx}")
                        desired[additional_key] = name
                        idx += 1

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
    parser.add_argument("--cleanup_legacy_tags", type=str, default="false")
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

    # Compute tag prefix for filtering existing tags
    tag_prefixes = set()
    for config in tag_sync_configs:
        if config.get("enabled", True):
            key_format = config.get("tag_key_format", "")
            if "{" in key_format:
                tag_prefixes.add(key_format.split("{")[0])
            else:
                tag_prefixes.add(key_format)

    if tag_prefixes:
        common_prefix = ""
        sorted_prefixes = sorted(tag_prefixes)
        if len(sorted_prefixes) > 0:
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
    cleanup_legacy = args.cleanup_legacy_tags.lower() in ("true", "1", "yes")

    print("=" * 80)
    print("UC Tag Sync workflow started")
    print("=" * 80)
    print(f"\nJob Parameters:")
    print(f"  Tag sync configs: {len(tag_sync_configs)} entity types")
    print(f"  Computed prefix: {prefix}")
    print(f"  Dry run: {dry_run}")
    print(f"  Default catalog: {default_catalog}")
    print(f"  Default schema: {default_schema}")
    print(f"  Limit: {limit}")
    print(f"  Verbose: {verbose}")
    print(f"  Cleanup legacy tags: {cleanup_legacy}")
    print(f"  Lakebase instance name: {args.lakebase_instance_name}")

    # Initialize Workspace Client (needed for OAuth authentication)
    print("\nInitializing Databricks Workspace Client...")
    ws = WorkspaceClient(product=args.product_name,
                         product_version=args.product_version)
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
    contract_datasets = build_dataset_tag_infos(contract_rows, default_catalog,
                                                default_schema)
    print(f"  Found {len(contract_datasets)} datasets from contracts")

    print("Reading asset-based metadata...")
    asset_rows = read_assets_and_links(engine, limit=limit)
    asset_datasets = build_asset_tag_infos(asset_rows, default_catalog,
                                           default_schema)
    print(f"  Found {len(asset_datasets)} datasets from assets")

    print("Reading direct UC links (catalog/schema/table/column)...")
    direct_rows = read_direct_uc_links(engine, limit=limit)
    direct = build_direct_link_infos(direct_rows, default_catalog, default_schema)
    print(
        f"  Found {len(direct.tables)} tables, {len(direct.columns)} columns, "
        f"{len(direct.schemas)} schemas, {len(direct.catalogs)} catalogs from "
        f"direct links"
    )

    datasets = merge_dataset_tag_infos(contract_datasets, asset_datasets,
                                       direct.tables)

    print("\nReading the previous UC tag delivery state...")
    previous = read_delivery_state(engine)
    is_partial_read = limit is not None
    if previous is None:
        msg = "  Unavailable: tags on objects that lost their last link are not"
        print(f"{msg} removed this run")
    elif is_partial_read:
        print("  --limit is set: objects without a link are not cleaned up")
    else:
        count = sum(len(o) for o in previous.values())
        print(f"  {count} object(s) had tags delivered last run")

    print(f"\nProcessing {len(datasets)} datasets (merged)...")
    result = sync_tags(
        ws,
        spark,
        datasets,
        direct,
        tag_sync_configs,
        prefix,
        previous=None if is_partial_read else previous,
        dry_run=dry_run,
        verbose=verbose,
    )
    updated_total, removed_total = result.updated, result.removed
    all_errors: List[str] = list(result.errors)

    if not dry_run:
        save_error = save_delivery_state(engine, result.delivered, prefix,
                                         replace=previous is not None and
                                         not is_partial_read)
        if save_error:
            all_errors.append(save_error)

    # Handle optional cleanup of legacy tags (from before delivery state tracking)
    print("\nHandling legacy tag cleanup...")
    legacy_removed, legacy_errors = handle_legacy_tag_cleanup(
        spark,
        engine,
        datasets,
        direct,
        prefix,
        previous=None if is_partial_read else previous,
        cleanup_enabled=cleanup_legacy,
        is_partial_read=is_partial_read,
        dry_run=dry_run,
        current=result.delivered,
    )
    removed_total += legacy_removed
    all_errors.extend(legacy_errors)

    print("\n" + "=" * 80)
    msg = f"Summary: updated={updated_total} removed={removed_total} errors="
    print(f"{msg}{len(all_errors)}")

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


