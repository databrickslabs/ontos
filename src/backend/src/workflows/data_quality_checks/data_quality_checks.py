import os
import re
import json
import argparse
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from datetime import datetime
from uuid import uuid4

import yaml
from pyspark.sql import SparkSession, DataFrame
from pyspark.sql import functions as F
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
# Data Quality Check Result Storage
# ============================================================================

def create_dq_run(engine: Engine, contract_id: str) -> str:
    """Create a new DQ check run record and return its ID."""
    run_id = str(uuid4())
    sql = text("""
        INSERT INTO data_quality_check_runs (
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


def store_dq_result(
    engine: Engine,
    run_id: str,
    contract_id: str,
    object_name: str,
    check_type: str,
    column_name: Optional[str],
    passed: bool,
    violations_count: int,
    message: str
) -> None:
    """Store a single DQ check result."""
    result_id = str(uuid4())
    sql = text("""
        INSERT INTO data_quality_check_results (
            id, run_id, contract_id, object_name, check_type, column_name,
            passed, violations_count, message, created_at
        ) VALUES (
            :id, :run_id, :contract_id, :object_name, :check_type, :column_name,
            :passed, :violations_count, :message, :created_at
        )
    """)

    with engine.connect() as conn:
        conn.execute(sql, {
            "id": result_id,
            "run_id": run_id,
            "contract_id": contract_id,
            "object_name": object_name,
            "check_type": check_type,
            "column_name": column_name,
            "passed": passed,
            "violations_count": violations_count,
            "message": message,
            "created_at": datetime.utcnow()
        })
        conn.commit()


def complete_dq_run(
    engine: Engine,
    run_id: str,
    checks_passed: int,
    checks_failed: int,
    score: float,
    error_message: Optional[str] = None
) -> None:
    """Complete a DQ check run with final counts and score."""
    status = "succeeded" if error_message is None else "failed"
    sql = text("""
        UPDATE data_quality_check_runs
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
# Contract Loading & DQ Checks (existing logic)
# ============================================================================

def load_active_contracts_from_uc(spark: SparkSession, catalog: str, schema: str, statuses: List[str]) -> List[Dict[str, Any]]:
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
               p.required AS prop_required,
               p.unique AS prop_unique,
               p.logical_type_options_json AS prop_opts
        FROM {cte}.data_contracts c
        JOIN {cte}.data_contract_schema_objects o
          ON o.contract_id = c.id
        LEFT JOIN {cte}.data_contract_schema_properties p
          ON p.object_id = o.id
        WHERE {status_filter}
        """
    )

    # Group rows into contracts -> schema objects -> properties
    rows = df.collect()
    contracts_by_id: Dict[str, Dict[str, Any]] = {}
    for r in rows:
        cid = r["contract_id"]
        cname = r["contract_name"]
        oid = r["object_id"]
        oname = r["object_name"]
        physical_name = r["physical_name"]
        prop_name = r["prop_name"]
        prop_required = bool(r["prop_required"]) if r["prop_required"] is not None else False
        prop_unique = bool(r["prop_unique"]) if r["prop_unique"] is not None else False
        prop_opts_raw = r["prop_opts"]
        prop_opts: Dict[str, Any] = {}
        if isinstance(prop_opts_raw, str) and prop_opts_raw:
            try:
                prop_opts = json.loads(prop_opts_raw)
            except Exception:
                prop_opts = {}

        contract = contracts_by_id.setdefault(cid, {
            "id": cid,
            "name": cname,
            "schema": {}
        })
        schema_obj = contract["schema"].setdefault(oid, {
            "id": oid,
            "name": oname,
            "physicalName": physical_name,
            "properties": []
        })

        if prop_name:
            prop_dict: Dict[str, Any] = {
                "name": str(prop_name),
                "required": prop_required,
                "unique": prop_unique,
            }
            # Map common ODCS options if present
            if isinstance(prop_opts, dict):
                if prop_opts.get("minLength") is not None:
                    prop_dict["minLength"] = prop_opts.get("minLength")
                if prop_opts.get("maxLength") is not None:
                    prop_dict["maxLength"] = prop_opts.get("maxLength")
                if prop_opts.get("minimum") is not None:
                    prop_dict["minimum"] = prop_opts.get("minimum")
                if prop_opts.get("maximum") is not None:
                    prop_dict["maximum"] = prop_opts.get("maximum")
                if prop_opts.get("pattern"):
                    prop_dict["pattern"] = prop_opts.get("pattern")
            schema_obj["properties"].append(prop_dict)

    # Convert schema maps to arrays
    result: List[Dict[str, Any]] = []
    for contract in contracts_by_id.values():
        schema_list = list(contract["schema"].values())
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


def column_exists(df: DataFrame, column_name: str) -> bool:
    return column_name in [c.lower() for c in df.columns]


def evaluate_required_columns(df: DataFrame, columns: List[str]) -> List[Tuple[str, bool, int]]:
    """Check that required columns have no nulls. Returns (column, passed, null_count)."""
    if not columns:
        return []
    # Compute null counts in one pass
    agg_exprs = [F.sum(F.col(c).isNull().cast("int")).alias(c) for c in columns if column_exists(df, c)]
    if not agg_exprs:
        return []
    row = df.agg(*agg_exprs).collect()[0]
    results: List[Tuple[str, bool, int]] = []
    for c in columns:
        if not column_exists(df, c):
            continue
        nulls = int(row[c])
        results.append((c, nulls == 0, nulls))
    return results


def evaluate_unique_columns(df: DataFrame, columns: List[str]) -> List[Tuple[str, bool, int]]:
    """Check that columns are unique. Returns (column, passed, duplicate_groups)."""
    results: List[Tuple[str, bool, int]] = []
    for c in columns:
        if not column_exists(df, c):
            continue
        dup_groups = df.groupBy(F.col(c)).count().filter(F.col("count") > 1).limit(1).count()
        results.append((c, dup_groups == 0, dup_groups))
    return results


def evaluate_numeric_ranges(df: DataFrame, col_specs: List[Tuple[str, Optional[float], Optional[float]]]) -> List[Tuple[str, bool, int]]:
    """Check numeric ranges; returns (column, passed, out_of_range_count)."""
    results: List[Tuple[str, bool, int]] = []
    for c, min_val, max_val in col_specs:
        if not column_exists(df, c):
            continue
        col_expr = F.col(c).cast("double")
        conds = []
        if min_val is not None:
            conds.append(col_expr < F.lit(float(min_val)))
        if max_val is not None:
            conds.append(col_expr > F.lit(float(max_val)))
        if not conds:
            continue
        out_of_range = df.select(F.sum(F.when(conds[0] if len(conds) == 1 else (conds[0] | conds[1]), 1).otherwise(0)).alias("cnt")).collect()[0]["cnt"]
        results.append((c, int(out_of_range) == 0, int(out_of_range)))
    return results


def evaluate_string_lengths(df: DataFrame, col_specs: List[Tuple[str, Optional[int], Optional[int]]]) -> List[Tuple[str, bool, int]]:
    """Check string min/max lengths; returns (column, passed, violations)."""
    results: List[Tuple[str, bool, int]] = []
    for c, min_len, max_len in col_specs:
        if not column_exists(df, c):
            continue
        length_expr = F.length(F.col(c).cast("string"))
        conds = []
        if min_len is not None:
            conds.append(length_expr < F.lit(int(min_len)))
        if max_len is not None:
            conds.append(length_expr > F.lit(int(max_len)))
        if not conds:
            continue
        violations = df.select(F.sum(F.when(conds[0] if len(conds) == 1 else (conds[0] | conds[1]), 1).otherwise(0)).alias("cnt")).collect()[0]["cnt"]
        results.append((c, int(violations) == 0, int(violations)))
    return results


def evaluate_regex_patterns(df: DataFrame, specs: List[Tuple[str, str]]) -> List[Tuple[str, bool, int]]:
    """Check regex patterns; returns (column, passed, non_matching_count)."""
    results: List[Tuple[str, bool, int]] = []
    for c, pattern in specs:
        if not column_exists(df, c):
            continue
        # Use Spark SQL rlike (Java regex). Best-effort for Python patterns; escape if obviously invalid.
        try:
            re.compile(pattern)
        except re.error:
            # Skip invalid user pattern
            results.append((c, True, 0))
            continue
        nonmatch = df.select(F.sum(F.when(~F.col(c).cast("string").rlike(pattern), 1).otherwise(0)).alias("cnt")).collect()[0]["cnt"]
        results.append((c, int(nonmatch) == 0, int(nonmatch)))
    return results


def run_contract_checks(
    spark: SparkSession,
    engine: Engine,
    contract: Dict[str, Any],
    default_catalog: Optional[str],
    default_schema: Optional[str]
) -> Tuple[int, int]:
    """Run DQ checks for a contract and store results. Returns (passed_count, failed_count)."""
    contract_id = contract.get("id") or "unknown"
    contract_name = contract.get("name") or contract_id
    schema_objs: List[Dict[str, Any]] = contract.get("schema") or []

    # Create run record
    run_id = create_dq_run(engine, contract_id)

    checks_passed = 0
    checks_failed = 0

    try:
        for schema_obj in schema_objs:
            physical_name = schema_obj.get("physicalName") or schema_obj.get("physical_name")
            qualified = qualify_uc_name(str(physical_name) if physical_name else "", default_catalog, default_schema)
            if not qualified:
                print(f"[SKIP] {contract_name}: schema '{schema_obj.get('name')}' has no resolvable physicalName")
                continue

            try:
                df = spark.table(qualified)
            except Exception as e:
                print(f"[ERROR] {contract_name}: failed to read table {qualified}: {e}")
                store_dq_result(
                    engine, run_id, contract_id, qualified, "table_access", None,
                    False, 0, f"Failed to read table: {e}"
                )
                checks_failed += 1
                continue

            properties: List[Dict[str, Any]] = schema_obj.get("properties") or []
            required_cols = [str(p.get("name")) for p in properties if p.get("required") is True and p.get("name")]
            unique_cols = [str(p.get("name")) for p in properties if p.get("unique") is True and p.get("name")]
            range_specs: List[Tuple[str, Optional[float], Optional[float]]] = []
            length_specs: List[Tuple[str, Optional[int], Optional[int]]] = []
            pattern_specs: List[Tuple[str, str]] = []

            for p in properties:
                col_name = p.get("name")
                if not col_name:
                    continue
                min_val = p.get("minimum")
                max_val = p.get("maximum")
                if min_val is not None or max_val is not None:
                    try:
                        range_specs.append((str(col_name), float(min_val) if min_val is not None else None, float(max_val) if max_val is not None else None))
                    except Exception:
                        pass
                min_len = p.get("minLength")
                max_len = p.get("maxLength")
                if min_len is not None or max_len is not None:
                    try:
                        length_specs.append((str(col_name), int(min_len) if min_len is not None else None, int(max_len) if max_len is not None else None))
                    except Exception:
                        pass
                pattern_val = p.get("pattern")
                if isinstance(pattern_val, str) and pattern_val:
                    pattern_specs.append((str(col_name), pattern_val))

            # Required
            for col_name, passed, nulls in evaluate_required_columns(df, required_cols):
                msg = f"required({col_name})={'OK' if passed else 'FAIL'} nulls={nulls}"
                print(f"[DQ] {contract_name} | {qualified} -> {msg}")
                store_dq_result(engine, run_id, contract_id, qualified, "required", col_name, passed, nulls, msg)
                if passed:
                    checks_passed += 1
                else:
                    checks_failed += 1

            # Unique
            for col_name, passed, dup_groups in evaluate_unique_columns(df, unique_cols):
                msg = f"unique({col_name})={'OK' if passed else 'FAIL'} duplicate_groups={dup_groups}"
                print(f"[DQ] {contract_name} | {qualified} -> {msg}")
                store_dq_result(engine, run_id, contract_id, qualified, "unique", col_name, passed, dup_groups, msg)
                if passed:
                    checks_passed += 1
                else:
                    checks_failed += 1

            # Ranges
            for col_name, passed, violations in evaluate_numeric_ranges(df, range_specs):
                msg = f"range({col_name})={'OK' if passed else 'FAIL'} violations={violations}"
                print(f"[DQ] {contract_name} | {qualified} -> {msg}")
                store_dq_result(engine, run_id, contract_id, qualified, "range", col_name, passed, violations, msg)
                if passed:
                    checks_passed += 1
                else:
                    checks_failed += 1

            # Lengths
            for col_name, passed, violations in evaluate_string_lengths(df, length_specs):
                msg = f"length({col_name})={'OK' if passed else 'FAIL'} violations={violations}"
                print(f"[DQ] {contract_name} | {qualified} -> {msg}")
                store_dq_result(engine, run_id, contract_id, qualified, "length", col_name, passed, violations, msg)
                if passed:
                    checks_passed += 1
                else:
                    checks_failed += 1

            # Patterns
            for col_name, passed, violations in evaluate_regex_patterns(df, pattern_specs):
                msg = f"pattern({col_name})={'OK' if passed else 'FAIL'} violations={violations}"
                print(f"[DQ] {contract_name} | {qualified} -> {msg}")
                store_dq_result(engine, run_id, contract_id, qualified, "pattern", col_name, passed, violations, msg)
                if passed:
                    checks_passed += 1
                else:
                    checks_failed += 1

        # Complete run
        total = max(1, checks_passed + checks_failed)
        score = round(100.0 * (checks_passed / total), 2)
        complete_dq_run(engine, run_id, checks_passed, checks_failed, score)

        return (checks_passed, checks_failed)

    except Exception as e:
        # Complete run with error
        total = max(1, checks_passed + checks_failed)
        score = round(100.0 * (checks_passed / total), 2) if total > 0 else 0.0
        complete_dq_run(engine, run_id, checks_passed, checks_failed, score, str(e))
        raise


def main() -> None:
    print("Data Quality Checks workflow started")

    parser = argparse.ArgumentParser(description="Run data quality checks for active contracts")
    parser.add_argument("--catalog", type=str, default=os.environ.get("DATABRICKS_CATALOG"))
    parser.add_argument("--schema", type=str, default=os.environ.get("DATABRICKS_SCHEMA"))
    parser.add_argument("--contract_statuses", type=str, default='["active", "certified"]')
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
    verbose = args.verbose.lower() == "true"

    spark = SparkSession.builder.appName("Ontos-DataQuality-Checks").getOrCreate()

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

    # Load from Lakehouse federated UC tables
    print(f"\nLoading contracts with statuses: {contract_statuses}")
    try:
        contracts = load_active_contracts_from_uc(spark, default_catalog, default_schema, contract_statuses)
    except Exception as e:
        print(f"Failed loading contracts from UC: {e}")
        return

    if not contracts:
        print("No contracts found matching criteria. Exiting.")
        return

    print(f"Found {len(contracts)} contracts to check")

    total_passed = 0
    total_failed = 0

    for contract in contracts:
        try:
            passed, failed = run_contract_checks(spark, engine, contract, default_catalog, default_schema)
            total_passed += passed
            total_failed += failed
        except Exception as e:
            name = contract.get("name") or contract.get("id") or "unknown"
            print(f"[ERROR] Contract {name} failed with error: {e}")
            total_failed += 1

    total = max(1, total_passed + total_failed)
    overall_score = round(100.0 * (total_passed / total), 2)

    print("\n" + "=" * 80)
    print("Data Quality Checks workflow completed")
    print("=" * 80)
    print(f"Total checks passed: {total_passed}")
    print(f"Total checks failed: {total_failed}")
    print(f"Overall score: {overall_score}%")
    print("")


if __name__ == "__main__":
    main()
