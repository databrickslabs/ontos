"""
Data Contract Validation Workflow

Validates active data contracts against Unity Catalog for:
- Schema drift (columns, types)
- Access privileges compliance
- SLA compliance (data freshness)
- Data quality report status
"""

import os
import json
import argparse
from typing import Any, Dict, List, Optional, Tuple
from datetime import datetime, timedelta
from uuid import uuid4

from pyspark.sql import SparkSession
from sqlalchemy import text, create_engine
from sqlalchemy.engine import Engine

from databricks.sdk import WorkspaceClient


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
# Validation Run Management
# ============================================================================

def create_validation_run(engine: Engine, contract_id: str) -> str:
    """Create a new validation run record and return its ID."""
    run_id = str(uuid4())
    sql = text("""
        INSERT INTO data_contract_validation_runs (
            id, contract_id, status, started_at, checks_passed, checks_failed, score
        ) VALUES (
            :id, :contract_id, :status, :started_at, :checks_passed, :checks_failed, :score
        )
    """)

    with engine.connect() as conn:
        conn.execute(sql, {
            "id": run_id,
            "contract_id": contract_id,
            "status": "running",
            "started_at": datetime.utcnow(),
            "checks_passed": 0,
            "checks_failed": 0,
            "score": 0.0
        })
        conn.commit()

    return run_id


def store_validation_result(
    engine: Engine,
    run_id: str,
    contract_id: str,
    check_type: str,
    passed: bool,
    message: str,
    details_json: Optional[str] = None
) -> None:
    """Store a single validation result."""
    result_id = str(uuid4())
    sql = text("""
        INSERT INTO data_contract_validation_results (
            id, run_id, contract_id, check_type, passed, message, details_json, created_at
        ) VALUES (
            :id, :run_id, :contract_id, :check_type, :passed, :message, :details_json, :created_at
        )
    """)

    with engine.connect() as conn:
        conn.execute(sql, {
            "id": result_id,
            "run_id": run_id,
            "contract_id": contract_id,
            "check_type": check_type,
            "passed": passed,
            "message": message,
            "details_json": details_json,
            "created_at": datetime.utcnow()
        })
        conn.commit()


def complete_validation_run(
    engine: Engine,
    run_id: str,
    checks_passed: int,
    checks_failed: int,
    score: float,
    error_message: Optional[str] = None
) -> None:
    """Complete a validation run with final counts and score."""
    status = "succeeded" if error_message is None else "failed"
    sql = text("""
        UPDATE data_contract_validation_runs
        SET status = :status,
            finished_at = :finished_at,
            checks_passed = :checks_passed,
            checks_failed = :checks_failed,
            score = :score,
            error_message = :error_message
        WHERE id = :id
    """)

    with engine.connect() as conn:
        conn.execute(sql, {
            "id": run_id,
            "status": status,
            "finished_at": datetime.utcnow(),
            "checks_passed": checks_passed,
            "checks_failed": checks_failed,
            "score": score,
            "error_message": error_message
        })
        conn.commit()


# ============================================================================
# Contract Loading
# ============================================================================

def load_active_contracts_from_uc(
    spark: SparkSession,
    catalog: str,
    schema: str,
    statuses: List[str]
) -> List[Dict[str, Any]]:
    """Load active contracts and their schema/properties from UC-backed Lakehouse tables."""
    cte = f"{catalog}.{schema}"

    # Build status filter
    status_list = "','".join(s.lower() for s in statuses)
    status_filter = f"lower(c.status) IN ('{status_list}')"

    df = spark.sql(
        f"""
        SELECT c.id AS contract_id,
               c.name AS contract_name,
               o.id AS object_id,
               o.name AS object_name,
               o.physical_name AS physical_name,
               p.name AS prop_name,
               p.logical_type AS prop_type
        FROM {cte}.data_contracts c
        JOIN {cte}.data_contract_schema_objects o
          ON o.contract_id = c.id
        LEFT JOIN {cte}.data_contract_schema_properties p
          ON p.object_id = o.id
        WHERE {status_filter}
        """
    )

    # Group rows into contracts
    rows = df.collect()
    contracts_by_id: Dict[str, Dict[str, Any]] = {}

    for r in rows:
        cid = r["contract_id"]
        cname = r["contract_name"]
        oid = r["object_id"]
        oname = r["object_name"]
        physical_name = r["physical_name"]
        prop_name = r["prop_name"]
        prop_type = r["prop_type"]

        contract = contracts_by_id.setdefault(cid, {
            "id": cid,
            "name": cname,
            "schema": {}
        })

        schema_obj = contract["schema"].setdefault(oid, {
            "id": oid,
            "name": oname,
            "physicalName": physical_name,
            "properties": {}
        })

        if prop_name:
            schema_obj["properties"][prop_name] = {
                "name": str(prop_name),
                "type": str(prop_type) if prop_type else None
            }

    # Convert to list format
    result: List[Dict[str, Any]] = []
    for contract in contracts_by_id.values():
        schema_list = []
        for schema_obj in contract["schema"].values():
            schema_obj["properties"] = list(schema_obj["properties"].values())
            schema_list.append(schema_obj)
        contract["schema"] = schema_list
        result.append(contract)

    return result


