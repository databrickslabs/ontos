"""
UC Bulk Import Workflow

Discovers and imports Data Contracts, Products, and Domains from Unity Catalog
based on governed tags applied to catalog objects.
"""

import os
import sys
import json
import re
import argparse
import traceback
from typing import List, Dict, Any, Optional, Set, Tuple
from datetime import datetime
from uuid import uuid4

from sqlalchemy import text
from sqlalchemy.engine import Engine

from databricks.sdk import WorkspaceClient
from sqlalchemy import create_engine
from pyspark.sql import SparkSession


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


# ============================================================================
# Data Structures
# ============================================================================

class EntityPatternConfig:
    """Entity discovery pattern configuration"""
    def __init__(self, data: Dict[str, Any]):
        self.entity_type = data['entity_type']
        self.enabled = data.get('enabled', True)
        self.filter_source = data.get('filter_source')
        self.filter_pattern = data.get('filter_pattern')
        self.key_pattern = data['key_pattern']
        self.value_extraction_source = data['value_extraction_source']
        self.value_extraction_pattern = data['value_extraction_pattern']
        
        # Compile regex patterns
        self.key_regex = re.compile(self.key_pattern) if self.key_pattern else None
        self.filter_regex = re.compile(self.filter_pattern) if self.filter_pattern else None
        self.extraction_regex = re.compile(self.value_extraction_pattern)


class DiscoveredObject:
    """Represents a discovered catalog object with tags"""
    def __init__(self, object_type: str, full_name: str, tags: Dict[str, str]):
        self.object_type = object_type  # CATALOG, SCHEMA, TABLE
        self.full_name = full_name
        self.tags = tags
        
        # Parse full name
        parts = full_name.split('.')
        if object_type == 'CATALOG':
            self.catalog = parts[0]
            self.schema = None
            self.table = None
        elif object_type == 'SCHEMA':
            self.catalog = parts[0] if len(parts) > 0 else None
            self.schema = parts[1] if len(parts) > 1 else None
            self.table = None
        else:  # TABLE
            self.catalog = parts[0] if len(parts) > 0 else None
            self.schema = parts[1] if len(parts) > 1 else None
            self.table = parts[2] if len(parts) > 2 else None


# ============================================================================
# UC Tag Scanning
# ============================================================================

