"""ARF Authority Decision Model (ADM) v0.4 binding for Authority Resolution (#1294 slice 4).

The shared ADM schema (``catalog.schema`` in Unity Catalog) is the only evidence source an
Authority Relation reads. Ontos needs ``SELECT`` on that one schema; Unity Catalog row
filters and column masks still apply. Ontos never writes to it.

This module is pure (no database, no workspace client):

* the pinned ADM subset we read (:data:`TABLES`, from ADM v0.4 sections 5.2, 5.3, 5.4, 6.1
  and 6.5), and the conformance check against it;
* the DDL for that subset (:func:`render_ddl`);
* the SQL the resolver and the DNA-Coefficient run (identifiers validated, literals escaped);
* typed coercion of result rows, as-of predicates (ADM section 4.2) and the resolve-time
  facts derived from entitlements, roles and delegation chains.

ADM v0.4 is guidance, not a strict contract: we pin ``ADM v0.4`` as the conformance
version and say so in every DNA run's basis. Deviations from the spec text are noted at
the definitions below.
"""
from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

from src.common.api_errors import CodedValueError

ADM_VERSION = "ADM v0.4"
# The DNA method a run was computed under (ADM section 8.6 ``method_version``).
DNA_METHOD_VERSION = "ontos-dnaco-signed-2"

# Logical column types. JSON columns are STRING in Unity Catalog (parsed by the reader).
STRING = "STRING"
TIMESTAMP = "TIMESTAMP"
DECIMAL = "DECIMAL"
INT = "INT"
BOOLEAN = "BOOLEAN"

_LOGICAL_DDL = {STRING: "STRING", TIMESTAMP: "TIMESTAMP", DECIMAL: "DECIMAL(20,4)", INT: "INT", BOOLEAN: "BOOLEAN"}

# Table -> ((column, logical type), ...). Every listed column is part of the conformance
# check, and the reader selects only these names (no raw extra columns are kept).
#
# Deviation: ADM v0.4 section 6.5 (observed_decision_provenance) has no superseded_at, so an
# observation is read as of the snapshot with recorded_at alone (see :func:`as_of_clause`).
TABLES: Dict[str, Tuple[Tuple[str, str], ...]] = {
    "roles": (
        ("role_id", STRING), ("role_name", STRING), ("domain", STRING), ("authority_scope", STRING),
        ("permissions", STRING), ("max_value", DECIMAL), ("currency", STRING),
        ("requires_approval_above", DECIMAL), ("policy_basis_id", STRING),
        ("valid_from", TIMESTAMP), ("valid_to", TIMESTAMP),
        ("recorded_at", TIMESTAMP), ("superseded_at", TIMESTAMP),
    ),
    "entitlements": (
        ("entitlement_id", STRING), ("entity_id", STRING), ("role_id", STRING), ("domain_context", STRING),
        ("granted_by", STRING), ("granted_at", TIMESTAMP), ("valid_from", TIMESTAMP), ("valid_to", TIMESTAMP),
        ("conditions", STRING), ("revoked_at", TIMESTAMP), ("revocation_reason", STRING),
        ("evidence_id", STRING), ("policy_basis_id", STRING), ("claim_status", STRING),
        ("recorded_at", TIMESTAMP), ("superseded_at", TIMESTAMP),
    ),
    "delegation_chains": (
        ("delegation_id", STRING), ("grantor_entity_id", STRING), ("grantee_entity_id", STRING),
        ("role_id", STRING), ("scope_restriction", STRING), ("valid_from", TIMESTAMP), ("valid_to", TIMESTAMP),
        ("justification", STRING), ("parent_delegation_id", STRING), ("max_sub_delegation_depth", INT),
        ("requires_notification", BOOLEAN), ("policy_basis_id", STRING), ("evidence_id", STRING),
        ("recorded_at", TIMESTAMP), ("superseded_at", TIMESTAMP),
    ),
    "source_identity_map": (
        ("identity_link_id", STRING), ("entity_id", STRING), ("source_system", STRING), ("source_tenant", STRING),
        ("source_id", STRING), ("match_method", STRING), ("verification_status", STRING), ("evidence_id", STRING),
        ("valid_from", TIMESTAMP), ("valid_to", TIMESTAMP), ("recorded_at", TIMESTAMP), ("superseded_at", TIMESTAMP),
    ),
    "observed_decision_provenance": (
        ("observation_id", STRING), ("business_decision_id", STRING), ("action_code", STRING),
        ("object_ref", STRING), ("actor_entity_id", STRING), ("actor_role", STRING),
        ("event_at", TIMESTAMP), ("recorded_at", TIMESTAMP), ("decision_basis_ref", STRING),
        ("approval_evidence_id", STRING), ("source_evidence_id", STRING), ("context", STRING),
        ("observation_status", STRING), ("dna_contribution_flag", BOOLEAN),
    ),
}