def qualify_uc_name(physical_name: str, default_catalog: Optional[str], default_schema: Optional[str]) -> Optional[str]:
    """Return a fully qualified UC table name catalog.schema.table if possible."""
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


# ============================================================================
# Validation Checks
# ============================================================================

def check_schema_drift(
    spark: SparkSession,
    qualified_name: str,
    contract_properties: List[Dict[str, Any]]
) -> Tuple[bool, str, Dict[str, Any]]:
    """Check if table schema matches contract schema.

    Returns: (passed, message, details)
    """
    try:
        # Get actual table schema
        df = spark.sql(f"DESCRIBE TABLE {qualified_name}")
        actual_columns = {row.col_name.lower(): row.data_type.lower() for row in df.collect() if row.col_name and not row.col_name.startswith('#')}

        # Build expected schema from contract
        expected_columns = {prop["name"].lower(): prop.get("type", "").lower() for prop in contract_properties if prop.get("name")}

        # Check for missing columns
        missing = set(expected_columns.keys()) - set(actual_columns.keys())
        # Check for extra columns
        extra = set(actual_columns.keys()) - set(expected_columns.keys())
        # Check for type mismatches
        type_mismatches = []
        for col in expected_columns:
            if col in actual_columns:
                expected_type = expected_columns[col]
                actual_type = actual_columns[col]
                # Simple type matching (could be more sophisticated)
                if expected_type and actual_type and expected_type not in actual_type and actual_type not in expected_type:
                    type_mismatches.append(f"{col}: expected {expected_type}, got {actual_type}")

        details = {
            "missing_columns": list(missing),
            "extra_columns": list(extra),
            "type_mismatches": type_mismatches
        }

        passed = len(missing) == 0 and len(type_mismatches) == 0

        if passed:
            message = f"Schema matches contract ({len(expected_columns)} columns)"
            if extra:
                message += f" (with {len(extra)} extra columns)"
        else:
            issues = []
            if missing:
                issues.append(f"{len(missing)} missing columns")
            if type_mismatches:
                issues.append(f"{len(type_mismatches)} type mismatches")
            message = f"Schema drift detected: {', '.join(issues)}"

        return (passed, message, details)

    except Exception as e:
        return (False, f"Failed to check schema: {str(e)}", {"error": str(e)})


def check_table_freshness(
    spark: SparkSession,
    qualified_name: str,
    max_age_hours: int = 24
) -> Tuple[bool, str]:
    """Check if table data is fresh (updated within max_age_hours).

    Returns: (passed, message)
    """
    try:
        # Use DESCRIBE DETAIL to get last modified time
        df = spark.sql(f"DESCRIBE DETAIL {qualified_name}")
        row = df.collect()[0]

        last_modified = row.lastModified if hasattr(row, 'lastModified') else None

        if not last_modified:
            return (False, "Unable to determine table freshness")

        # Calculate age
        if isinstance(last_modified, str):
            last_modified = datetime.fromisoformat(last_modified.replace('Z', '+00:00'))

        age = datetime.now() - last_modified.replace(tzinfo=None)
        age_hours = age.total_seconds() / 3600

        passed = age_hours <= max_age_hours
        message = f"Table age: {age_hours:.1f}h (max: {max_age_hours}h) - {'OK' if passed else 'STALE'}"

        return (passed, message)

    except Exception as e:
        return (False, f"Failed to check freshness: {str(e)}")


