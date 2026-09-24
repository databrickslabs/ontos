"""
Authority Relation DNA Recompute Workflow

Recomputes the DNA-Coefficient for every Authority Relation (ARF) that has a
``schedule_cron`` set. The Databricks job's own schedule drives cadence; when it
runs, it recomputes all scheduled ARs via the same AuthorityResolutionManager
routine used by the manual trigger endpoint.

Reuses the Lakebase OAuth + engine helpers from the compliance_checks workflow to
avoid duplicating the DB-connection boilerplate.
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
    # Telemetry parameters (passed from app)
    parser.add_argument("--product_name", type=str, default="ontos")
    parser.add_argument("--product_version", type=str, default="0.0.0")

    args, _ = parser.parse_known_args()
    verbose = args.verbose.lower() == "true"

    print("\nInitializing workspace client...")
    ws = WorkspaceClient(product=args.product_name, product_version=args.product_version)
    print("  ✓ Workspace client initialized")

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
