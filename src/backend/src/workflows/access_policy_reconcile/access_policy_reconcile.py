"""
Access Policy Drift Reconcile Workflow (report only)

For every Access Target whose reconcile schedule (cron) fired since its last report, or the
targets passed in, reads the
live Unity Catalog grants of the securables in its Grant Ledger and stores a drift report
(tracked-but-missing / unmanaged grants). Nothing is granted or revoked: drift is reported,
admins decide. Reuses the Compliance Checks job's database / backend-source helpers.
"""

import argparse
import sys
from pathlib import Path
from typing import List, Optional

# Bootstrap the backend package parent for local and file-based execution (same as
# compliance_checks.py); serverless runs pass --backend_source_path instead.
_entry_file = globals().get("__file__")
if _entry_file is not None:
    try:
        sys.path.insert(0, str(Path(_entry_file).parent.parent.parent.parent))
    except Exception as _exc:  # pragma: no cover - defensive; must never abort import
        print(f"WARNING: access_policy_reconcile sys.path bootstrap failed: {_exc}", file=sys.stderr)


def _add_backend_source(path: Optional[str]) -> Optional[str]:
    """Make ``src`` importable from a source directory or the deployed source archive."""
    if not path:
        return None
    p = Path(path)
    if p.is_dir():
        import_path = str(p)
    elif p.suffix.lower() == ".zip" and p.is_file():
        # Same as compliance_checks._add_backend_source_path (which can't be imported before this).
        import shutil
        import tempfile
        from io import BytesIO
        from zipfile import BadZipFile, ZipFile

        import_path = tempfile.mkdtemp(prefix="ontos-reconcile-backend-")
        root = Path(import_path).resolve()
        try:
            # Read fully first: the /Workspace FUSE path may not support seeking.
            with ZipFile(BytesIO(p.read_bytes())) as archive:
                for member in archive.infolist():
                    if not (root / member.filename).resolve().is_relative_to(root):
                        raise RuntimeError(f"unsafe zip member escapes extraction root: {member.filename}")
                archive.extractall(import_path)
            if not (root / "src" / "__init__.py").is_file():
                raise RuntimeError("archive does not contain the src package")
        except (BadZipFile, OSError, RuntimeError) as exc:
            shutil.rmtree(import_path, ignore_errors=True)
            raise RuntimeError(f"Failed to extract backend source archive {p}: {exc}") from exc
    else:
        print(f"WARNING: unsupported backend source path: {path}", file=sys.stderr)
        return None
    while import_path in sys.path:
        sys.path.remove(import_path)
    sys.path.insert(0, import_path)
    print(f"Backend source added to sys.path: {import_path}")
    return import_path


def _target_keys(value: Optional[str]) -> Optional[List[str]]:
    value = (value or "").strip()
    if not value or value == "scheduled":
        return None
    return [k.strip() for k in value.split(",") if k.strip()]


def main() -> None:
    print("Access Policy Drift Reconcile workflow started")
    parser = argparse.ArgumentParser(description="Report-only drift reconcile of Access Policy targets")
    parser.add_argument("--targets", type=str, default="scheduled")
    parser.add_argument("--backend_source_path", type=str, default=None)
    parser.add_argument("--lakebase_instance_name", type=str, required=True)
    parser.add_argument("--postgres_host", type=str, required=True)
    parser.add_argument("--postgres_db", type=str, required=True)
    parser.add_argument("--postgres_port", type=str, default="5432")
    parser.add_argument("--postgres_schema", type=str, default="public")
    parser.add_argument("--product_name", type=str, default="ontos")
    parser.add_argument("--product_version", type=str, default="0.0.0")
    args, _ = parser.parse_known_args()

    import_path = _add_backend_source(args.backend_source_path)

    from databricks.sdk import WorkspaceClient
    from sqlalchemy.orm import sessionmaker

    from src.workflows.compliance_checks.compliance_checks import (
        SchemaRevisionError,
        _alembic_script_location,
        _initialize_application_config,
        check_schema_revision,
        create_engine_from_params,
    )

    ws = WorkspaceClient(product=args.product_name, product_version=args.product_version)
    _initialize_application_config(ws)
    engine = create_engine_from_params(ws_client=ws, host=args.postgres_host, db=args.postgres_db,
                                       port=args.postgres_port, schema=args.postgres_schema,
                                       instance_name=args.lakebase_instance_name)
    try:
        check_schema_revision(engine, _alembic_script_location(import_path))
    except SchemaRevisionError:
        sys.exit(1)

    from src.controller.access_policy_releases_manager import PolicyReleaseManager
    from src.controller.grant_manager import GrantManager

    grants = GrantManager(ws_client=ws)
    db = sessionmaker(autocommit=False, autoflush=False, bind=engine)()
    try:
        reports = PolicyReleaseManager().reconcile_scheduled(db, grants, "system:reconcile-job",
                                                             _target_keys(args.targets))
        db.commit()
        for r in reports:
            c = r.counts or {}
            print(f"  {r.target}: {r.status} — {c.get('missing', 0)} missing, {c.get('unmanaged', 0)} unmanaged, "
                  f"{c.get('tracked', 0)} tracked, {c.get('errors', 0)} read errors")
        if not reports:
            print("No target due (each Access Target's reconcile schedule decides; or pass --targets).")
        # Drift is a finding, not a job failure; targets that couldn't be (fully) read are.
        if any(r.status in ("error", "partial") for r in reports):
            sys.exit(1)
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


if __name__ == "__main__":
    main()
