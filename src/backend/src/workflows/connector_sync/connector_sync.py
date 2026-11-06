"""
Connector Sync Workflow

Runs the connector syncs that are due (or one given sync): each imports its
Schema Importer selection again in sync mode, refreshes what changed in the
source, and retires assets the source no longer has (#1312 slice 5). Uses the
app's SchemaImportManager from the deployed backend source.
"""

import argparse
import os
import shutil
import sys
import tempfile
from io import BytesIO
from pathlib import Path
from typing import Optional
from zipfile import BadZipFile, ZipFile

# Local and file-based execution: the backend package parent is four levels up.
# A deployed job gets the backend source archive instead (--backend_source_path).
_entry_file = globals().get("__file__")
if _entry_file is not None:
    try:
        sys.path.insert(0, str(Path(_entry_file).parent.parent.parent.parent))
    except Exception as _exc:  # pragma: no cover - must never abort import
        print(f"WARNING: connector_sync sys.path bootstrap failed: {_exc}", file=sys.stderr)


def _add_backend_source_path(backend_source_path: Optional[str]) -> Optional[str]:
    """Put the deployed backend source (a directory or the zip archive) on sys.path.

    Needed before anything from ``src`` can be imported, so it can't come from
    there; same rules as the compliance checks workflow.
    """
    if not backend_source_path:
        return None
    source_path = Path(backend_source_path)
    if source_path.is_dir():
        import_path = str(source_path)
    elif source_path.suffix.lower() == ".zip" and source_path.is_file():
        import_path = tempfile.mkdtemp(prefix="ontos-connector-sync-backend-")
        try:
            with ZipFile(BytesIO(source_path.read_bytes())) as archive:
                root = Path(import_path).resolve()
                for member in archive.infolist():
                    if not (root / member.filename).resolve().is_relative_to(root):
                        raise RuntimeError(f"unsafe zip member escapes extraction root: {member.filename}")
                archive.extractall(import_path)
            if not (Path(import_path) / "src" / "__init__.py").is_file():
                raise RuntimeError("archive does not contain the src package")
        except (BadZipFile, OSError, RuntimeError) as exc:
            shutil.rmtree(import_path, ignore_errors=True)
            raise RuntimeError(f"Failed to extract backend source archive {source_path}: {exc}") from exc
    else:
        print(f"WARNING: backend source not found: {source_path}", file=sys.stderr)
        return None
    while import_path in sys.path:
        sys.path.remove(import_path)
    sys.path.insert(0, import_path)
    print(f"Backend source added to sys.path: {import_path}")
    return import_path


def _set_app_environment(args: argparse.Namespace) -> None:
    """Settings the app has from its resources: the volume for dashboard snapshots."""
    for env_name, value in (
        ("DATABRICKS_VOLUME", args.databricks_volume),
        ("DATABRICKS_CATALOG", args.databricks_catalog),
        ("DATABRICKS_SCHEMA", args.databricks_schema),
    ):
        if value and value != "None":
            os.environ.setdefault(env_name, value)


def run_syncs(db, ws, sync_id: Optional[str] = None, importer=None) -> int:
    """Run the due syncs (or ``sync_id``); returns how many failed. Commits after each sync."""
    from src.controller.assets_manager import AssetsManager
    from src.controller.connections_manager import ConnectionsManager
    from src.controller.connector_sync_manager import ConnectorSyncManager
    from src.controller.dashboard_snapshot_manager import DashboardSnapshotManager
    from src.controller.schema_import_manager import SchemaImportManager

    manager = ConnectorSyncManager()
    if sync_id:
        sync = manager.get(db, sync_id)
        syncs = [sync] if sync is not None else []
        if not syncs:
            print(f"ERROR: connector sync {sync_id} not found")
            return 1
    else:
        syncs = manager.due(db)
    print(f"{len(syncs)} connector sync(s) to run")

    if importer is None:
        # The job's identity (the app's service principal) reads the sources: it
        # needs READ_SECRET on each connection's secret
        importer = SchemaImportManager(
            ConnectionsManager(db=db, workspace_client=ws), AssetsManager(),
            snapshot_manager=DashboardSnapshotManager(workspace_client_provider=lambda: ws),
        )

    failed = 0
    for sync in syncs:
        print(f"\n▶ Sync '{sync.name}' ({sync.id})")
        try:
            summary = manager.run(db, sync, importer, trigger="manual" if sync_id else "schedule")
            db.commit()
        except Exception as exc:  # the manager records failures; this is a database error
            db.rollback()
            print(f"  ERROR: could not record the sync: {type(exc).__name__}: {exc}")
            failed += 1
            continue
        print(f"  status={summary['status']} created={summary.get('created', 0)} "
              f"refreshed={summary.get('refreshed', 0)} missed={summary.get('missed', 0)} "
              f"retired={summary.get('retired', 0)} reactivated={summary.get('reactivated', 0)}")
        for reason in summary.get("incomplete_reasons") or []:
            print(f"  not complete: {reason}")
        if summary["status"] == "failed":
            print(f"  ERROR: {summary.get('error')}")
            failed += 1
    return failed


def main() -> None:
    print("Connector Sync workflow started")
    parser = argparse.ArgumentParser(description="Run due connector syncs")
    parser.add_argument("--sync_id", type=str, default="")
    parser.add_argument("--backend_source_path", type=str, default=None)
    parser.add_argument("--databricks_volume", type=str, default="")
    parser.add_argument("--databricks_catalog", type=str, default="")
    parser.add_argument("--databricks_schema", type=str, default="")
    parser.add_argument("--lakebase_instance_name", type=str, required=True)
    parser.add_argument("--postgres_host", type=str, required=True)
    parser.add_argument("--postgres_db", type=str, required=True)
    parser.add_argument("--postgres_port", type=str, default="5432")
    parser.add_argument("--postgres_schema", type=str, default="public")
    parser.add_argument("--product_name", type=str, default="ontos")
    parser.add_argument("--product_version", type=str, default="0.0.0")
    args, _ = parser.parse_known_args()

    import_path = _add_backend_source_path(args.backend_source_path)
    _set_app_environment(args)

    from databricks.sdk import WorkspaceClient
    from sqlalchemy.orm import sessionmaker

    # Lakebase connection, schema check and app settings: the same as the compliance checks job
    from src.workflows.compliance_checks.compliance_checks import (
        SchemaRevisionError,
        _alembic_script_location,
        _initialize_application_config,
        check_schema_revision,
        create_engine_from_params,
    )

    ws = WorkspaceClient(product=args.product_name, product_version=args.product_version)
    _initialize_application_config(ws)
    engine = create_engine_from_params(
        ws_client=ws, host=args.postgres_host, db=args.postgres_db, port=args.postgres_port,
        schema=args.postgres_schema, instance_name=args.lakebase_instance_name,
    )
    try:
        check_schema_revision(engine, _alembic_script_location(import_path))
    except SchemaRevisionError:
        sys.exit(1)

    db = sessionmaker(autocommit=False, autoflush=False, bind=engine)()
    try:
        failed = run_syncs(db, ws, sync_id=(args.sync_id or "").strip() or None)
    finally:
        db.close()
    if failed:
        print(f"\nERROR: {failed} connector sync(s) failed")
        sys.exit(1)
    print("\nConnector Sync workflow completed")


if __name__ == "__main__":
    main()
