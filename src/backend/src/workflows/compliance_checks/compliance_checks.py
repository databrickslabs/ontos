"""
Compliance Checks Workflow

Runs user-defined compliance DSL rules from the compliance_policies table.
Uses the existing ComplianceManager infrastructure for rule evaluation.
"""

import os
import sys
import json
import argparse
from typing import Any, Dict, List, Optional, Tuple
from datetime import datetime
from uuid import uuid4
from pathlib import Path

# Add parent directory to path to enable imports from src.*
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from sqlalchemy import text, create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

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
# Policy Loading & Execution
# ============================================================================

def load_policies(
    engine: Engine,
    policy_filter: str,
    categories: Optional[List[str]],
    severities: Optional[List[str]]
) -> List[Any]:
    """Load compliance policies based on filters.

    Args:
        engine: Database engine
        policy_filter: 'all', 'active', or JSON array of policy IDs
        categories: Optional list of categories to filter
        severities: Optional list of severities to filter

    Returns:
        List of policy dictionaries
    """
    # Build WHERE clause
    conditions = []

    if policy_filter == 'active':
        conditions.append("is_active = TRUE")
    elif policy_filter != 'all':
        # Try to parse as JSON array of IDs
        try:
            policy_ids = json.loads(policy_filter)
            if isinstance(policy_ids, list) and policy_ids:
                id_list = "','".join(policy_ids)
                conditions.append(f"id IN ('{id_list}')")
        except Exception:
            print(f"Warning: Unable to parse policy_filter as JSON, using 'active' filter")
            conditions.append("is_active = TRUE")

    if categories:
        cat_list = "','".join(categories)
        conditions.append(f"category IN ('{cat_list}')")

    if severities:
        sev_list = "','".join(severities)
        conditions.append(f"severity IN ('{sev_list}')")

    where_clause = " AND ".join(conditions) if conditions else "1=1"

    sql = text(f"""
        SELECT id, name, description, rule, category, severity, is_active
        FROM compliance_policies
        WHERE {where_clause}
        ORDER BY severity DESC, name
    """)

    with engine.connect() as conn:
        result = conn.execute(sql)
        policies = []
        for row in result:
            policies.append({
                "id": row[0],
                "name": row[1],
                "description": row[2],
                "rule": row[3],
                "category": row[4],
                "severity": row[5],
                "is_active": row[6]
            })

    return policies


def run_policy(
    db: Session,
    policy: Dict[str, Any],
    manager: Any,
    entity_limit: Optional[int]
) -> Dict[str, Any]:
    """Run a single compliance policy.

    Returns:
        Dict with run statistics
    """
    from src.db_models.compliance import CompliancePolicyDb

    print(f"\n[POLICY] {policy['name']}")
    print(f"  Category: {policy.get('category', 'N/A')}")
    print(f"  Severity: {policy.get('severity', 'N/A')}")

    # Get policy from database as DB object
    policy_db = db.get(CompliancePolicyDb, policy['id'])
    if not policy_db:
        print(f"  ERROR: Policy not found in database")
        return {
            "policy_id": policy['id'],
            "policy_name": policy['name'],
            "status": "error",
            "error": "Policy not found"
        }

    try:
        # Run policy using ComplianceManager
        run = manager.run_policy_inline(db, policy=policy_db, limit=entity_limit)

        print(f"  Run ID: {run.id}")
        print(f"  Status: {run.status}")
        print(f"  Passed: {run.success_count}")
        print(f"  Failed: {run.failure_count}")
        print(f"  Score: {run.score}%")

        return {
            "policy_id": policy['id'],
            "policy_name": policy['name'],
            "run_id": run.id,
            "status": run.status,
            "success_count": run.success_count,
            "failure_count": run.failure_count,
            "score": run.score,
            "error": run.error_message
        }

    except Exception as e:
        print(f"  ERROR: {e}")
        return {
            "policy_id": policy['id'],
            "policy_name": policy['name'],
            "status": "error",
            "error": str(e)
        }


# ============================================================================
# Main Workflow
# ============================================================================

def main() -> None:
    print("Compliance Checks workflow started")

    parser = argparse.ArgumentParser(description="Run compliance DSL rules from compliance_policies table")
    parser.add_argument("--policy_filter", type=str, default="active")  # 'all', 'active', or JSON array of IDs
    parser.add_argument("--policy_categories", type=str, default=None)  # JSON array of categories
    parser.add_argument("--policy_severities", type=str, default=None)  # JSON array of severities
    parser.add_argument("--entity_limit", type=str, default=None)  # Limit entities checked per policy
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
    policy_filter = args.policy_filter
    verbose = args.verbose.lower() == "true"

    entity_limit = None
    if args.entity_limit and args.entity_limit != "null":
        try:
            entity_limit = int(args.entity_limit)
        except Exception:
            pass

    categories = None
    if args.policy_categories:
        try:
            categories = json.loads(args.policy_categories)
        except Exception:
            pass

    severities = None
    if args.policy_severities:
        try:
            severities = json.loads(args.policy_severities)
        except Exception:
            pass

    print(f"\nConfiguration:")
    print(f"  Policy filter: {policy_filter}")
    print(f"  Categories: {categories or 'all'}")
    print(f"  Severities: {severities or 'all'}")
    print(f"  Entity limit: {entity_limit or 'none'}")
    print(f"  Verbose: {verbose}")

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

    # Create session
    SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    db = SessionLocal()

    try:
        # Load policies
        print("\nLoading compliance policies...")
        policies = load_policies(engine, policy_filter, categories, severities)

        if not policies:
            print("No policies found matching criteria. Exiting.")
            return

        print(f"Found {len(policies)} policies to run")

        # Import ComplianceManager
        print("\nInitializing ComplianceManager...")
        from src.controller.compliance_manager import ComplianceManager
        manager = ComplianceManager()
        print("  ✓ ComplianceManager initialized")

        # Run each policy
        results = []
        total_passed = 0
        total_failed = 0
        total_entities = 0

        for policy in policies:
            result = run_policy(db, policy, manager, entity_limit)
            results.append(result)

            if result.get("status") in ["succeeded", "running"]:
                total_passed += result.get("success_count", 0)
                total_failed += result.get("failure_count", 0)
                total_entities += result.get("success_count", 0) + result.get("failure_count", 0)

        # Summary
        print("\n" + "=" * 80)
        print("Compliance Checks workflow completed")
        print("=" * 80)
        print(f"Policies run: {len(results)}")
        print(f"Total entities checked: {total_entities}")
        print(f"Total checks passed: {total_passed}")
        print(f"Total checks failed: {total_failed}")

        if total_entities > 0:
            overall_score = round(100.0 * (total_passed / total_entities), 2)
            print(f"Overall score: {overall_score}%")

        # Show failed policies
        failed_policies = [r for r in results if r.get("status") == "error" or r.get("score", 100) < 70]
        if failed_policies:
            print(f"\nPolicies requiring attention ({len(failed_policies)}):")
            for r in failed_policies:
                status = r.get("status", "unknown")
                score = r.get("score", 0)
                print(f"  - {r['policy_name']}: {status} (score: {score}%)")

        print("")

    finally:
        db.close()


if __name__ == "__main__":
    main()
