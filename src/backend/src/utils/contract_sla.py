"""The contract page's SLA requirements, stored as ODCS ``slaProperties``.

The SLA form edits four values (uptime target, maximum downtime, query
response time, data freshness). They have no columns of their own: each one is
an SLA property named after its API field, so it also goes out with the ODCS
export and comes back on import. Other SLA properties are left alone.
"""
from typing import Any, Dict, Iterable, Optional

from src.db_models.data_contracts import DataContractSlaPropertyDb

# API field (also the SLA property name) -> (unit, number type)
LEGACY_SLA_FIELDS: Dict[str, tuple] = {
    'uptimeTarget': ('percent', float),
    'maxDowntimeMinutes': ('minutes', int),
    'queryResponseTimeMs': ('milliseconds', int),
    'dataFreshnessMinutes': ('minutes', int),
}

_SNAKE_TO_FIELD = {
    'uptime_target': 'uptimeTarget',
    'max_downtime_minutes': 'maxDowntimeMinutes',
    'query_response_time_ms': 'queryResponseTimeMs',
    'data_freshness_minutes': 'dataFreshnessMinutes',
}


def _number(raw: Any, kind: type) -> Optional[float]:
    try:
        value = float(raw)
    except (TypeError, ValueError):
        return None
    return int(value) if kind is int and value.is_integer() else value


def legacy_sla_from_rows(rows: Iterable[DataContractSlaPropertyDb]) -> Optional[Dict[str, Any]]:
    """The four SLA requirements found among a contract's SLA properties, or
    ``None`` when it has none of them. A value that isn't a number is skipped."""
    sla: Dict[str, Any] = {}
    for row in rows or []:
        spec = LEGACY_SLA_FIELDS.get(row.property)
        if spec is None or row.value is None:
            continue
        value = _number(row.value, spec[1])
        if value is not None:
            sla[row.property] = value
    return sla or None


def apply_legacy_sla(db, contract_id: str, sla: Optional[Dict[str, Any]]) -> None:
    """Store the SLA form's values: each of the four fields replaces its SLA
    property, and a field left empty removes it."""
    values: Dict[str, Any] = {}
    for key, value in (sla or {}).items():
        field = _SNAKE_TO_FIELD.get(key, key)
        if field in LEGACY_SLA_FIELDS:
            values[field] = value

    db.query(DataContractSlaPropertyDb).filter(
        DataContractSlaPropertyDb.contract_id == contract_id,
        DataContractSlaPropertyDb.property.in_(list(LEGACY_SLA_FIELDS)),
    ).delete(synchronize_session=False)

    for field, (unit, _kind) in LEGACY_SLA_FIELDS.items():
        value = values.get(field)
        if value is None:
            continue
        db.add(DataContractSlaPropertyDb(
            contract_id=contract_id, property=field, value=str(value), unit=unit,
        ))