def check_dq_status(
    engine: Engine,
    contract_id: str,
    min_score: float = 95.0
) -> Tuple[bool, str]:
    """Check latest DQ check status for contract.

    Returns: (passed, message)
    """
    try:
        sql = text("""
            SELECT score, status, finished_at
            FROM data_quality_check_runs
            WHERE contract_id = :contract_id
            ORDER BY started_at DESC
            LIMIT 1
        """)

        with engine.connect() as conn:
            result = conn.execute(sql, {"contract_id": contract_id})
            row = result.fetchone()

        if not row:
            return (False, "No DQ checks found for contract")

        score = row[0] if row[0] is not None else 0.0
        status = row[1]
        finished_at = row[2]

        if status != "succeeded":
            return (False, f"Latest DQ check failed (status: {status})")

        passed = score >= min_score
        message = f"DQ score: {score:.1f}% (min: {min_score}%) - {'OK' if passed else 'BELOW THRESHOLD'}"

        return (passed, message)

    except Exception as e:
        return (False, f"Failed to check DQ status: {str(e)}")


# ============================================================================
# Main Validation Logic
# ============================================================================

def validate_contract(
    spark: SparkSession,
    ws_client: WorkspaceClient,
    engine: Engine,
    contract: Dict[str, Any],
    default_catalog: Optional[str],
    default_schema: Optional[str],
    config: Dict[str, Any]
) -> Tuple[int, int]:
    """Run validation checks for a contract and store results.

    Returns: (passed_count, failed_count)
    """
    contract_id = contract.get("id") or "unknown"
    contract_name = contract.get("name") or contract_id
    schema_objs: List[Dict[str, Any]] = contract.get("schema") or []

    print(f"\n[VALIDATE] {contract_name}")

    # Create run record
    run_id = create_validation_run(engine, contract_id)

    checks_passed = 0
    checks_failed = 0

    try:
        for schema_obj in schema_objs:
            physical_name = schema_obj.get("physicalName") or schema_obj.get("physical_name")
            qualified = qualify_uc_name(str(physical_name) if physical_name else "", default_catalog, default_schema)

            if not qualified:
                print(f"  [SKIP] No resolvable physical name for {schema_obj.get('name')}")
                continue

            print(f"  Checking: {qualified}")

            # Schema Drift Check
            if config.get("schema_drift_check_enabled", True):
                passed, message, details = check_schema_drift(
                    spark,
                    qualified,
                    schema_obj.get("properties", [])
                )
                store_validation_result(
                    engine, run_id, contract_id, "schema_drift",
                    passed, message, json.dumps(details)
                )
                print(f"    - Schema drift: {message}")
                if passed:
                    checks_passed += 1
                else:
                    checks_failed += 1

            # SLA/Freshness Check
            if config.get("sla_check_enabled", True):
                max_age_hours = config.get("sla_max_age_hours", 24)
                passed, message = check_table_freshness(spark, qualified, max_age_hours)
                store_validation_result(
                    engine, run_id, contract_id, "sla",
                    passed, message, None
                )
                print(f"    - SLA/Freshness: {message}")
                if passed:
                    checks_passed += 1
                else:
                    checks_failed += 1

        # DQ Status Check (once per contract, not per table)
        if config.get("dq_check_enabled", True):
            min_score = config.get("dq_score_threshold", 95.0)
            passed, message = check_dq_status(engine, contract_id, min_score)
            store_validation_result(
                engine, run_id, contract_id, "dq",
                passed, message, None
            )
            print(f"    - DQ Status: {message}")
            if passed:
                checks_passed += 1
            else:
                checks_failed += 1

        # Complete run
        total = max(1, checks_passed + checks_failed)
        score = round(100.0 * (checks_passed / total), 2)
        complete_validation_run(engine, run_id, checks_passed, checks_failed, score)

        print(f"  Score: {score}% ({checks_passed} passed, {checks_failed} failed)")

        return (checks_passed, checks_failed)

    except Exception as e:
        # Complete run with error
        total = max(1, checks_passed + checks_failed)
        score = round(100.0 * (checks_passed / total), 2) if total > 0 else 0.0
        complete_validation_run(engine, run_id, checks_passed, checks_failed, score, str(e))
        print(f"  ERROR: {e}")
        raise


