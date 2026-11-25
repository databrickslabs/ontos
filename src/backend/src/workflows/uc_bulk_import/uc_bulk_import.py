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
from datetime import datetime, timezone
from contextlib import contextmanager
from uuid import uuid4

from sqlalchemy import text
from sqlalchemy.engine import Engine
from sqlalchemy.exc import DBAPIError

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


def is_pooler_host(host: str) -> bool:
    """A Lakebase pooler host (``<endpoint>-pooler.<domain>``): it runs in
    transaction mode, which doesn't keep the job's session advisory lock."""
    return (host or "").split(".", 1)[0].lower().endswith("-pooler")


# Lock key of the job: ``data_products.name`` has no unique constraint and the
# job finds then inserts, so two overlapping runs could insert duplicates.
IMPORT_LOCK_NAME = "ontos.uc_bulk_import"
# Exit code of a run that finds another run holding the lock: the run fails, so a
# scheduler shows it red rather than green, with a code distinct from errors (1).
LOCK_HELD_EXIT_CODE = 3
# Transaction-level lock every write transaction takes before its fence check
# (see ``RunLock.fence``): a write transaction of a run that lost the lock then
# commits before the next run's first write begins its find, or fails its check.
IMPORT_WRITE_LOCK_NAME = "ontos.uc_bulk_import.write"

# A session is its pid and its start time: the OS can reuse a dead session's pid
_LOCK_HELD_SQL = text("""
    SELECT EXISTS (
        SELECT 1 FROM pg_locks l JOIN pg_stat_activity a ON a.pid = l.pid
        WHERE l.locktype = 'advisory' AND l.granted AND l.pid = :pid AND l.objsubid = 1
          AND a.backend_start = :backend_start
          AND ((l.classid::bigint << 32) | l.objid::bigint) = hashtext(:name)::bigint
    )
""")


class LockLostError(RuntimeError):
    """This run's lock connection ended, so another run may hold the lock now."""


class RunLock:
    """The run lock this run holds: ``pid`` and ``backend_start`` identify the
    server session of the lock connection (pid None on databases without
    advisory locks)."""

    def __init__(self, pid: Optional[int], backend_start: Optional[datetime] = None):
        self.pid = pid
        self.backend_start = backend_start

    def fence(self, conn) -> None:
        """First statement of each write transaction. Raises ``LockLostError``
        when the lock connection is gone (the server released its lock with it).

        The check runs inside the write transaction, under the write lock: a
        check made before the transaction would leave a window in which the lock
        is lost and a second run finds (before this one commits) and inserts the
        same entities. Under the write lock, a run's find waits for the commit of
        the other run's write transaction, and the check passes only while this
        run still holds the run lock, which no other run can hold at the same time.
        """
        if self.pid is None:
            return
        conn.execute(text("SELECT pg_advisory_xact_lock(hashtext(:name))"),
                     {"name": IMPORT_WRITE_LOCK_NAME})
        held = conn.execute(_LOCK_HELD_SQL, {
            "pid": self.pid, "backend_start": self.backend_start, "name": IMPORT_LOCK_NAME,
        }).scalar()
        if not held:
            raise LockLostError("The import lock was lost: this run stopped before writing")


# Databases without advisory locks (the unit tests): nothing to fence
NO_LOCK = RunLock(None)


@contextmanager
def single_flight(engine: Engine):
    """Yield a ``RunLock`` when this run holds the job's Postgres advisory lock
    (session level, held on its own connection until the block ends), None when
    another run holds it. Other databases (the unit tests) have no such lock:
    ``NO_LOCK``. Every write transaction calls ``RunLock.fence`` first, so a run
    whose lock connection ended stops before its next write.

    The lock connection runs in autocommit, so it sits ``idle`` (not ``idle in
    transaction``) while the import runs on other connections: a server
    ``idle_in_transaction_session_timeout`` can't end it and release the lock.
    The lock needs a direct connection: a transaction-mode pooler (such as
    Lakebase's PgBouncer, opt-in and not offered to OAuth roles) doesn't
    support advisory locks."""
    if engine.dialect.name != "postgresql":
        yield NO_LOCK
        return
    conn = engine.connect().execution_options(isolation_level="AUTOCOMMIT")
    try:
        acquired = bool(conn.execute(
            text("SELECT pg_try_advisory_lock(hashtext(:name))"), {"name": IMPORT_LOCK_NAME}
        ).scalar())
        try:
            if acquired:
                pid, backend_start = conn.execute(text(
                    "SELECT pid, backend_start FROM pg_stat_activity "
                    "WHERE pid = pg_backend_pid()"
                )).one()
                yield RunLock(pid, backend_start)
            else:
                yield None
        finally:
            if acquired:
                try:
                    released = conn.execute(
                        text("SELECT pg_advisory_unlock(hashtext(:name))"),
                        {"name": IMPORT_LOCK_NAME},
                    ).scalar()
                except DBAPIError:
                    # The connection died: the server dropped the lock with it. Raising
                    # here would mask the run's result or exit code.
                    released = False
                if not released:
                    print("  ⚠ The import lock was lost during the run (its connection ended)")
    finally:
        conn.close()


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