def scan_catalog_tags(ws: WorkspaceClient, verbose: bool = False) -> List[DiscoveredObject]:
    """
    Scan Unity Catalog for all tags on catalogs, schemas, and tables.
    
    Returns list of DiscoveredObject instances.
    """
    discovered = []
    
    # Initialize Spark session
    spark = SparkSession.builder.appName("UC-Bulk-Import").getOrCreate()
    
    if verbose:
        print("Scanning Unity Catalog tags...")
    
    # Query catalog tags
    try:
        query = "SELECT catalog_name, tag_name, tag_value FROM system.information_schema.catalog_tags"
        df = spark.sql(query)
        rows = df.collect()  # Returns list of Row objects
        
        for row in rows:
            catalog_name = row['catalog_name']
            tag_name = row['tag_name']
            tag_value = row['tag_value'] if row['tag_value'] else ''
            
            # Find or create discovered object
            obj = next((o for o in discovered if o.full_name == catalog_name and o.object_type == 'CATALOG'), None)
            if not obj:
                obj = DiscoveredObject('CATALOG', catalog_name, {})
                discovered.append(obj)
            obj.tags[tag_name] = tag_value
        
        if verbose:
            print(f"  Found {len(rows)} catalog tags")
    except Exception as e:
        print(f"Warning: Failed to scan catalog tags: {e}")
    
    # Query schema tags
    try:
        query = "SELECT catalog_name, schema_name, tag_name, tag_value FROM system.information_schema.schema_tags"
        df = spark.sql(query)
        rows = df.collect()
        
        for row in rows:
            catalog_name = row['catalog_name']
            schema_name = row['schema_name']
            full_name = f"{catalog_name}.{schema_name}"
            tag_name = row['tag_name']
            tag_value = row['tag_value'] if row['tag_value'] else ''
            
            obj = next((o for o in discovered if o.full_name == full_name and o.object_type == 'SCHEMA'), None)
            if not obj:
                obj = DiscoveredObject('SCHEMA', full_name, {})
                discovered.append(obj)
            obj.tags[tag_name] = tag_value
        
        if verbose:
            print(f"  Found {len(rows)} schema tags")
    except Exception as e:
        print(f"Warning: Failed to scan schema tags: {e}")
    
    # Query table tags
    try:
        query = "SELECT catalog_name, schema_name, table_name, tag_name, tag_value FROM system.information_schema.table_tags"
        df = spark.sql(query)
        rows = df.collect()
        
        for row in rows:
            catalog_name = row['catalog_name']
            schema_name = row['schema_name']
            table_name = row['table_name']
            full_name = f"{catalog_name}.{schema_name}.{table_name}"
            tag_name = row['tag_name']
            tag_value = row['tag_value'] if row['tag_value'] else ''
            
            obj = next((o for o in discovered if o.full_name == full_name and o.object_type == 'TABLE'), None)
            if not obj:
                obj = DiscoveredObject('TABLE', full_name, {})
                discovered.append(obj)
            obj.tags[tag_name] = tag_value
        
        if verbose:
            print(f"  Found {len(rows)} table tags")
    except Exception as e:
        print(f"Warning: Failed to scan table tags: {e}")
    
    if verbose:
        print(f"\nTotal discovered objects: {len(discovered)}")
    
    return discovered


# ============================================================================
# Pattern Matching & Filtering
# ============================================================================

def apply_filter(obj: DiscoveredObject, pattern: EntityPatternConfig, all_objects: List[DiscoveredObject]) -> bool:
    """
    Check if object passes filter pattern.
    
    Implements filter inheritance: schema-level filters apply to child tables,
    catalog-level filters apply to child schemas and tables.
    """
    if not pattern.filter_regex:
        return True  # No filter means all objects pass
    
    # Check object's own tags first
    for tag_key, tag_value in obj.tags.items():
        source_text = tag_key if pattern.filter_source == 'key' else tag_value
        if pattern.filter_regex.search(source_text):
            return True
    
    # Check parent schema tags (for tables)
    if obj.object_type == 'TABLE' and obj.catalog and obj.schema:
        schema_name = f"{obj.catalog}.{obj.schema}"
        schema_obj = next((o for o in all_objects if o.full_name == schema_name and o.object_type == 'SCHEMA'), None)
        if schema_obj:
            for tag_key, tag_value in schema_obj.tags.items():
                source_text = tag_key if pattern.filter_source == 'key' else tag_value
                if pattern.filter_regex.search(source_text):
                    return True
    
    # Check parent catalog tags (for schemas and tables)
    if obj.catalog:
        catalog_obj = next((o for o in all_objects if o.full_name == obj.catalog and o.object_type == 'CATALOG'), None)
        if catalog_obj:
            for tag_key, tag_value in catalog_obj.tags.items():
                source_text = tag_key if pattern.filter_source == 'key' else tag_value
                if pattern.filter_regex.search(source_text):
                    return True
    
    return False


def extract_entity_name(obj: DiscoveredObject, pattern: EntityPatternConfig) -> Optional[str]:
    """
    Extract entity name from object tags using pattern.
    
    Returns entity name if pattern matches, None otherwise.
    """
    for tag_key, tag_value in obj.tags.items():
        # Check if key matches key pattern
        if pattern.key_regex and pattern.key_regex.search(tag_key):
            # Extract name from source (key or value)
            source_text = tag_key if pattern.value_extraction_source == 'key' else tag_value
            match = pattern.extraction_regex.search(source_text)
            if match and match.groups():
                return match.group(1)  # Return first capture group
    
    return None


