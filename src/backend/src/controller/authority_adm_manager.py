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

from typing import Any, Dict, Optional

from sqlalchemy.orm import Session

from src.common import adm
from src.common.adm_sql import run_query
from src.common.api_errors import CodedValueError
from src.common.logging import get_logger
from src.repositories.app_settings_repository import AppSettingsRepository

logger = get_logger(__name__)

SHARED_SCHEMA_SETTING = "authority_adm_schema"
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

        Returns the new state with its conformance report.
        """
        if not caller_is_admin:
            raise AdmPermissionError("Only an Admin can change the shared ADM schema.")
        parsed = adm.parse_schema_fqn(value)
        if parsed is None:
            _settings_repo.set(db, SHARED_SCHEMA_SETTING, None)
            return {"schema": None, "conformance": None}
        schema = f"{parsed[0]}.{parsed[1]}"
        report = self.conformance(schema)
        if report["status"] != "conformant":
            raise AdmNonconformantError(schema, report)
        _settings_repo.set(db, SHARED_SCHEMA_SETTING, schema)
        logger.info("Shared ADM schema set to %s (%s)", schema, adm.ADM_VERSION)
        return {"schema": schema, "conformance": report}

    def state(self, db: Session) -> Dict[str, Any]:
        """The shared schema and its conformance, as the Settings page shows them.

        A schema that can't be checked (no warehouse, no access) reports ``unavailable`` with
        a code, not the database error text.
        """
        schema = self.shared_schema(db)
        if schema is None:
            return {"schema": None, "adm_version": adm.ADM_VERSION, "conformance": None}
        try:
            report = self.conformance(schema)
        except CodedValueError as exc:
            report = {"adm_version": adm.ADM_VERSION, "schema": schema, "status": "unavailable",
                      "findings": [], "error_code": exc.code, "checked_tables": sorted(adm.TABLES)}
        return {"schema": schema, "adm_version": adm.ADM_VERSION, "conformance": report}

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
    return get_workspace_client(), warehouse_id