# The resolve-time facts a rule can read as ``fact.<name>``. Flat names: the DSL reads
# ``root.property`` only, so ``fact.entitlement_valid_from`` stands for the
# ``fact.entitlement.valid_from`` of the design note.
FACT_TYPES: Dict[str, str] = {
    "identity_verified": BOOLEAN,       # the caller's identity has a VERIFIED link
    "entity_id": STRING,                # the caller's canonical entity id (VERIFIED links only)
    "entitlement_current": BOOLEAN,     # a current, verified, unrevoked entitlement for entity + AR role
    "entitlement_valid_from": TIMESTAMP,
    "entitlement_valid_to": TIMESTAMP,  # None = open-ended, which a rule sees as unknown
    "role_codes": STRING,               # JSON list of the AR role's permission codes (current role row)
    "delegation_active": BOOLEAN,       # a current delegation to the entity for the AR role
}
FACT_NAMESPACE = "fact"

_IDENT_RE = re.compile(r"^[A-Za-z0-9_][A-Za-z0-9_\-]{0,254}$")
_ACTION_RE = re.compile(r"^[a-z][a-z0-9_:.\-]{0,127}$")
_FACT_REF_RE = re.compile(r"\bfact\.([A-Za-z_][A-Za-z0-9_]*)")

# Keys the observed row sets itself. A context key of the same name never overrides them.
CANONICAL_ROW_KEYS = (
    "observation_id", "business_decision_id", "action", "object_id", "actor_identity",
    "actor_entity_id", "actor_role", "actor_identity_status", "event_at", "approval_evidence_id",
    "value", "escalated", "cosign_present",
)


class AdmError(CodedValueError):
    """A configuration or input fault in the ADM binding. ``code`` is safe to show a client."""

    def __init__(self, code: str, message: str, **params: Any):
        super().__init__(message, **params)
        self.code = code


# --------------------------------------------------------------------------- #
# Identifiers and literals                                                    #
# --------------------------------------------------------------------------- #

def parse_schema_fqn(value: Optional[str]) -> Optional[Tuple[str, str]]:
    """``catalog.schema`` -> ``(catalog, schema)``; None for empty; refuses anything else."""
    text = (value or "").strip()
    if not text:
        return None
    parts = text.split(".")
    if len(parts) != 2 or not all(_IDENT_RE.match(p) for p in parts):
        raise AdmError("adm_schema_invalid", "The ADM schema must be catalog.schema.", value=text)
    return parts[0], parts[1]


def _q(ident: str) -> str:
    return f"`{ident}`"


def table_fqn(schema_fqn: str, table: str) -> str:
    """Backticked ``catalog.schema.table`` for a pinned ADM table."""
    if table not in TABLES:
        raise AdmError("adm_table_unknown", "Unknown ADM table.", table=table)
    parsed = parse_schema_fqn(schema_fqn)
    if parsed is None:
        raise AdmError("adm_schema_missing", "No ADM schema is configured.")
    return f"{_q(parsed[0])}.{_q(parsed[1])}.{_q(table)}"