def discover_entities(
    objects: List[DiscoveredObject],
    patterns: List[EntityPatternConfig],
    verbose: bool = False
) -> Dict[str, Dict[str, List[DiscoveredObject]]]:
    """
    Discover entities from catalog objects using patterns.
    
    Returns: {entity_type: {entity_name: [objects]}}
    """
    results: Dict[str, Dict[str, List[DiscoveredObject]]] = {}
    
    for pattern in patterns:
        if not pattern.enabled:
            if verbose:
                print(f"Skipping disabled entity type: {pattern.entity_type}")
            continue
        
        if verbose:
            print(f"Processing {pattern.entity_type} patterns...")
        
        entity_map: Dict[str, List[DiscoveredObject]] = {}
        
        for obj in objects:
            # Apply filter
            if not apply_filter(obj, pattern, objects):
                continue
            
            # Extract entity name
            entity_name = extract_entity_name(obj, pattern)
            if entity_name:
                if entity_name not in entity_map:
                    entity_map[entity_name] = []
                entity_map[entity_name].append(obj)
        
        results[pattern.entity_type] = entity_map
        
        if verbose:
            print(f"  Discovered {len(entity_map)} {pattern.entity_type}(s)")
            for name, objs in list(entity_map.items())[:10]:  # Show first 10
                print(f"    - {name}: {len(objs)} UC object(s)")
                for obj in objs[:3]:  # Show first 3 objects per entity
                    tags_str = ", ".join(f"{k}={v}" for k, v in list(obj.tags.items())[:5])
                    if len(obj.tags) > 5:
                        tags_str += f" ... +{len(obj.tags) - 5} more"
                    print(f"      • {obj.full_name} ({obj.object_type})")
                    print(f"        Tags: {tags_str}")
                if len(objs) > 3:
                    print(f"      ... and {len(objs) - 3} more object(s)")
            
            if len(entity_map) > 10:
                print(f"    ... and {len(entity_map) - 10} more {pattern.entity_type}(s)")
    
    return results


# ============================================================================
# Entity Creation
# ============================================================================

def qualify_table_name(full_name: str, default_catalog: Optional[str], default_schema: Optional[str]) -> str:
    """Ensure table name is fully qualified"""
    parts = full_name.split('.')
    if len(parts) == 3:
        return full_name
    if len(parts) == 2 and default_catalog:
        return f"{default_catalog}.{full_name}"
    if len(parts) == 1 and default_catalog and default_schema:
        return f"{default_catalog}.{default_schema}.{full_name}"
    return full_name


