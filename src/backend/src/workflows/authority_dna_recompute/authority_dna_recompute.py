"""
Authority Relation DNA Recompute Workflow

Recomputes the DNA-Coefficient for every Authority Relation (ARF) that has a
``schedule_cron`` set and whose cron has fired since its last measurement. The Databricks
job's own schedule drives cadence; the per-AR cron decides which ARs are due, retired ARs
are skipped, and the sample is read from the shared ADM schema through the job's SQL
warehouse. The same AuthorityResolutionManager routine serves the Admin trigger endpoint.

Reuses the Lakebase OAuth + engine helpers from the compliance_checks workflow to
avoid duplicating the DB-connection boilerplate, and the shared workflow config helper.
"""

import sys
import argparse
from pathlib import Path

# Add the backend root (…/src/backend/src's parent chain) so `src.*` imports work.
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from sqlalchemy.orm import sessionmaker

from databricks.sdk import WorkspaceClient

# Reuse the vetted DB-connection scaffolding from the compliance workflow.
from src.workflows.compliance_checks.compliance_checks import create_engine_from_params
from src.common.workflow_config import initialize_application_config
from src.common.adm_sql import AdmQueryError, ADM_NO_WAREHOUSE


def require_warehouse(warehouse_id: str) -> None:
    """Fail the whole job, once, when no SQL warehouse was passed: the ADM schema can't be read
    without one, so every AR would fail the same way. The job parameter is filled in by Ontos
    (``databricks_warehouse_id``, from the app's configured warehouse)."""
    if not (warehouse_id or "").strip():
        raise AdmQueryError(
            "No SQL warehouse is configured for the job, so the ADM schema cannot be read.",
            code=ADM_NO_WAREHOUSE,
        )


def main() -> None:
    print("Authority Relation DNA Recompute workflow started")

    parser = argparse.ArgumentParser(description="Recompute DNAco for scheduled Authority Relations")
    parser.add_argument("--verbose", type=str, default="false")
    # Database connection parameters
    parser.add_argument("--lakebase_instance_name", type=str, required=True)
    parser.add_argument("--postgres_host", type=str, required=True)
    parser.add_argument("--postgres_db", type=str, required=True)
    parser.add_argument("--postgres_port", type=str, default="5432")
    parser.add_argument("--postgres_schema", type=str, default="public")
    # The SQL warehouse the ADM evidence is read through (the shared ADM schema).
    parser.add_argument("--databricks_warehouse_id", type=str, default="")
    # Telemetry parameters (passed from app)
    parser.add_argument("--product_name", type=str, default="ontos")
    parser.add_argument("--product_version", type=str, default="0.0.0")

    args, _ = parser.parse_known_args()
    verbose = args.verbose.lower() == "true"

    try:
        require_warehouse(args.databricks_warehouse_id)
    except AdmQueryError as e:
        print(f"ERROR: {e.code}: {e.message}")
        raise SystemExit(1)

    print("\nInitializing workspace client...")
    ws = WorkspaceClient(product=args.product_name, product_version=args.product_version)
    print("  ✓ Workspace client initialized")

    print("\nInitializing application settings...")
    initialize_application_config(ws, warehouse_id=args.databricks_warehouse_id or None)
    print("  ✓ Application settings initialized")

    print("\nConnecting to database...")
    engine = create_engine_from_params(
        ws_client=ws,
        host=args.postgres_host,
        db=args.postgres_db,
        port=args.postgres_port,
        schema=args.postgres_schema,
        instance_name=args.lakebase_instance_name,
    )
    print("  ✓ Database connection established")

    SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    db = SessionLocal()

    try:
        from src.controller.authority_resolution_manager import AuthorityResolutionManager
        manager = AuthorityResolutionManager()

        print("\nRecomputing DNA-Coefficient for scheduled Authority Relations...")
        summary = manager.recompute_scheduled(db)
        db.commit()

        succeeded = sum(1 for r in summary.get("results", []) if r.get("status") == "succeeded")
        failed = sum(1 for r in summary.get("results", []) if r.get("status") == "failed")
        print("\n" + "=" * 80)
        print("Authority Relation DNA Recompute completed")
        print(f"  Scheduled ARs: {summary.get('scheduled', 0)}")
        print(f"  Succeeded: {succeeded} | Failed: {failed}")
        if verbose:
            for r in summary.get("results", []):
                print(f"    - {r.get('relation_id')}: {r.get('status')} (magnitude={r.get('magnitude')})")
        print("=" * 80)
    except Exception as e:
        db.rollback()
        print(f"ERROR: Authority Relation DNA recompute failed: {e}")
        raise
    finally:
        db.close()


if __name__ == "__main__":
    main()