def lit(value: Any) -> str:
    """A SQL string literal. Backslashes and quotes are escaped; no value is ever interpolated raw."""
    text = str(value)
    return "'" + text.replace("\\", "\\\\").replace("'", "\\'") + "'"


def ts_lit(value: datetime) -> str:
    """A UTC timestamp literal (ISO text cast, so the session time zone doesn't matter)."""
    utc = _as_utc(value)
    return f"CAST({lit(utc.strftime('%Y-%m-%dT%H:%M:%S.%fZ'))} AS TIMESTAMP)"


def _in_list(values: Sequence[str]) -> str:
    return "(" + ", ".join(lit(v) for v in values) + ")"


def validated_action_codes(values: Iterable[str]) -> List[str]:
    out = []
    for v in values:
        text = str(v).strip()
        if not _ACTION_RE.match(text):
            raise AdmError("evidence_slice_invalid", "An action code must be a lowercase code such as approve.", value=text)
        if text not in out:
            out.append(text)
    return out


# --------------------------------------------------------------------------- #
# Conformance (ADM v0.4 pinned subset)                                        #
# --------------------------------------------------------------------------- #

_TYPE_FAMILY = {
    "STRING": STRING, "VARCHAR": STRING, "CHAR": STRING,
    "TIMESTAMP": TIMESTAMP, "TIMESTAMP_NTZ": TIMESTAMP,
    "DECIMAL": DECIMAL, "NUMERIC": DECIMAL,
    "INT": INT, "INTEGER": INT, "BIGINT": INT, "LONG": INT, "SMALLINT": INT, "TINYINT": INT, "SHORT": INT,
    "BOOLEAN": BOOLEAN,
}


def normalise_uc_type(data_type: Optional[str]) -> str:
    """A Unity Catalog ``data_type`` reduced to its ADM logical family (``DECIMAL(20,4)`` -> DECIMAL)."""
    base = re.sub(r"\(.*\)", "", (data_type or "").upper()).strip()
    return _TYPE_FAMILY.get(base, base)


def conformance_report(
    columns: Iterable[Tuple[str, str, str]], *, schema_fqn: Optional[str] = None,
) -> Dict[str, Any]:
    """Compare ``(table, column, data_type)`` rows from ``information_schema`` with the pinned ADM subset.

    Every pinned table and column must exist with its logical type. Extra columns are
    allowed and never read. The report lists each finding with a code, so the UI can show
    what to fix; it carries no raw database text.
    """
    found: Dict[str, Dict[str, str]] = {}
    for table, column, data_type in columns:
        found.setdefault(str(table).lower(), {})[str(column).lower()] = normalise_uc_type(data_type)
    findings: List[Dict[str, Any]] = []
    for table, spec in TABLES.items():
        have = found.get(table)
        if have is None:
            findings.append({"code": "missing_table", "table": table})
            continue
        for column, logical in spec:
            if column not in have:
                findings.append({"code": "missing_column", "table": table, "column": column, "expected": logical})
            elif have[column] != logical:
                findings.append({
                    "code": "type_mismatch", "table": table, "column": column,
                    "expected": logical, "actual": have[column],
                })
    return {
        "adm_version": ADM_VERSION,
        "schema": schema_fqn,
        "status": "conformant" if not findings else "nonconformant",
        "findings": findings,
        "checked_tables": sorted(TABLES),
    }


def information_schema_sql(schema_fqn: str) -> str:
    """The query behind :func:`conformance_report`: the pinned tables' columns and types."""
    parsed = parse_schema_fqn(schema_fqn)
    if parsed is None:
        raise AdmError("adm_schema_missing", "No ADM schema is configured.")
    catalog, schema = parsed
    names = _in_list(sorted(TABLES))
    return (
        "SELECT table_name, column_name, data_type "
        f"FROM {_q(catalog)}.information_schema.columns "
        f"WHERE table_schema = {lit(schema)} AND lower(table_name) IN {names}"
    )


# --------------------------------------------------------------------------- #
# DDL                                                                         #
# --------------------------------------------------------------------------- #