def create_contracts(
    engine: Engine,
    entity_objects: Dict[str, List[DiscoveredObject]],
    conflict_strategy: str,
    default_catalog: Optional[str],
    default_schema: Optional[str],
    dry_run: bool = False,
    verbose: bool = False
) -> Dict[str, int]:
    """Create data contracts from discovered objects"""
    stats = {"created": 0, "skipped": 0, "errors": 0}
    
    for contract_name, objects in entity_objects.items():
        try:
            if verbose:
                print(f"  Processing contract: {contract_name}")
            
            # Check if exists
            check_sql = text("SELECT id FROM data_contracts WHERE name = :name")
            with engine.connect() as conn:
                result = conn.execute(check_sql, {"name": contract_name})
                existing = result.fetchone()
            
            if existing:
                if conflict_strategy == 'skip':
                    if verbose:
                        print(f"    Skipped (already exists)")
                    stats["skipped"] += 1
                    continue
                elif conflict_strategy == 'error':
                    raise ValueError(f"Contract '{contract_name}' already exists")
                # elif 'update': continue with creation/update
            
            if dry_run:
                print(f"  [DRY-RUN] Would create contract: {contract_name} with {len(objects)} schema objects")
                stats["created"] += 1
                continue
            
            # Create contract
            contract_id = str(uuid4())
            contract_sql = text("""
                INSERT INTO data_contracts (
                    id, name, kind, api_version, version, status, created_at, updated_at
                ) VALUES (
                    :id, :name, :kind, :api_version, :version, :status, :created_at, :updated_at
                )
                ON CONFLICT (id) DO UPDATE SET
                    updated_at = :updated_at
            """)
            
            with engine.connect() as conn:
                conn.execute(contract_sql, {
                    "id": contract_id,
                    "name": contract_name,
                    "kind": "DataContract",
                    "api_version": "v3.1.0",
                    "version": "1.0.0",
                    "status": "draft",
                    "created_at": datetime.utcnow(),
                    "updated_at": datetime.utcnow()
                })
                conn.commit()
            
            # Create schema objects for each table
            for obj in objects:
                if obj.object_type != 'TABLE':
                    continue
                
                qualified_name = qualify_table_name(obj.full_name, default_catalog, default_schema)
                object_id = str(uuid4())
                
                schema_obj_sql = text("""
                    INSERT INTO data_contract_schema_objects (
                        id, contract_id, name, logical_type, physical_name
                    ) VALUES (
                        :id, :contract_id, :name, :logical_type, :physical_name
                    )
                """)
                
                with engine.connect() as conn:
                    conn.execute(schema_obj_sql, {
                        "id": object_id,
                        "contract_id": contract_id,
                        "name": obj.table or qualified_name,
                        "logical_type": "table",
                        "physical_name": qualified_name
                    })
                    conn.commit()
            
            if verbose:
                print(f"    Created with {len([o for o in objects if o.object_type == 'TABLE'])} schema objects")
            stats["created"] += 1
            
        except Exception as e:
            print(f"  Error creating contract {contract_name}: {e}")
            if verbose:
                traceback.print_exc()
            stats["errors"] += 1
    
    return stats


def create_products(
    engine: Engine,
    entity_objects: Dict[str, List[DiscoveredObject]],
    conflict_strategy: str,
    default_catalog: Optional[str],
    default_schema: Optional[str],
    dry_run: bool = False,
    verbose: bool = False
) -> Dict[str, int]:
    """Create data products from discovered objects"""
    stats = {"created": 0, "skipped": 0, "errors": 0}
    
    for product_name, objects in entity_objects.items():
        try:
            if verbose:
                print(f"  Processing product: {product_name}")
            
            # Check if exists
            check_sql = text("SELECT id FROM data_products WHERE name = :name")
            with engine.connect() as conn:
                result = conn.execute(check_sql, {"name": product_name})
                existing = result.fetchone()
            
            if existing:
                if conflict_strategy == 'skip':
                    if verbose:
                        print(f"    Skipped (already exists)")
                    stats["skipped"] += 1
                    continue
                elif conflict_strategy == 'error':
                    raise ValueError(f"Product '{product_name}' already exists")
            
            if dry_run:
                print(f"  [DRY-RUN] Would create product: {product_name} with {len(objects)} output ports")
                stats["created"] += 1
                continue
            
            # Create product
            product_id = str(uuid4())
            product_sql = text("""
                INSERT INTO data_products (
                    id, api_version, kind, status, name, version, product_created_ts, created_at, updated_at
                ) VALUES (
                    :id, :api_version, :kind, :status, :name, :version, :product_created_ts, :created_at, :updated_at
                )
                ON CONFLICT (id) DO UPDATE SET
                    updated_at = :updated_at
            """)
            
            with engine.connect() as conn:
                conn.execute(product_sql, {
                    "id": product_id,
                    "api_version": "v1.0.0",
                    "kind": "DataProduct",
                    "status": "draft",
                    "name": product_name,
                    "version": "1.0.0",
                    "product_created_ts": datetime.utcnow(),
                    "created_at": datetime.utcnow(),
                    "updated_at": datetime.utcnow()
                })
                conn.commit()
            
            # Create output ports for each table
            for obj in objects:
                if obj.object_type != 'TABLE':
                    continue
                
                qualified_name = qualify_table_name(obj.full_name, default_catalog, default_schema)
                port_id = str(uuid4())
                
                port_sql = text("""
                    INSERT INTO output_ports (
                        id, product_id, name, version, asset_type, asset_identifier
                    ) VALUES (
                        :id, :product_id, :name, :version, :asset_type, :asset_identifier
                    )
                """)
                
                with engine.connect() as conn:
                    conn.execute(port_sql, {
                        "id": port_id,
                        "product_id": product_id,
                        "name": obj.table or qualified_name,
                        "version": "1.0.0",
                        "asset_type": "table",
                        "asset_identifier": qualified_name
                    })
                    conn.commit()
            
            if verbose:
                print(f"    Created with {len([o for o in objects if o.object_type == 'TABLE'])} output ports")
            stats["created"] += 1
            
        except Exception as e:
            print(f"  Error creating product {product_name}: {e}")
            if verbose:
                traceback.print_exc()
            stats["errors"] += 1
    
    return stats


