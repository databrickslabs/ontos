import os
import sys
import json
import argparse
import traceback
from typing import Any, Dict, List, Optional, Tuple
from datetime import datetime, date
from decimal import Decimal
from uuid import uuid4


def json_serializer(obj):
    """Custom JSON serializer for objects not serializable by default."""
    if isinstance(obj, (datetime, date)):
        return obj.isoformat()
    if isinstance(obj, Decimal):
        return float(obj)
    raise TypeError(f"Object of type {obj.__class__.__name__} is not JSON serializable")

from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine
from pyspark.sql import SparkSession

# DQX imports
try:
    from databricks.labs.dqx.profiler.profiler import DQProfiler
    from databricks.labs.dqx.profiler.generator import DQGenerator
    from databricks.sdk import WorkspaceClient
except ImportError as e:
    print(f"WARNING: DQX imports failed: {e}")
    print("This workflow requires databricks-labs-dqx package to be installed")


# ============================================================================
# OAuth Token Generation (for Lakebase Postgres)
# ============================================================================

def get_oauth_token(ws_client: WorkspaceClient, instance_name: str) -> Tuple[str, str]:
    """Generate OAuth token for the service principal to access Lakebase Postgres.

    ``instance_name`` is either a provisioned instance name or an autoscale
    endpoint resource name (``projects/…/endpoints/…``).  The correct SDK API
    is chosen automatically.
    """
    is_autoscale = instance_name.startswith("projects/")
    print(f"  Generating OAuth token for {'autoscale' if is_autoscale else 'provisioned'} Lakebase: {instance_name}")

    current_user = ws_client.current_user.me().user_name
    print(f"  Service Principal: {current_user}")

    if is_autoscale:
        cred = ws_client.postgres.generate_database_credential(
            endpoint=instance_name,
        )
    else:
        cred = ws_client.database.generate_database_credential(
            request_id=str(uuid4()),
            instance_names=[instance_name],
        )

    print(f"  ✓ Successfully generated OAuth token")
    return current_user, cred.token


# ============================================================================
# Database Connection Utilities (inlined to avoid import issues in Databricks)
# ============================================================================

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
    host: str,
    db: str, 
    port: str, 
    schema: str,
    instance_name: str,
    ws_client: WorkspaceClient
) -> Engine:
    """Create SQLAlchemy engine using OAuth authentication."""
    from sqlalchemy import create_engine as create_sa_engine
    url, auth_user = build_db_url(host, db, port, schema, instance_name, ws_client)
    return create_sa_engine(url, pool_pre_ping=True)


def load_contract_schemas(engine: Engine, contract_id: str, schema_names: List[str]) -> List[Dict[str, Any]]:
    """Load schema details for a contract from the database."""
    print(f"Loading contract schemas from database for contract: {contract_id}")
    schema_names_sql = ",".join([f"'{name}'" for name in schema_names])
    
    sql = text(f"""
        SELECT o.id AS object_id,
               o.name AS schema_name,
               o.physical_name,
               c.name AS contract_name
        FROM data_contract_schema_objects o
        JOIN data_contracts c ON c.id = o.contract_id
        WHERE o.contract_id = :contract_id
          AND o.name IN ({schema_names_sql})
    """)
    
    with engine.connect() as conn:
        result = conn.execute(sql, {"contract_id": contract_id})
        rows = result.fetchall()
        
    schemas = []
    for row in rows:
        schemas.append({
            "object_id": row[0],
            "schema_name": row[1],
            "physical_name": row[2],
            "contract_name": row[3]
        })
    
    print(f"Found {len(schemas)} schemas: {[s['schema_name'] for s in schemas]}")
    return schemas


def update_profiling_run_status(
    engine: Engine,
    profile_run_id: str,
    status: str,
    summary_stats: Optional[str] = None,
    error_message: Optional[str] = None
):
    """Update the status of a profiling run."""
    print(f"Updating profiling run status to: {status}")
    updates = {"status": status, "completed_at": datetime.utcnow()}
    
    if summary_stats:
        updates["summary_stats"] = summary_stats
    if error_message:
        updates["error_message"] = error_message
    
    set_clause = ", ".join([f"{k} = :{k}" for k in updates.keys()])
    sql = text(f"UPDATE data_profiling_runs SET {set_clause} WHERE id = :profile_run_id")
    
    with engine.connect() as conn:
        conn.execute(sql, {**updates, "profile_run_id": profile_run_id})
        conn.commit()
    print(f"Successfully updated profiling run status to: {status}")