# ============================================================================
# Main Workflow
# ============================================================================

def main() -> None:
    print("Data Contract Validation workflow started")

    parser = argparse.ArgumentParser(description="Validate data contracts against Unity Catalog")
    parser.add_argument("--catalog", type=str, default=os.environ.get("DATABRICKS_CATALOG"))
    parser.add_argument("--schema", type=str, default=os.environ.get("DATABRICKS_SCHEMA"))
    parser.add_argument("--contract_statuses", type=str, default='["active", "certified"]')
    parser.add_argument("--schema_drift_check_enabled", type=str, default="true")
    parser.add_argument("--sla_check_enabled", type=str, default="true")
    parser.add_argument("--sla_max_age_hours", type=str, default="24")
    parser.add_argument("--dq_check_enabled", type=str, default="true")
    parser.add_argument("--dq_score_threshold", type=str, default="95.0")
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

    args, _ = parser.parse_known_args()

    # Parse arguments
    try:
        contract_statuses = json.loads(args.contract_statuses)
    except Exception:
        contract_statuses = ["active", "certified"]

    config = {
        "schema_drift_check_enabled": args.schema_drift_check_enabled.lower() == "true",
        "sla_check_enabled": args.sla_check_enabled.lower() == "true",
        "sla_max_age_hours": int(args.sla_max_age_hours),
        "dq_check_enabled": args.dq_check_enabled.lower() == "true",
        "dq_score_threshold": float(args.dq_score_threshold),
        "verbose": args.verbose.lower() == "true"
    }

    # Initialize Spark
    spark = SparkSession.builder.appName("Ontos-Contract-Validation").getOrCreate()

    # Defaults for partially-qualified physical names
    default_catalog = args.catalog or os.environ.get("DATABRICKS_CATALOG")
    default_schema = args.schema or os.environ.get("DATABRICKS_SCHEMA")

    if not default_catalog or not default_schema:
        print("Catalog/schema not provided; set --catalog/--schema or DATABRICKS_CATALOG/SCHEMA.")
        return

    # Initialize workspace client
    print("\nInitializing workspace client...")
    ws = WorkspaceClient(product=args.product_name, product_version=args.product_version)
    print("  ✓ Workspace client initialized")

    # Connect to database
    print("\nConnecting to database...")
    engine = create_engine_from_params(
        ws_client=ws,
        host=args.postgres_host,
        db=args.postgres_db,
        port=args.postgres_port,
        schema=args.postgres_schema,
        instance_name=args.lakebase_instance_name
    )
    print("  ✓ Database connection established")

    # Load contracts
    print(f"\nLoading contracts with statuses: {contract_statuses}")
    try:
        contracts = load_active_contracts_from_uc(spark, default_catalog, default_schema, contract_statuses)
    except Exception as e:
        print(f"Failed loading contracts from UC: {e}")
        return

    if not contracts:
        print("No contracts found matching criteria. Exiting.")
        return

    print(f"Found {len(contracts)} contracts to validate")

    # Validate each contract
    total_passed = 0
    total_failed = 0

    for contract in contracts:
        try:
            passed, failed = validate_contract(
                spark, ws, engine, contract,
                default_catalog, default_schema, config
            )
            total_passed += passed
            total_failed += failed
        except Exception as e:
            name = contract.get("name") or contract.get("id") or "unknown"
            print(f"[ERROR] Contract {name} validation failed: {e}")
            total_failed += 1

    # Summary
    total = max(1, total_passed + total_failed)
    overall_score = round(100.0 * (total_passed / total), 2)

    print("\n" + "=" * 80)
    print("Data Contract Validation workflow completed")
    print("=" * 80)
    print(f"Total checks passed: {total_passed}")
    print(f"Total checks failed: {total_failed}")
    print(f"Overall score: {overall_score}%")
    print("")


if __name__ == "__main__":
    main()