def create_domains(
    engine: Engine,
    entity_objects: Dict[str, List[DiscoveredObject]],
    conflict_strategy: str,
    created_by: str,
    dry_run: bool = False,
    verbose: bool = False
) -> Dict[str, int]:
    """Create data domains from discovered objects"""
    stats = {"created": 0, "skipped": 0, "errors": 0}
    
    for domain_name, objects in entity_objects.items():
        try:
            if verbose:
                print(f"  Processing domain: {domain_name}")
            
            # Check if exists
            check_sql = text("SELECT id FROM data_domains WHERE name = :name")
            with engine.connect() as conn:
                result = conn.execute(check_sql, {"name": domain_name})
                existing = result.fetchone()
            
            if existing:
                if conflict_strategy == 'skip':
                    if verbose:
                        print(f"    Skipped (already exists)")
                    stats["skipped"] += 1
                    continue
                elif conflict_strategy == 'error':
                    raise ValueError(f"Domain '{domain_name}' already exists")
            
            if dry_run:
                print(f"  [DRY-RUN] Would create domain: {domain_name}")
                stats["created"] += 1
                continue
            
            # Create domain
            domain_id = str(uuid4())
            domain_sql = text("""
                INSERT INTO data_domains (
                    id, name, created_by, created_at, updated_at
                ) VALUES (
                    :id, :name, :created_by, :created_at, :updated_at
                )
                ON CONFLICT (id) DO UPDATE SET
                    updated_at = :updated_at
            """)
            
            with engine.connect() as conn:
                conn.execute(domain_sql, {
                    "id": domain_id,
                    "name": domain_name,
                    "created_by": created_by,
                    "created_at": datetime.utcnow(),
                    "updated_at": datetime.utcnow()
                })
                conn.commit()
            
            if verbose:
                print(f"    Created")
            stats["created"] += 1
            
        except Exception as e:
            print(f"  Error creating domain {domain_name}: {e}")
            if verbose:
                traceback.print_exc()
            stats["errors"] += 1
    
    return stats