def find_existing(
    conn, table: str, name: str
) -> Optional[Tuple[str, Optional[str], Optional[str]]]:
    """(id, status, version_family_id) of the row a discovered entity matches, by
    name: the key both the skip and the update strategies use. Versions of an
    entity share its name, so the newest row is the one matched. Domains have no
    lifecycle or versions: (id, None, None). A user's personal draft (``draft_owner_id``
    set, made by editing a published entity) is never matched: it belongs to that user."""
    columns = "id" if table == "data_domains" else "id, status, version_family_id"
    personal = "" if table == "data_domains" else " AND draft_owner_id IS NULL"
    sql = text(f"SELECT {columns} FROM {table} WHERE name = :name{personal} "
               "ORDER BY created_at DESC LIMIT 1")
    row = conn.execute(sql, {"name": name}).first()
    if row is None:
        return None
    return (row[0], None, None) if len(row) == 1 else (row[0], row[1], row[2])


def should_skip_update(kind: str, name: str, status: Optional[str]) -> bool:
    """``update`` only touches drafts: a product or contract past draft is
    lifecycle-controlled in the app (versions, change log, search index), and
    the job would change it behind those, or re-add what a user deleted."""
    if status is None or status == 'draft':
        return False
    print(f"  Skipped {kind} '{name}': status is '{status}', update only changes drafts")
    return True


def _tables(objects: List[DiscoveredObject], default_catalog: Optional[str],
            default_schema: Optional[str]) -> List[Tuple[str, str]]:
    """(name, qualified name) of each discovered table, in discovery order."""
    tables = []
    for obj in objects:
        if obj.object_type != 'TABLE':
            continue
        qualified_name = qualify_table_name(obj.full_name, default_catalog, default_schema)
        tables.append((obj.table or qualified_name, qualified_name))
    return tables


def _new_stats() -> Dict[str, int]:
    return {"created": 0, "updated": 0, "unchanged": 0, "skipped": 0, "errors": 0}


_IMPORTED_SQL = text("""
    SELECT source_key FROM uc_bulk_import_sources
    WHERE entity_type = :entity_type AND version_family_id = :family_id
""")
_RECORD_SQL = text("""
    INSERT INTO uc_bulk_import_sources (
        id, entity_type, version_family_id, source_key, created_at
    ) VALUES (
        :id, :entity_type, :family_id, :source_key, :created_at
    )
""")


def _add_new_tables(conn, entity_type: str, family_id: str, tables: List[Tuple[str, str]],
                    present: Set[str], add, now: datetime) -> int:
    """Call ``add(name, qualified_name)`` for each table the job never imported
    into this version family, record it in ``uc_bulk_import_sources`` and return
    how many were added. A recorded table is never added again, so a deliverable
    a user deleted in the app stays deleted. A table in ``present`` (the entity
    already has it: imported before the job recorded its tables, or added by a
    user) is recorded, not added."""
    params = {"entity_type": entity_type, "family_id": family_id}
    imported = set(conn.execute(_IMPORTED_SQL, params).scalars())
    added = 0
    for name, qualified_name in tables:
        if qualified_name in imported:
            continue
        imported.add(qualified_name)
        if qualified_name not in present:
            add(name, qualified_name)
            added += 1
        conn.execute(_RECORD_SQL, {
            **params, "id": str(uuid4()), "source_key": qualified_name, "created_at": now,
        })
    return added


def _outcome(existing_id: Optional[str], added: int) -> str:
    if not existing_id:
        return "created"
    return "updated" if added else "unchanged"