def insert_suggestion(
    engine: Engine,
    profile_run_id: str,
    contract_id: str,
    schema_name: str,
    property_name: Optional[str],
    dq_profile: Any,
    source: str = "dqx"
) -> str:
    """Insert a quality check suggestion into the database."""
    suggestion_id = str(uuid4())
    
    # Map DQX profile to our schema
    # DQX returns a nested structure: {'check': {'function': '...', 'arguments': {...}}, 'name': '...', 'criticality': '...'}
    if isinstance(dq_profile, dict) and 'check' in dq_profile:
        # New nested format
        check_info = dq_profile.get('check', {})
        rule_name = check_info.get('function', '')
        arguments = check_info.get('arguments', {})
        column_name = arguments.get('column', '')
        params = arguments  # Use arguments as params
        description = dq_profile.get('name', '')  # Use the human-readable name as description
        severity_map = {'error': 'error', 'warn': 'warning', 'info': 'info'}
        severity = severity_map.get(dq_profile.get('criticality', 'error'), 'error')
        print(f"    Processing check: {rule_name} for column '{column_name}'")
    elif isinstance(dq_profile, dict):
        # Old flat format (fallback)
        rule_name = dq_profile.get("name", "")
        column_name = dq_profile.get("column", "")
        description = dq_profile.get("description", "") or ""
        params = dq_profile.get("parameters") or {}
        severity = "error"
        print(f"    Processing dict check: {rule_name} for column {column_name}")
    else:
        # Object format (fallback)
        rule_name = getattr(dq_profile, "name", "")
        column_name = getattr(dq_profile, "column", "")
        description = getattr(dq_profile, "description", "") or ""
        params = getattr(dq_profile, "parameters", None) or {}
        severity = "error"
        print(f"    Processing object check: {rule_name} for column {column_name}")
    
    # Determine level
    level = "property" if property_name else "object"
    
    # Map DQX rule types to ODCS dimensions and our rule format
    dimension_map = {
        "is_not_null": "completeness",
        "is_not_null_or_empty": "completeness",
        "is_null": "completeness",  # Add this mapping
        "min_max": "conformity",
        "is_in": "conformity",
        "pattern": "conformity",
        "is_unique": "uniqueness"
    }
    
    dimension = dimension_map.get(rule_name, "accuracy")
    
    # Build the rule string based on DQX rule type
    rule_str = None
    must_be = None
    must_be_gt = None
    must_be_lt = None
    
    if rule_name == "is_not_null":
        rule_str = f"{column_name} IS NOT NULL"
    elif rule_name == "is_not_null_or_empty":
        rule_str = f"{column_name} IS NOT NULL AND {column_name} != ''"
    elif rule_name == "min_max":
        min_val = params.get("min")
        max_val = params.get("max")
        if min_val is not None:
            must_be_gt = str(min_val)
        if max_val is not None:
            must_be_lt = str(max_val)
        rule_str = f"{column_name} BETWEEN {min_val} AND {max_val}"
    elif rule_name == "is_in":
        values = params.get("values", [])
        values_str = ", ".join([f"'{v}'" for v in values])
        rule_str = f"{column_name} IN ({values_str})"
    elif rule_name == "pattern":
        pattern = params.get("pattern", "")
        rule_str = f"{column_name} MATCHES '{pattern}'"
    elif rule_name == "is_unique":
        rule_str = f"{column_name} IS UNIQUE"
    
    sql = text("""
        INSERT INTO suggested_quality_checks (
            id, profile_run_id, contract_id, source, schema_name, property_name,
            status, name, description, level, dimension, severity, type, rule,
            must_be, must_be_gt, must_be_lt, created_at
        ) VALUES (
            :id, :profile_run_id, :contract_id, :source, :schema_name, :property_name,
            :status, :name, :description, :level, :dimension, :severity, :type, :rule,
            :must_be, :must_be_gt, :must_be_lt, :created_at
        )
    """)
    
    with engine.connect() as conn:
        conn.execute(sql, {
            "id": suggestion_id,
            "profile_run_id": profile_run_id,
            "contract_id": contract_id,
            "source": source,
            "schema_name": schema_name,
            "property_name": property_name,
            "status": "pending",
            "name": rule_name,
            "description": description,
            "level": level,
            "dimension": dimension,
            "severity": severity,
            "type": "library",
            "rule": rule_str,
            "must_be": must_be,
            "must_be_gt": must_be_gt,
            "must_be_lt": must_be_lt,
            "created_at": datetime.utcnow()
        })
        conn.commit()
    
    return suggestion_id