_COMMENTS = {
    "roles": "ADM v0.4 section 5.2. Role definitions and candidate mandates.",
    "entitlements": "ADM v0.4 section 5.3. Role assignments (read-only input for Ontos).",
    "delegation_chains": "ADM v0.4 section 5.4. Delegation lineage.",
    "source_identity_map": "ADM v0.4 section 6.1. Verified links from source aliases to canonical entities.",
    "observed_decision_provenance": "ADM v0.4 section 6.5. Observed decision events; the DNA-Coefficient evidence.",
}


def render_ddl(catalog: str, schema: str) -> str:
    """Delta DDL for the pinned ADM subset in ``catalog.schema`` (idempotent)."""
    parsed = parse_schema_fqn(f"{catalog}.{schema}")
    assert parsed is not None
    cat, sch = parsed
    out = [
        f"-- {ADM_VERSION}: pinned subset read by Ontos Authority Resolution.",
        "-- Ontos needs SELECT on this schema only. Ontos never writes to it.",
        f"CREATE SCHEMA IF NOT EXISTS {_q(cat)}.{_q(sch)};",
        "",
    ]
    for table, spec in TABLES.items():
        cols = ",\n".join(f"  {c} {_LOGICAL_DDL[t]} COMMENT '{c}'" for c, t in spec)
        out.append(
            f"-- {_COMMENTS[table]}\n"
            f"CREATE TABLE IF NOT EXISTS {_q(cat)}.{_q(sch)}.{_q(table)} (\n{cols}\n)\n"
            f"USING DELTA\n"
            f"TBLPROPERTIES ('ontos.adm_version' = '{ADM_VERSION}');\n"
        )
    return "\n".join(out)


# --------------------------------------------------------------------------- #
# As-of predicates (ADM section 4.2)                                          #
# --------------------------------------------------------------------------- #

def as_of_clause(table: str, *, at: datetime, valid_at: Optional[datetime] = None) -> str:
    """The bitemporal predicate for one table, as SQL.

    * System time: ``recorded_at <= at`` and, where the table carries it, ``superseded_at``
      is null or after ``at``. A correction recorded after the snapshot doesn't rewrite it.
    * Valid time (when ``valid_at`` is given): half-open ``[valid_from, valid_to)`` at that instant.
    """
    columns = dict(TABLES[table])
    clauses = [f"recorded_at <= {ts_lit(at)}"]
    if "superseded_at" in columns:
        clauses.append(f"(superseded_at IS NULL OR superseded_at > {ts_lit(at)})")
    if valid_at is not None and "valid_from" in columns:
        clauses.append(f"valid_from <= {ts_lit(valid_at)}")
        clauses.append(f"(valid_to IS NULL OR valid_to > {ts_lit(valid_at)})")
    return " AND ".join(clauses)


def sample_seed(relation_id: str, version: str, window_start: datetime, window_end: datetime) -> str:
    """A stable seed for the sample of one AR version over one window (same inputs, same seed)."""
    basis = "|".join([str(relation_id), str(version), _as_utc(window_start).isoformat(), _as_utc(window_end).isoformat()])
    return hashlib.sha256(basis.encode("utf-8")).hexdigest()[:24]


