"""The shared ADM schema for Authority Resolution (ARF 1.2.0 slice 4, #1294).

One ``catalog.schema`` is the app setting every Authority Relation reads evidence from
(``authority_adm_schema`` in ``app_settings``). An AR can override it with another schema
(Admin only; see the AR manager). Either way the schema must pass the conformance check
against the pinned ADM v0.4 subset (:mod:`src.common.adm`).

Ontos reads the schema as its app service principal, which needs ``SELECT`` on that schema
only. Ontos never writes to it. The DDL for the pinned subset is served by
:meth:`AuthorityAdmManager.ddl`; the seeded demo schema ships as a SQL file.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from sqlalchemy.orm import Session

from src.common import adm
from src.common.adm_sql import AdmQueryError, run_query
from src.common.api_errors import CodedValueError, log_failure
from src.common.logging import get_logger
from src.repositories.app_settings_repository import AppSettingsRepository

logger = get_logger(__name__)

SHARED_SCHEMA_SETTING = "authority_adm_schema"
# The last conformance result for the shared schema, stored with its time: {checked_at, report}.
CONFORMANCE_SETTING = "authority_adm_conformance"
ADM_NOT_CONFIGURED = "adm_schema_not_configured"
ADM_NONCONFORMANT = "adm_nonconformant"

_settings_repo = AppSettingsRepository()


class AuthorityAdmManager:
    """Reads and checks the shared ADM schema. Stateless; the DB session is passed per call."""

    # ------------------------------------------------------------ the setting

    def shared_schema(self, db: Session) -> Optional[str]:
        """The configured ``catalog.schema``, or None."""
        value = _settings_repo.get_by_key(db, SHARED_SCHEMA_SETTING)
        text = (value or "").strip()
        return text or None

    def set_shared_schema(self, db: Session, value: Optional[str], *, caller_is_admin: bool) -> Dict[str, Any]:
        """Set (or clear, with None or "") the shared schema. Admin only; the schema must conform.

        The conformance result is stored with its time, so reading the setting later doesn't
        need a warehouse query. Returns the new state.
        """
        if not caller_is_admin:
            raise AdmPermissionError("Only an Admin can change the shared ADM schema.")
        parsed = adm.parse_schema_fqn(value)
        if parsed is None:
            _settings_repo.set(db, SHARED_SCHEMA_SETTING, None)
            _settings_repo.set(db, CONFORMANCE_SETTING, None)
            return {"schema": None, "adm_version": adm.ADM_VERSION, "conformance": None, "checked_at": None}
        schema = f"{parsed[0]}.{parsed[1]}"
        report = self.conformance(schema)
        if report["status"] != "conformant":
            raise AdmNonconformantError(schema, report)
        _settings_repo.set(db, SHARED_SCHEMA_SETTING, schema)
        checked_at = self._store_conformance(db, report)
        logger.info("Shared ADM schema set to %s (%s)", schema, adm.ADM_VERSION)
        return {"schema": schema, "adm_version": adm.ADM_VERSION, "conformance": report, "checked_at": checked_at}

    def check(self, db: Session, *, caller_is_admin: bool) -> Dict[str, Any]:
        """Check the configured schema now and store the result. Admin only; the one warehouse-bound call.

        A schema that can't be checked (no warehouse, no access, a failed statement) is stored as
        ``unavailable`` with its code.
        """
        if not caller_is_admin:
            raise AdmPermissionError("Only an Admin can check the shared ADM schema.")
        schema = self.shared_schema(db)
        if schema is None:
            return self.state(db)
        try:
            report = self.conformance(schema)
        except CodedValueError as exc:
            report = {"adm_version": adm.ADM_VERSION, "schema": schema, "status": "unavailable",
                      "findings": [], "error_code": exc.code, "checked_tables": sorted(adm.TABLES)}
        self._store_conformance(db, report)
        return self.state(db)

    def state(self, db: Session) -> Dict[str, Any]:
        """The shared schema and its last stored conformance result. Never queries the warehouse,
        so opening Settings (or an AR) costs no statement; use :meth:`check` to refresh."""
        schema = self.shared_schema(db)
        stored = self._stored_conformance(db) if schema else None
        return {
            "schema": schema,
            "adm_version": adm.ADM_VERSION,
            "conformance": (stored or {}).get("report"),
            "checked_at": (stored or {}).get("checked_at"),
        }

    @staticmethod
    def _store_conformance(db: Session, report: Dict[str, Any]) -> str:
        checked_at = datetime.now(timezone.utc).isoformat()
        _settings_repo.set(db, CONFORMANCE_SETTING, json.dumps({"checked_at": checked_at, "report": report}))
        return checked_at

    @staticmethod
    def _stored_conformance(db: Session) -> Optional[Dict[str, Any]]:
        raw = _settings_repo.get_by_key(db, CONFORMANCE_SETTING)
        if not raw:
            return None
        try:
            value = json.loads(raw)
        except ValueError:
            return None
        return value if isinstance(value, dict) else None

    # ------------------------------------------------------------- checks

    def conformance(self, schema_fqn: str) -> Dict[str, Any]:
        """Check ``schema_fqn`` against the pinned ADM v0.4 subset (reads ``information_schema``)."""
        sql = adm.information_schema_sql(schema_fqn)
        ws, warehouse_id = workspace_and_warehouse()
        rows = run_query(sql, ws=ws, warehouse_id=warehouse_id)
        columns = [(r.get("table_name"), r.get("column_name"), r.get("data_type")) for r in rows]
        return adm.conformance_report(columns, schema_fqn=schema_fqn)

    def ddl(self, schema_fqn: str) -> str:
        """The DDL that creates the pinned subset in ``schema_fqn`` (idempotent)."""
        parsed = adm.parse_schema_fqn(schema_fqn)
        if parsed is None:
            raise adm.AdmError(ADM_NOT_CONFIGURED, "No ADM schema is configured.")
        return adm.render_ddl(parsed[0], parsed[1])


class AdmPermissionError(CodedValueError):
    """A change to the shared schema by someone who isn't an Admin."""

    http_status = 403

    def __init__(self, message: str):
        super().__init__(message, required_level="Admin")
        self.code = "authority_permission_denied"


class AdmNonconformantError(CodedValueError):
    """A schema that doesn't pass the ADM v0.4 conformance check. The findings list what to fix."""

    http_status = 422

    def __init__(self, schema: str, report: Dict[str, Any]):
        findings = report.get("findings") or []
        super().__init__(
            f"{schema} does not conform to {adm.ADM_VERSION}: {len(findings)} finding(s).",
            schema=schema, findings=len(findings),
        )
        self.code = ADM_NONCONFORMANT
        self.report = report


def workspace_and_warehouse():
    """The app service principal's client and the SQL warehouse, or a coded refusal."""
    from src.common.config import get_settings
    from src.common.workspace_client import get_workspace_client

    settings = get_settings()
    warehouse_id = (
        getattr(settings, "DATABRICKS_WAREHOUSE_ID", None)
        or getattr(settings, "DATABRICKS_SQL_WAREHOUSE_ID", None)
    )
    if not warehouse_id:
        raise adm.AdmError(ADM_NOT_CONFIGURED, "No SQL warehouse is configured for the ADM schema.")
    try:
        return get_workspace_client(), warehouse_id
    except Exception as exc:
        error_id = log_failure("ADM workspace client", exc)
        raise AdmQueryError("The ADM workspace client could not be built.", error_id=error_id)