def profile_and_generate_suggestions(
    spark: SparkSession,
    ws: WorkspaceClient,
    engine: Engine,
    profile_run_id: str,
    contract_id: str,
    schemas: List[Dict[str, Any]]
):
    """Profile tables and generate quality check suggestions using DQX."""
    print(f"Initializing DQX profiler and generator")
    profiler = DQProfiler(ws)
    generator = DQGenerator(ws)
    
    summary_data = {"tables": {}}
    total_suggestions = 0
    errors = []  # Track errors that occur
    
    print(f"Starting profiling for {len(schemas)} schemas...")
    
    for idx, schema_info in enumerate(schemas, 1):
        schema_name = schema_info["schema_name"]
        physical_name = schema_info["physical_name"]
        
        print(f"\n[{idx}/{len(schemas)}] Profiling table: {physical_name} (schema: {schema_name})")
        
        try:
            # Profile the table
            # Use moderate sampling for reasonable performance
            profile_options = {
                "sample_fraction": 0.1,  # 10% sample
                "limit": 5000,  # Max 5000 rows
                "sample_seed": 42,  # Reproducible
            }
            
            print(f"  Running profiler with options: sample_fraction=0.1, limit=5000")
            summary_stats, profiles = profiler.profile_table(
                table=physical_name,
                options=profile_options
            )
            
            print(f"  Profiler completed. Generated {len(profiles)} column profiles")
            
            # Store summary stats
            summary_data["tables"][schema_name] = {
                "physical_name": physical_name,
                "summary_stats": summary_stats,
                "profile_count": len(profiles)
            }
            
            # Generate DQ rules from profiles
            print(f"  Generating quality check rules...")
            checks = generator.generate_dq_rules(profiles, level="error")
            
            print(f"  Generated {len(checks)} quality check suggestions")
            
            # Insert suggestions into database
            print(f"  Inserting {len(checks)} suggestions into database...")
            for check_idx, check in enumerate(checks, 1):
                # Debug: print the raw check data
                if check_idx == 1:
                    print(f"    DEBUG: Sample check structure:")
                    if isinstance(check, dict):
                        print(f"      Type: dict")
                        print(f"      Keys: {list(check.keys())}")
                        print(f"      Content: {check}")
                    else:
                        print(f"      Type: {type(check)}")
                        print(f"      Dir: {[attr for attr in dir(check) if not attr.startswith('_')]}")
                
                # Extract property name from nested structure
                if isinstance(check, dict) and 'check' in check:
                    # New nested format
                    arguments = check.get('check', {}).get('arguments', {})
                    property_name = arguments.get('column')
                elif isinstance(check, dict):
                    # Old flat format
                    property_name = check.get("column")
                else:
                    # Object format
                    property_name = getattr(check, "column", None)
                
                insert_suggestion(
                    engine=engine,
                    profile_run_id=profile_run_id,
                    contract_id=contract_id,
                    schema_name=schema_name,
                    property_name=property_name,
                    dq_profile=check,
                    source="dqx"
                )
                total_suggestions += 1
            print(f"  Successfully inserted {len(checks)} suggestions")
            
        except Exception as e:
            error_msg = str(e)
            print(f"  ERROR profiling {physical_name}: {error_msg}")
            traceback.print_exc()
            summary_data["tables"][schema_name] = {
                "physical_name": physical_name,
                "error": error_msg
            }
            errors.append({
                "schema": schema_name,
                "table": physical_name,
                "error": error_msg
            })
    
    print(f"\nProfiling complete. Total suggestions generated: {total_suggestions}")
    
    # If there were errors, raise an exception to fail the job
    if errors:
        error_summary = f"Failed to profile {len(errors)} out of {len(schemas)} schema(s)"
        summary_data["total_suggestions"] = total_suggestions
        summary_data["errors"] = errors
        print(f"\n✗ {error_summary}")
        for err in errors:
            print(f"  - {err['schema']} ({err['table']}): {err['error'][:100]}")
        raise RuntimeError(error_summary)
    
    summary_data["total_suggestions"] = total_suggestions
    return json.dumps(summary_data, default=json_serializer)