def observed_sample_sql(
    schema_fqn: str, *, action_codes: Sequence[str], object_refs: Sequence[str],
    window_start: datetime, window_end: datetime, as_of: datetime, seed: str, sample_size: int,
) -> str:
    """The DNA evidence read: the observations in the window, as of the snapshot, in a stable
    pseudo-random order (``xxhash64`` of the observation id with the seed), then the first N.

    Same schema, codes, window, snapshot and seed give the same text, and so the same rows.
    """
    if not action_codes:
        raise AdmError("evidence_slice_empty", "The Authority Relation declares no action codes to read.")
    n = int(sample_size)
    if not 1 <= n <= 5000:
        raise AdmError("evidence_slice_invalid", "The sample size must be between 1 and 5000.", value=n)
    table = table_fqn(schema_fqn, "observed_decision_provenance")
    where = [
        "dna_contribution_flag = true",
        as_of_clause("observed_decision_provenance", at=as_of),
        f"event_at >= {ts_lit(window_start)}",
        f"event_at < {ts_lit(window_end)}",
        f"action_code IN {_in_list(list(action_codes))}",
    ]
    if object_refs:
        where.append(f"object_ref IN {_in_list(list(object_refs))}")
    return (
        "SELECT observation_id, business_decision_id, action_code, object_ref, actor_entity_id, actor_role, "
        "event_at, approval_evidence_id, context, observation_status "
        f"FROM {table} WHERE " + " AND ".join(where) + " "
        f"ORDER BY xxhash64({lit(seed)}, observation_id), observation_id "
        f"LIMIT {n}"
    )


def identity_links_sql(schema_fqn: str, *, as_of: datetime, aliases: Optional[Sequence[str]] = None) -> str:
    """VERIFIED identity links valid at ``as_of``. Unverified and rejected links are never read."""
    table = table_fqn(schema_fqn, "source_identity_map")
    where = [
        "verification_status = 'VERIFIED'",
        as_of_clause("source_identity_map", at=as_of, valid_at=as_of),
    ]
    if aliases is not None:
        if not aliases:
            where.append("1 = 0")
        else:
            where.append(f"source_id IN {_in_list(list(aliases))}")
    return (
        "SELECT identity_link_id, entity_id, source_id, valid_from, valid_to "
        f"FROM {table} WHERE " + " AND ".join(where) + " "
        "ORDER BY source_id, identity_link_id LIMIT 10000"
    )


def identity_index(links: Iterable[Dict[str, Any]]) -> Tuple[Dict[str, str], Dict[str, str]]:
    """``(alias_by_entity, entity_by_alias)`` from VERIFIED links (ADM section 6.1).

    An alias that maps to two different entities is ambiguous and maps to nothing, so it
    fails closed. An entity with several unambiguous aliases reports the first in source-id order.
    """
    pairs = [
        (str(link.get("source_id") or "").strip(), str(link.get("entity_id") or "").strip())
        for link in links
    ]
    pairs = [(a, e) for a, e in pairs if a and e]
    candidates: Dict[str, set] = {}
    for alias, entity in pairs:
        candidates.setdefault(alias, set()).add(entity)
    entity_by_alias = {a: next(iter(es)) for a, es in candidates.items() if len(es) == 1}
    alias_by_entity: Dict[str, str] = {}
    for alias in sorted(entity_by_alias):
        alias_by_entity.setdefault(entity_by_alias[alias], alias)
    return alias_by_entity, entity_by_alias


def entitlements_sql(schema_fqn: str, *, entity_id: str, role_id: str, as_of: datetime) -> str:
    table = table_fqn(schema_fqn, "entitlements")
    return (
        "SELECT entitlement_id, entity_id, role_id, valid_from, valid_to, revoked_at, claim_status "
        f"FROM {table} WHERE entity_id = {lit(entity_id)} AND role_id = {lit(role_id)} "
        f"AND {as_of_clause('entitlements', at=as_of)} "
        "ORDER BY valid_from DESC, entitlement_id LIMIT 50"
    )


def roles_sql(schema_fqn: str, *, role_id: str, as_of: datetime) -> str:
    table = table_fqn(schema_fqn, "roles")
    return (
        "SELECT role_id, permissions, valid_from, valid_to "
        f"FROM {table} WHERE role_id = {lit(role_id)} "
        f"AND {as_of_clause('roles', at=as_of)} "
        "ORDER BY valid_from DESC LIMIT 20"
    )


def delegations_sql(schema_fqn: str, *, entity_id: str, as_of: datetime) -> str:
    table = table_fqn(schema_fqn, "delegation_chains")
    return (
        "SELECT delegation_id, grantee_entity_id, role_id, valid_from, valid_to "
        f"FROM {table} WHERE grantee_entity_id = {lit(entity_id)} "
        f"AND {as_of_clause('delegation_chains', at=as_of)} "
        "ORDER BY valid_from DESC, delegation_id LIMIT 50"
    )