def create_contracts(
    engine: Engine,
    entity_objects: Dict[str, List[DiscoveredObject]],
    conflict_strategy: str,
    default_catalog: Optional[str],
    default_schema: Optional[str],
    dry_run: bool = False,
    verbose: bool = False,
    run_lock: RunLock = NO_LOCK,
) -> Dict[str, int]:
    """Create data contracts from discovered objects.

    With the ``update`` strategy an existing draft contract (matched by name)
    keeps its id and gets a schema object for each tagged table the job never
    imported into it (see ``_add_new_tables``); its ``updated_at`` changes only
    when one is added (else it counts as unchanged). A contract past draft is
    skipped.
    """
    stats = _new_stats()

    # Raw SQL gets no ORM defaults, so every NOT NULL column of DataContractDb is set here.
    contract_sql = text("""
        INSERT INTO data_contracts (
            id, name, kind, api_version, version, status,
            published, version_family_id, publication_scope, created_at, updated_at
        ) VALUES (
            :id, :name, :kind, :api_version, :version, :status,
            :published, :version_family_id, :publication_scope, :created_at, :updated_at
        )
    """)
    touch_sql = text("UPDATE data_contracts SET updated_at = :updated_at WHERE id = :id")
    present_sql = text(
        "SELECT physical_name FROM data_contract_schema_objects WHERE contract_id = :id"
    )
    schema_obj_sql = text("""
        INSERT INTO data_contract_schema_objects (
            id, contract_id, name, logical_type, physical_name
        ) VALUES (
            :id, :contract_id, :name, :logical_type, :physical_name
        )
    """)

    for contract_name, objects in entity_objects.items():
        try:
            if verbose:
                print(f"  Processing contract: {contract_name}")

            now = datetime.now(timezone.utc)
            # One transaction, the find included: a contract whose schema objects
            # failed would be skipped by every later run, and the fence (before the
            # find) keeps a run that lost its lock from writing.
            with engine.begin() as conn:
                if not dry_run:
                    run_lock.fence(conn)
                existing = find_existing(conn, "data_contracts", contract_name)
                existing_id = existing[0] if existing else None
                if existing_id:
                    if conflict_strategy == 'skip':
                        if verbose:
                            print(f"    Skipped (already exists)")
                        stats["skipped"] += 1
                        continue
                    elif conflict_strategy == 'error':
                        raise ValueError(f"Contract '{contract_name}' already exists")
                if existing_id and should_skip_update('contract', contract_name, existing[1]):
                    stats["skipped"] += 1
                    continue

                if dry_run:
                    verb = "update" if existing_id else "create"
                    print(f"  [DRY-RUN] Would {verb} contract: {contract_name} "
                          f"with {len(objects)} schema objects")
                    stats["updated" if existing_id else "created"] += 1
                    continue

                if existing_id:
                    contract_id, family_id = existing_id, existing[2]
                    present = set(conn.execute(present_sql, {"id": contract_id}).scalars())
                else:
                    contract_id = family_id = str(uuid4())
                    conn.execute(contract_sql, {
                        "id": contract_id,
                        "name": contract_name,
                        "kind": "DataContract",
                        "api_version": "v3.1.0",
                        "version": "1.0.0",
                        "status": "draft",
                        "published": False,
                        "version_family_id": family_id,
                        "publication_scope": "none",
                        "created_at": now,
                        "updated_at": now
                    })
                    present = set()

                def add_schema_object(name, qualified_name):
                    conn.execute(schema_obj_sql, {
                        "id": str(uuid4()),
                        "contract_id": contract_id,
                        "name": name,
                        "logical_type": "table",
                        "physical_name": qualified_name
                    })

                added = _add_new_tables(
                    conn, "data_contract", family_id,
                    _tables(objects, default_catalog, default_schema),
                    present, add_schema_object, now,
                )
                if existing_id and added:
                    conn.execute(touch_sql, {"id": contract_id, "updated_at": now})

            outcome = _outcome(existing_id, added)
            if verbose:
                print(f"    {outcome.capitalize()}, {added} schema object(s) added")
            stats[outcome] += 1

        except LockLostError:
            raise
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
    verbose: bool = False,
    run_lock: RunLock = NO_LOCK,
) -> Dict[str, int]:
    """Create data products from discovered objects.

    With the ``update`` strategy an existing draft product (matched by name)
    keeps its id and gets an output port for each tagged table the job never
    imported into it (see ``_add_new_tables``); its ``updated_at`` changes only
    when one is added (else it counts as unchanged). A product past draft is
    skipped.

    Imported products have no owner on purpose: ``draft_owner_id``,
    ``owner_team_id`` and ``project_id`` stay NULL, so only admins see the
    draft and can edit it until they assign an owner in the app. The job also
    skips what the manager's create path does (change log, search index, tags,
    domain links, on_create workflows).
    """
    stats = _new_stats()

    # Raw SQL skips the ORM's Python-side defaults, and a fresh database (tables
    # from create_all) has no server defaults, so every NOT NULL column of
    # DataProductDb is set here.
    product_sql = text("""
        INSERT INTO data_products (
            id, api_version, kind, status, name, version, product_created_ts,
            max_level_inheritance, version_family_id, published, publication_scope,
            created_at, updated_at
        ) VALUES (
            :id, :api_version, :kind, :status, :name, :version, :product_created_ts,
            :max_level_inheritance, :version_family_id, :published, :publication_scope,
            :created_at, :updated_at
        )
    """)
    touch_sql = text("UPDATE data_products SET updated_at = :updated_at WHERE id = :id")
    present_sql = text(
        "SELECT asset_identifier FROM data_product_output_ports WHERE product_id = :id"
    )
    port_sql = text("""
        INSERT INTO data_product_output_ports (
            id, product_id, name, version, asset_type, asset_identifier,
            contains_pii, auto_approve
        ) VALUES (
            :id, :product_id, :name, :version, :asset_type, :asset_identifier,
            :contains_pii, :auto_approve
        )
    """)

    for product_name, objects in entity_objects.items():
        try:
            if verbose:
                print(f"  Processing product: {product_name}")

            now = datetime.now(timezone.utc)
            # One transaction, the find included: a product whose ports failed
            # would be skipped by every later run, and the fence (before the find)
            # keeps a run that lost its lock from writing.
            with engine.begin() as conn:
                if not dry_run:
                    run_lock.fence(conn)
                existing = find_existing(conn, "data_products", product_name)
                existing_id = existing[0] if existing else None
                if existing_id:
                    if conflict_strategy == 'skip':
                        if verbose:
                            print(f"    Skipped (already exists)")
                        stats["skipped"] += 1
                        continue
                    elif conflict_strategy == 'error':
                        raise ValueError(f"Product '{product_name}' already exists")
                if existing_id and should_skip_update('product', product_name, existing[1]):
                    stats["skipped"] += 1
                    continue

                if dry_run:
                    verb = "update" if existing_id else "create"
                    print(f"  [DRY-RUN] Would {verb} product: {product_name} "
                          f"with {len(objects)} output ports")
                    stats["updated" if existing_id else "created"] += 1
                    continue

                if existing_id:
                    product_id, family_id = existing_id, existing[2]
                    present = set(conn.execute(present_sql, {"id": product_id}).scalars())
                else:
                    product_id = family_id = str(uuid4())
                    conn.execute(product_sql, {
                        "id": product_id,
                        "api_version": "v1.0.0",
                        "kind": "DataProduct",
                        "status": "draft",
                        "name": product_name,
                        "version": "1.0.0",
                        "product_created_ts": now,
                        "max_level_inheritance": 99,
                        "version_family_id": family_id,
                        "published": False,
                        "publication_scope": "none",
                        "created_at": now,
                        "updated_at": now
                    })
                    present = set()

                def add_port(name, qualified_name):
                    conn.execute(port_sql, {
                        "id": str(uuid4()),
                        "product_id": product_id,
                        "name": name,
                        "version": "1.0.0",
                        "asset_type": "table",
                        "asset_identifier": qualified_name,
                        "contains_pii": False,
                        "auto_approve": False
                    })

                added = _add_new_tables(
                    conn, "data_product", family_id,
                    _tables(objects, default_catalog, default_schema),
                    present, add_port, now,
                )
                if existing_id and added:
                    conn.execute(touch_sql, {"id": product_id, "updated_at": now})

            outcome = _outcome(existing_id, added)
            if verbose:
                print(f"    {outcome.capitalize()}, {added} output port(s) added")
            stats[outcome] += 1

        except LockLostError:
            raise
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
    verbose: bool = False,
    run_lock: RunLock = NO_LOCK,
) -> Dict[str, int]:
    """Create data domains from discovered objects.

    With the ``update`` strategy an existing domain (matched by its unique
    name) is left as it is and counted as unchanged: the job sets nothing on a
    domain beyond its name. Domains are standalone: the job doesn't link them
    to products or contracts.
    """
    stats = _new_stats()
    domain_sql = text("""
        INSERT INTO data_domains (
            id, name, created_by, created_at, updated_at
        ) VALUES (
            :id, :name, :created_by, :created_at, :updated_at
        )
    """)

    for domain_name, objects in entity_objects.items():
        try:
            if verbose:
                print(f"  Processing domain: {domain_name}")

            now = datetime.now(timezone.utc)
            with engine.begin() as conn:
                if not dry_run:
                    run_lock.fence(conn)
                existing = find_existing(conn, "data_domains", domain_name)
                existing_id = existing[0] if existing else None
                if existing_id:
                    if conflict_strategy == 'skip':
                        if verbose:
                            print(f"    Skipped (already exists)")
                        stats["skipped"] += 1
                        continue
                    elif conflict_strategy == 'error':
                        raise ValueError(f"Domain '{domain_name}' already exists")
                    if verbose:
                        print(f"    Unchanged (already exists)")
                    stats["unchanged"] += 1
                    continue

                if dry_run:
                    print(f"  [DRY-RUN] Would create domain: {domain_name}")
                    stats["created"] += 1
                    continue

                conn.execute(domain_sql, {
                    "id": str(uuid4()),
                    "name": domain_name,
                    "created_by": created_by,
                    "created_at": now,
                    "updated_at": now
                })

            if verbose:
                print(f"    Created")
            stats["created"] += 1

        except LockLostError:
            raise
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
    verbose: bool = False,
    run_lock: RunLock = NO_LOCK,
) -> int:
    """
    Link products to contracts when same table has both tags.
    Sets output_port.contract_id to the newest version of the matching
    contract, on draft products only, and only on ports with no contract: a
    port a user linked to another contract keeps it.
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

    update_sql = text("""
        UPDATE data_product_output_ports
        SET contract_id = :contract_id
        WHERE product_id IN (
            SELECT id FROM data_products
            WHERE name = :product_name AND status = 'draft' AND draft_owner_id IS NULL
        )
          AND asset_identifier = :asset_identifier
          AND contract_id IS NULL
    """)

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

            with engine.begin() as conn:
                run_lock.fence(conn)
                # Versions share the contract's name: link the newest, as matching does
                contract = find_existing(conn, "data_contracts", contract_name)
                if not contract:
                    continue
                result = conn.execute(update_sql, {
                    "contract_id": contract[0],
                    "product_name": product_name,
                    "asset_identifier": obj.full_name
                })
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
    
    if is_pooler_host(args.postgres_host):
        print(f"\n❌ postgres_host '{args.postgres_host}' is a connection pooler: the import "
              "lock needs a direct connection (use the host without '-pooler')")
        sys.exit(1)

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
    
    if dry_run:
        # A dry run writes nothing: it neither needs the lock nor blocks a real run
        run_import(args, ws, engine, patterns, dry_run, verbose, current_user, NO_LOCK)
        return
    with single_flight(engine) as run_lock:
        if run_lock is None:
            print("\nAnother UC Bulk Import run holds the lock: this run imported nothing")
            sys.exit(LOCK_HELD_EXIT_CODE)
        try:
            run_import(args, ws, engine, patterns, dry_run, verbose, current_user, run_lock)
        except LockLostError as e:
            # Another run may be importing now: this one stops, and fails
            print(f"\n❌ {e}")
            sys.exit(1)


def run_import(args, ws, engine, patterns, dry_run, verbose, current_user,
               run_lock: RunLock = NO_LOCK):
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
            verbose=verbose,
            run_lock=run_lock,
        )
        summary['contracts'] = contract_stats
        print(f"  Created: {contract_stats['created']}, Updated: {contract_stats['updated']}, "
              f"Unchanged: {contract_stats['unchanged']}, "
              f"Skipped: {contract_stats['skipped']}, Errors: {contract_stats['errors']}")
    
    if 'product' in discovered:
        print(f"\nCreating Products...")
        product_stats = create_products(
            engine,
            discovered['product'],
            args.conflict_strategy,
            args.default_catalog,
            args.default_schema,
            dry_run=dry_run,
            verbose=verbose,
            run_lock=run_lock,
        )
        summary['products'] = product_stats
        print(f"  Created: {product_stats['created']}, Updated: {product_stats['updated']}, "
              f"Unchanged: {product_stats['unchanged']}, "
              f"Skipped: {product_stats['skipped']}, Errors: {product_stats['errors']}")
    
    if 'domain' in discovered:
        print(f"\nCreating Domains...")
        domain_stats = create_domains(
            engine,
            discovered['domain'],
            args.conflict_strategy,
            created_by=current_user,
            dry_run=dry_run,
            verbose=verbose,
            run_lock=run_lock,
        )
        summary['domains'] = domain_stats
        print(f"  Created: {domain_stats['created']}, Updated: {domain_stats['updated']}, "
              f"Unchanged: {domain_stats['unchanged']}, "
              f"Skipped: {domain_stats['skipped']}, Errors: {domain_stats['errors']}")
    
    # Link products to contracts
    if 'contract' in discovered and 'product' in discovered:
        print(f"\n" + "=" * 80)
        print("Phase 4: Linking Products to Contracts")
        print("=" * 80)
        linked = link_products_to_contracts(
            engine, discovered, dry_run=dry_run, verbose=verbose, run_lock=run_lock)
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