def main():
    print("=" * 80)
    print("DQX Profile Datasets workflow started")
    print("=" * 80)
    
    parser = argparse.ArgumentParser(description="Profile datasets using DQX")
    parser.add_argument("--contract_id", type=str, required=True)
    parser.add_argument("--schema_names", type=str, required=True)  # JSON array
    parser.add_argument("--profile_run_id", type=str, required=True)
    parser.add_argument("--lakebase_instance_name", type=str, required=True)
    parser.add_argument("--postgres_host", type=str, required=True)
    parser.add_argument("--postgres_db", type=str, required=True)
    parser.add_argument("--postgres_port", type=str, default="5432")
    parser.add_argument("--postgres_schema", type=str, default="public")
    # Telemetry parameters (passed from app)
    parser.add_argument("--product_name", type=str, default="ontos")
    parser.add_argument("--product_version", type=str, default="0.0.0")
    args, _ = parser.parse_known_args()
    
    contract_id = args.contract_id
    schema_names = json.loads(args.schema_names)
    profile_run_id = args.profile_run_id
    lakebase_instance_name = args.lakebase_instance_name
    
    print(f"\nJob Parameters:")
    print(f"  Contract ID: {contract_id}")
    print(f"  Schema names: {schema_names}")
    print(f"  Profile run ID: {profile_run_id}")
    print(f"  Lakebase instance name: {lakebase_instance_name}")
    
    print(f"\nEnvironment Info:")
    print(f"  Python version: {sys.version}")
    
    # Initialize Workspace Client (needed for OAuth authentication)
    print("\nInitializing Databricks Workspace Client...")
    try:
        ws = WorkspaceClient(product=args.product_name, product_version=args.product_version)
        print("✓ Workspace client initialized")
    except Exception as e:
        print(f"✗ Failed to initialize workspace client: {e}")
        traceback.print_exc()
        sys.exit(1)
    
    # Connect to database using OAuth
    print("\nConnecting to database...")
    try:
        engine = create_engine_from_params(
            host=args.postgres_host,
            db=args.postgres_db,
            port=args.postgres_port,
            schema=args.postgres_schema,
            instance_name=lakebase_instance_name,
            ws_client=ws
        )
        print("✓ Database connection established successfully")
    except Exception as e:
        print(f"✗ Failed to connect to database: {e}")
        traceback.print_exc()
        sys.exit(1)
    
    # Update run status to 'running'
    try:
        update_profiling_run_status(engine, profile_run_id, "running")
    except Exception as e:
        print(f"Warning: Failed to update run status to 'running': {e}")
    
    try:
        # Load contract schemas
        print("\n" + "=" * 80)
        print("Phase 1: Loading Contract Schemas")
        print("=" * 80)
        schemas = load_contract_schemas(engine, contract_id, schema_names)
        
        if not schemas:
            raise ValueError(f"No schemas found for contract {contract_id} with names {schema_names}")
        
        print(f"✓ Loaded {len(schemas)} schemas to profile")
        for schema in schemas:
            print(f"  - {schema['schema_name']} ({schema['physical_name']})")
        
        # Initialize Spark
        print("\n" + "=" * 80)
        print("Phase 2: Initializing Spark Session")
        print("=" * 80)
        spark = SparkSession.builder.appName("DQX-Profile-Datasets").getOrCreate()
        print("✓ Spark session initialized")
        
        # Profile and generate suggestions
        print("\n" + "=" * 80)
        print("Phase 3: Profiling Tables and Generating Suggestions")
        print("=" * 80)
        summary_stats = profile_and_generate_suggestions(
            spark=spark,
            ws=ws,
            engine=engine,
            profile_run_id=profile_run_id,
            contract_id=contract_id,
            schemas=schemas
        )
        
        # Update run status to 'completed'
        print("\n" + "=" * 80)
        print("Phase 4: Finalizing")
        print("=" * 80)
        update_profiling_run_status(
            engine,
            profile_run_id,
            "completed",
            summary_stats=summary_stats
        )
        
        print("\n" + "=" * 80)
        print("✓ DQX Profile Datasets workflow completed successfully!")
        print("=" * 80)
        
    except Exception as e:
        print("\n" + "=" * 80)
        print(f"✗ Workflow failed with error: {e}")
        print("=" * 80)
        traceback.print_exc()
        
        # Update run status to 'failed'
        # Try with existing engine first, if that fails, create a new one
        try:
            update_profiling_run_status(
                engine,
                profile_run_id,
                "failed",
                error_message=str(e)
            )
        except Exception as update_error:
            print(f"Warning: Failed to update run status with existing engine: {update_error}")
            print("Attempting to create new database connection to update status...")
            try:
                # Create fresh engine for status update
                new_engine = create_engine_from_params(
                    host=args.postgres_host,
                    db=args.postgres_db,
                    port=args.postgres_port,
                    schema=args.postgres_schema,
                    instance_name=lakebase_instance_name,
                    ws_client=ws
                )
                update_profiling_run_status(
                    new_engine,
                    profile_run_id,
                    "failed",
                    error_message=str(e)
                )
                print("✓ Successfully updated status to 'failed' with new connection")
                new_engine.dispose()
            except Exception as final_error:
                print(f"✗ Failed to update run status even with new connection: {final_error}")
                print("Status will remain as 'running' - manual intervention may be required")
        
        sys.exit(1)


if __name__ == "__main__":
    main()