def link_products_to_contracts(
    engine: Engine,
    discovered: Dict[str, Dict[str, List[DiscoveredObject]]],
    dry_run: bool = False,
    verbose: bool = False
) -> int:
    """
    Link products to contracts when same table has both tags.
    Updates output_port.contract_id when matching contract found.
    """
    linked = 0
    
    if 'contract' not in discovered or 'product' not in discovered:
        return linked
    
    contract_objects = discovered['contract']
    product_objects = discovered['product']
    
    # Build table -> contract_name mapping
    table_to_contract: Dict[str, str] = {}
    for contract_name, objects in contract_objects.items():
        for obj in objects:
            if obj.object_type == 'TABLE':
                table_to_contract[obj.full_name] = contract_name
    
    # For each product table, check if contract exists
    for product_name, objects in product_objects.items():
        for obj in objects:
            if obj.object_type != 'TABLE':
                continue
            
            contract_name = table_to_contract.get(obj.full_name)
            if not contract_name:
                continue
            
            if dry_run:
                print(f"  [DRY-RUN] Would link product '{product_name}' port '{obj.full_name}' to contract '{contract_name}'")
                linked += 1
                continue
            
            # Find contract ID
            contract_sql = text("SELECT id FROM data_contracts WHERE name = :name")
            with engine.connect() as conn:
                result = conn.execute(contract_sql, {"name": contract_name})
                contract_row = result.fetchone()
            
            if not contract_row:
                continue
            
            contract_id = contract_row[0]
            
            # Update output port
            update_sql = text("""
                UPDATE output_ports
                SET contract_id = :contract_id
                WHERE product_id IN (SELECT id FROM data_products WHERE name = :product_name)
                  AND asset_identifier = :asset_identifier
            """)
            
            with engine.connect() as conn:
                result = conn.execute(update_sql, {
                    "contract_id": contract_id,
                    "product_name": product_name,
                    "asset_identifier": obj.full_name
                })
                conn.commit()
                if result.rowcount > 0:
                    linked += 1
                    if verbose:
                        print(f"  Linked product '{product_name}' port to contract '{contract_name}'")
    
    return linked


# ============================================================================
# Main Workflow
# ============================================================================