# --------------------------------------------------------------------------- #
# Typed values                                                                #
# --------------------------------------------------------------------------- #

_MANIFEST_FAMILY = {
    "STRING": STRING, "TIMESTAMP": TIMESTAMP, "TIMESTAMP_NTZ": TIMESTAMP,
    "DECIMAL": DECIMAL, "DOUBLE": DECIMAL, "FLOAT": DECIMAL,
    "INT": INT, "INTEGER": INT, "BIGINT": INT, "LONG": INT, "SMALLINT": INT, "SHORT": INT, "TINYINT": INT,
    "BOOLEAN": BOOLEAN,
}


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def parse_timestamp(value: Any) -> Optional[datetime]:
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        return _as_utc(value)
    text = str(value).strip().replace("Z", "+00:00")
    try:
        return _as_utc(datetime.fromisoformat(text))
    except ValueError:
        return None


def parse_share(value: Any) -> Optional[float]:
    """A number, or a percentage string read as a share (``"15%"`` -> 0.15)."""
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value).strip()
    try:
        if text.endswith("%"):
            return float(text[:-1]) / 100.0
        return float(text)
    except ValueError:
        return None


def coerce_value(value: Any, logical: str) -> Any:
    """One value as its logical type. Unparseable values become None (an unknown, never a guess)."""
    if value is None:
        return None
    if logical == STRING:
        return str(value)
    if logical == TIMESTAMP:
        return parse_timestamp(value)
    if logical in (DECIMAL, INT):
        number = parse_share(value)
        if number is None:
            return None
        return int(number) if logical == INT and number.is_integer() else number
    if logical == BOOLEAN:
        if isinstance(value, bool):
            return value
        text = str(value).strip().lower()
        if text in ("true", "t", "1", "yes"):
            return True
        if text in ("false", "f", "0", "no"):
            return False
        return None
    return value


def typed_rows(columns: Sequence[Tuple[str, str]], data: Sequence[Sequence[Any]]) -> List[Dict[str, Any]]:
    """Result rows as dicts, each value coerced by its manifest type (``(name, type_name)`` pairs).

    Only the columns asked for come back; unknown manifest types are kept as text.
    """
    families = [(name, _MANIFEST_FAMILY.get(str(type_name or "").upper(), STRING)) for name, type_name in columns]
    out: List[Dict[str, Any]] = []
    for raw in data:
        out.append({name: coerce_value(value, family) for (name, family), value in zip(families, raw)})
    return out


def json_object(raw: Any) -> Dict[str, Any]:
    """A JSON object column as a dict. Anything else (null, a list, bad JSON) is an empty dict."""
    if isinstance(raw, dict):
        return dict(raw)
    if not raw:
        return {}
    try:
        value = json.loads(raw)
    except (TypeError, ValueError):
        return {}
    return value if isinstance(value, dict) else {}


def observation_row(obs: Dict[str, Any], *, actor_identity: Optional[str], identity_status: str) -> Dict[str, Any]:
    """One observed decision as an evidence row the AR's rules evaluate.

    Canonical names (``action``, ``object_id``, ``actor_identity``, ``value``...) come from the
    ADM columns; the context JSON supplies the rest. A context key never overrides a canonical
    name. ``actor_identity`` is the VERIFIED alias, or None when the actor has no verified link
    (the row's own rules then see an unknown and skip the row).
    """
    ctx = json_object(obs.get("context"))
    row: Dict[str, Any] = {k: v for k, v in ctx.items() if k not in CANONICAL_ROW_KEYS}
    value = ctx.get("value", ctx.get("amount"))
    row.update({
        "observation_id": obs.get("observation_id"),
        "business_decision_id": obs.get("business_decision_id"),
        "action": obs.get("action_code"),
        "object_id": obs.get("object_ref"),
        "actor_identity": actor_identity,
        "actor_entity_id": obs.get("actor_entity_id"),
        "actor_role": obs.get("actor_role"),
        "actor_identity_status": identity_status,
        "event_at": obs.get("event_at"),
        "approval_evidence_id": obs.get("approval_evidence_id"),
        "value": parse_share(value) if value is not None else None,
        "escalated": ctx.get("escalated"),
        "cosign_present": ctx.get("cosign_present"),
    })
    return row