def main():
    print("=" * 80)
    print("UC Bulk Import workflow started")
    print("=" * 80)
    
    parser = argparse.ArgumentParser(description="Import entities from Unity Catalog tags")
    parser.add_argument("--entity_patterns", type=str, required=True, help="JSON array of entity patterns")
    parser.add_argument("--default_catalog", type=str, default=None)
    parser.add_argument("--default_schema", type=str, default=None)
    parser.add_argument("--conflict_strategy", type=str, default="skip", choices=["skip", "update", "error"])
    parser.add_argument("--dry_run", type=str, default="false")
    parser.add_argument("--verbose", type=str, default="false")
    
    # Database connection parameters
    parser.add_argument("--lakebase_instance_name", type=str, required=True)
    parser.add_argument("--postgres_host", type=str, required=True)
    parser.add_argument("--postgres_db", type=str, required=True)
    parser.add_argument("--postgres_port", type=str, default="5432")
    parser.add_argument("--postgres_schema", type=str, default="public")
    # Telemetry parameters (passed from app)
    parser.add_argument("--product_name", type=str, default="ontos")
    parser.add_argument("--product_version", type=str, default="0.0.0")
    
    args = parser.parse_args()
    
    # Parse arguments
    entity_patterns_data = json.loads(args.entity_patterns)
    patterns = [EntityPatternConfig(p) for p in entity_patterns_data]
    dry_run = args.dry_run.lower() == "true"
    verbose = args.verbose.lower() == "true"
    
    print(f"\nConfiguration:")
    print(f"  Entity patterns: {len(patterns)} configured")
    print(f"  Default catalog: {args.default_catalog or 'None'}")
    print(f"  Default schema: {args.default_schema or 'None'}")
    print(f"  Conflict strategy: {args.conflict_strategy}")
    print(f"  Dry run: {dry_run}")
    print(f"  Verbose: {verbose}")
    
    # Initialize clients
    print("\nInitializing...")
    ws = WorkspaceClient(product=args.product_name, product_version=args.product_version)
    print("  Workspace client initialized")
    
    # Get current service principal for audit fields
    current_user = ws.current_user.me().user_name
    print(f"  Running as: {current_user}")
    
    print("\nConnecting to database...")
    engine = create_engine_from_params(
        ws_client=ws,
        host=args.postgres_host,
        db=args.postgres_db,
        port=args.postgres_port,
        schema=args.postgres_schema,
        instance_name=args.lakebase_instance_name
    )
    print("  Database connection established")
    
    # Scan Unity Catalog
    print("\n" + "=" * 80)
    print("Phase 1: Scanning Unity Catalog Tags")
    print("=" * 80)
    objects = scan_catalog_tags(ws, verbose=verbose)
    print(f"✓ Scanned {len(objects)} objects with tags")
    
    # Validate that we discovered at least some objects
    if len(objects) == 0:
        print("\n" + "=" * 80)
        print("❌ ERROR: No tagged objects discovered in Unity Catalog")
        print("=" * 80)
        print("\nThis may indicate:")
        print("  - No tags exist in Unity Catalog (check your catalogs/schemas/tables)")
        print("  - Scanning queries failed (check warnings above)")
        print("  - Insufficient permissions to read system.information_schema")
        print("  - Spark SQL is not properly configured")
        print("\nPlease verify:")
        print("  1. Tags exist on UC objects (catalogs, schemas, or tables)")
        print("  2. Service principal has SELECT permission on system.information_schema")
        print("  3. Review any warning messages above")
        sys.exit(1)
    
    # Discover entities
    print("\n" + "=" * 80)
    print("Phase 2: Discovering Entities")
    print("=" * 80)
    discovered = discover_entities(objects, patterns, verbose=verbose)
    
    total_discovered = sum(len(entities) for entities in discovered.values())
    print(f"✓ Discovered {total_discovered} unique entities across {len(discovered)} types")
    
    # Create entities
    print("\n" + "=" * 80)
    print("Phase 3: Creating Entities")
    print("=" * 80)
    
    summary = {}
    
    if 'contract' in discovered:
        print(f"\nCreating Contracts...")
        contract_stats = create_contracts(
            engine,
            discovered['contract'],
            args.conflict_strategy,
            args.default_catalog,
            args.default_schema,
            dry_run=dry_run,
            verbose=verbose
        )
        summary['contracts'] = contract_stats
        print(f"  Created: {contract_stats['created']}, Skipped: {contract_stats['skipped']}, Errors: {contract_stats['errors']}")
    
    if 'product' in discovered:
        print(f"\nCreating Products...")
        product_stats = create_products(
            engine,
            discovered['product'],
            args.conflict_strategy,
            args.default_catalog,
            args.default_schema,
            dry_run=dry_run,
            verbose=verbose
        )
        summary['products'] = product_stats
        print(f"  Created: {product_stats['created']}, Skipped: {product_stats['skipped']}, Errors: {product_stats['errors']}")
    
    if 'domain' in discovered:
        print(f"\nCreating Domains...")
        domain_stats = create_domains(
            engine,
            discovered['domain'],
            args.conflict_strategy,
            created_by=current_user,
            dry_run=dry_run,
            verbose=verbose
        )
        summary['domains'] = domain_stats
        print(f"  Created: {domain_stats['created']}, Skipped: {domain_stats['skipped']}, Errors: {domain_stats['errors']}")
    
    # Link products to contracts
    if 'contract' in discovered and 'product' in discovered:
        print(f"\n" + "=" * 80)
        print("Phase 4: Linking Products to Contracts")
        print("=" * 80)
        linked = link_products_to_contracts(engine, discovered, dry_run=dry_run, verbose=verbose)
        summary['linked'] = linked
        print(f"✓ Linked {linked} product ports to contracts")
    
    # Summary
    print("\n" + "=" * 80)
    print("Import Complete")
    print("=" * 80)
    print(json.dumps(summary, indent=2))
    
    total_errors = sum(stats.get('errors', 0) for stats in summary.values() if isinstance(stats, dict))
    if total_errors > 0:
        print(f"\n⚠ Completed with {total_errors} error(s)")
        sys.exit(1)
    else:
        print("\n✓ Import completed successfully")


if __name__ == "__main__":
    main()