# --------------------------------------------------------------------------- #
# Resolve-time facts (ADM section 4.2: current state and revocation)          #
# --------------------------------------------------------------------------- #

def in_validity(valid_from: Any, valid_to: Any, at: datetime) -> bool:
    """Half-open ``[valid_from, valid_to)`` at ``at``. A null ``valid_from`` never holds."""
    start = parse_timestamp(valid_from)
    end = parse_timestamp(valid_to)
    at_utc = _as_utc(at)
    return start is not None and start <= at_utc and (end is None or at_utc < end)


def entitlement_is_current(row: Dict[str, Any], at: datetime) -> bool:
    """Verified, in its validity window, and not revoked at ``at``. ``valid_to IS NULL`` alone is not proof."""
    if (row.get("claim_status") or "").upper() != "VERIFIED":
        return False
    if not in_validity(row.get("valid_from"), row.get("valid_to"), at):
        return False
    revoked = parse_timestamp(row.get("revoked_at"))
    return revoked is None or revoked > _as_utc(at)


def role_codes(row: Dict[str, Any]) -> Optional[List[str]]:
    """The permission codes of a role row (a JSON list of strings, or ``{"codes": [...]}``), or None."""
    raw = row.get("permissions")
    value: Any = raw
    if isinstance(raw, str):
        try:
            value = json.loads(raw)
        except (TypeError, ValueError):
            return None
    if isinstance(value, dict):
        value = value.get("codes", value.get("permissions"))
    if not isinstance(value, list):
        return None
    return sorted({str(v) for v in value if str(v).strip()})


def derive_facts(
    *, identity: Optional[Dict[str, Any]], entitlements: Sequence[Dict[str, Any]],
    roles: Sequence[Dict[str, Any]], delegations: Sequence[Dict[str, Any]], at: datetime,
) -> Dict[str, Any]:
    """The ``fact.*`` namespace for one request. Missing inputs give None (an unknown the DSL fails closed on)."""
    entity = (identity or {}).get("entity_id") if identity else None
    current = [e for e in entitlements if entitlement_is_current(e, at)]
    current.sort(key=lambda e: parse_timestamp(e.get("valid_from")) or _as_utc(at), reverse=True)
    newest = current[0] if current else None
    role = next((r for r in roles if in_validity(r.get("valid_from"), r.get("valid_to"), at)), None)
    facts: Dict[str, Any] = {
        "identity_verified": bool(entity),
        "entity_id": entity,
        "entitlement_current": bool(current) if entity else None,
        "entitlement_valid_from": _iso(parse_timestamp(newest.get("valid_from"))) if newest else None,
        "entitlement_valid_to": _iso(parse_timestamp(newest.get("valid_to"))) if newest else None,
        "role_codes": role_codes(role) if role else None,
        "delegation_active": any(in_validity(d.get("valid_from"), d.get("valid_to"), at) for d in delegations) if entity else None,
    }
    return facts


def _iso(value: Optional[datetime]) -> Optional[str]:
    return value.isoformat() if value else None


def fact_references(texts: Iterable[str]) -> set:
    """The ``fact.<name>`` names the given rule texts read."""
    found: set = set()
    for text in texts:
        found.update(_FACT_REF_RE.findall(text or ""))
    return found


def unknown_fact_references(texts: Iterable[str]) -> List[str]:
    """``fact.<name>`` references whose name isn't a known fact (refused on save)."""
    return sorted(n for n in fact_references(texts) if n not in FACT_TYPES)
