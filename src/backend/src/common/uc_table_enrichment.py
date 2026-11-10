"""Governed tags and lineage counts for Unity Catalog tables in compliance rules.

``tables.list`` returns columns (see ``uc_table_columns``) but no tags and no
lineage. This module adds, for the tables of one catalog at a time:

- ``tags`` (``{tag_name: value}``, True for a tag without a value) and
  ``columns[].tags``, from ``system.information_schema.table_tags`` and
  ``column_tags``, in one statement per catalog;
- ``upstream_count`` / ``downstream_count``: distinct source / target tables in
  ``system.access.table_lineage`` over the last ``LINEAGE_WINDOW_DAYS`` days,
  in one statement per catalog.

Both statements run on the SQL warehouse and are filtered by the catalog and
the schemas in scope, so a run reads only what its rule can see. A source that
can't be read (no warehouse, no grant, a query error) leaves its fields out and
records why in ``entity[UNAVAILABLE_KEY]``; the caller decides what a rule that
needs them gets. The query building and row mapping are pure; the only I/O is
the ``SqlRunner`` passed in, so assets pointing to a UC table can reuse this.
"""

from typing import Any, Dict, Iterable, List, Optional, Protocol, Set, Tuple

from src.common.compliance_dsl import (
    BinaryOp, CaseExpression, FunctionCall, ListLiteral, PropertyAccess, TokenType, UnaryOp,
)
from src.common.logging import get_logger

logger = get_logger(__name__)

TABLE_TAGS_SOURCE = 'system.information_schema.table_tags'
COLUMN_TAGS_SOURCE = 'system.information_schema.column_tags'
LINEAGE_SOURCE = 'system.access.table_lineage'

# Lineage events older than this are not counted. system.access.table_lineage
# keeps a year of events; 90 days bounds the scan and still sees every table a
# pipeline that runs at least quarterly writes.
LINEAGE_WINDOW_DAYS = 90

# Field groups, each read by one statement, and the entity fields they give
TAGS = 'tags'
LINEAGE = 'lineage'
GROUP_FIELDS = {
    TAGS: ('tags',),
    LINEAGE: ('upstream_count', 'downstream_count'),
}
GROUP_SOURCE = {
    TAGS: f'{TABLE_TAGS_SOURCE}, {COLUMN_TAGS_SOURCE}',
    LINEAGE: LINEAGE_SOURCE,
}
FIELD_GROUP = {field: group for group, fields in GROUP_FIELDS.items() for field in fields}

# Entity key with the fields that could not be loaded: {field: {source, reason}}
UNAVAILABLE_KEY = '_unavailable'

# Why a source could not be read (codes, also shown in run warnings)
REASON_NO_WAREHOUSE = 'no_warehouse'
REASON_NO_ACCESS = 'no_access'
REASON_QUERY_FAILED = 'query_failed'


class SourceUnavailable(Exception):
    """A system table could not be read; ``reason`` is one of the REASON_* codes."""

    def __init__(self, reason: str, detail: str = ''):
        super().__init__(detail or reason)
        self.reason = reason


class SqlRunner(Protocol):
    def rows(self, statement: str, parameters: Dict[str, str]) -> List[Dict[str, Any]]:
        """Rows of a parameterised statement; raises SourceUnavailable."""
        ...


# --- which fields a rule reads -------------------------------------------------

def fields_read(*nodes: Any) -> Set[str]:
    """Entity fields the given DSL AST nodes read.

    ``HAS_TAG`` / ``TAG`` read ``tags``; ``x.field`` reads ``field``.
    """
    found: Set[str] = set()
    stack = [n for n in nodes if n is not None]
    while stack:
        node = stack.pop()
        if isinstance(node, PropertyAccess):
            found.add(node.property)
        elif isinstance(node, FunctionCall):
            if node.name in ('HAS_TAG', 'TAG'):
                found.add('tags')
            stack.extend(node.args)
        elif isinstance(node, BinaryOp):
            stack.extend((node.left, node.right))
        elif isinstance(node, UnaryOp):
            stack.append(node.operand)
        elif isinstance(node, ListLiteral):
            stack.extend(node.values)
        elif isinstance(node, CaseExpression):
            stack.extend(n for n in (node.subject, node.else_clause) if n is not None)
            for condition, result in node.when_clauses:
                stack.extend((condition, result))
    return found


def conditions_without(node: Any, fields: Iterable[str]) -> List[Any]:
    """The AND-ed parts of a WHERE clause that read none of ``fields``.

    Every part must hold for the WHERE to hold, so an entity for which one of
    them is false is out of scope whatever the other parts give.
    """
    excluded = set(fields)
    parts: List[Any] = []
    stack = [node] if node is not None else []
    while stack:
        current = stack.pop()
        if isinstance(current, BinaryOp) and current.op == TokenType.AND:
            stack.extend((current.right, current.left))
        elif not fields_read(current) & excluded:
            parts.append(current)
    return parts


def groups_for_fields(fields: Iterable[str]) -> Set[str]:
    """Field groups (TAGS / LINEAGE) to load for the given fields."""
    return {FIELD_GROUP[f] for f in fields if f in FIELD_GROUP}


def unavailable_fields_read(entity: Dict[str, Any], fields: Iterable[str]) -> Dict[str, Any]:
    """The fields among ``fields`` that could not be loaded for ``entity``."""
    missing = entity.get(UNAVAILABLE_KEY) or {}
    return {f: missing[f] for f in fields if f in missing}


# --- statements ------------------------------------------------------------------

def _scope(catalog: str, schemas: Iterable[str]) -> Tuple[str, Dict[str, str]]:
    names = sorted({s.lower() for s in schemas})
    params = {'catalog': catalog.lower()}
    params.update({f's{i}': name for i, name in enumerate(names)})
    placeholders = ', '.join(f':s{i}' for i in range(len(names)))
    return placeholders, params


def tags_statement(catalog: str, schemas: Iterable[str]) -> Tuple[str, Dict[str, str]]:
    """Table and column tags of the given schemas of one catalog."""
    placeholders, params = _scope(catalog, schemas)
    where = f"catalog_name = :catalog AND schema_name IN ({placeholders})"
    statement = (
        f"SELECT schema_name, table_name, CAST(NULL AS STRING) AS column_name, "
        f"tag_name, tag_value FROM {TABLE_TAGS_SOURCE} WHERE {where} "
        f"UNION ALL "
        f"SELECT schema_name, table_name, column_name, tag_name, tag_value "
        f"FROM {COLUMN_TAGS_SOURCE} WHERE {where}"
    )
    return statement, params


def lineage_statement(catalog: str, schemas: Iterable[str]) -> Tuple[str, Dict[str, str]]:
    """Distinct upstream / downstream tables of the tables in the given schemas."""
    placeholders, params = _scope(catalog, schemas)
    window = f"event_time >= current_timestamp() - INTERVAL {LINEAGE_WINDOW_DAYS} DAYS"
    statement = (
        f"SELECT 'upstream' AS direction, lower(target_table_full_name) AS table_full_name, "
        f"COUNT(DISTINCT lower(source_table_full_name)) AS table_count "
        f"FROM {LINEAGE_SOURCE} WHERE {window} "
        f"AND lower(target_table_catalog) = :catalog "
        f"AND lower(target_table_schema) IN ({placeholders}) "
        f"AND source_table_full_name IS NOT NULL "
        f"AND lower(source_table_full_name) <> lower(target_table_full_name) "
        f"GROUP BY lower(target_table_full_name) "
        f"UNION ALL "
        f"SELECT 'downstream', lower(source_table_full_name), "
        f"COUNT(DISTINCT lower(target_table_full_name)) "
        f"FROM {LINEAGE_SOURCE} WHERE {window} "
        f"AND lower(source_table_catalog) = :catalog "
        f"AND lower(source_table_schema) IN ({placeholders}) "
        f"AND target_table_full_name IS NOT NULL "
        f"AND lower(source_table_full_name) <> lower(target_table_full_name) "
        f"GROUP BY lower(source_table_full_name)"
    )
    return statement, params


# --- rows to fields ----------------------------------------------------------------

def _tag_value(value: Any) -> Any:
    # A tag without a value is stored as '' (or NULL); rules see True, as for app tags
    return True if value is None or value == '' else value


def _table_key(entity: Dict[str, Any]) -> Tuple[str, str]:
    return str(entity.get('schema') or '').lower(), str(entity.get('name') or '').lower()


def apply_tag_rows(entities: List[Dict[str, Any]], rows: Iterable[Dict[str, Any]]) -> None:
    """Set ``tags`` and ``columns[].tags`` on each entity (empty when it has none)."""
    by_key = {_table_key(e): e for e in entities}
    for entity in entities:
        entity['tags'] = {}
        for column in entity.get('columns') or []:
            column['tags'] = {}
    columns_by_key = {
        key: {str(c.get('name') or '').lower(): c for c in e.get('columns') or []}
        for key, e in by_key.items()
    }
    for row in rows:
        key = (str(row.get('schema_name') or '').lower(),
               str(row.get('table_name') or '').lower())
        entity = by_key.get(key)
        if entity is None or not row.get('tag_name'):
            continue
        value = _tag_value(row.get('tag_value'))
        column_name = row.get('column_name')
        if column_name is None:
            entity['tags'][row['tag_name']] = value
            continue
        column = columns_by_key[key].get(str(column_name).lower())
        if column is not None:
            column['tags'][row['tag_name']] = value


def apply_lineage_rows(entities: List[Dict[str, Any]], rows: Iterable[Dict[str, Any]]) -> None:
    """Set ``upstream_count`` / ``downstream_count`` (0 for a table with no event)."""
    counts: Dict[Tuple[str, str], int] = {}
    for row in rows:
        name = str(row.get('table_full_name') or '').lower()
        counts[(str(row.get('direction')), name)] = int(row.get('table_count') or 0)
    for entity in entities:
        name = str(entity.get('full_name') or '').lower()
        entity['upstream_count'] = counts.get(('upstream', name), 0)
        entity['downstream_count'] = counts.get(('downstream', name), 0)


def mark_unavailable(entities: List[Dict[str, Any]], group: str, reason: str) -> None:
    """Record on each entity that the fields of ``group`` could not be loaded."""
    for entity in entities:
        missing = entity.setdefault(UNAVAILABLE_KEY, {})
        for field in GROUP_FIELDS[group]:
            missing[field] = {'source': GROUP_SOURCE[group], 'reason': reason}


# --- loading -------------------------------------------------------------------------

def enrich_catalog_tables(
    catalog: str,
    entities: List[Dict[str, Any]],
    groups: Set[str],
    runner: Optional[SqlRunner],
) -> None:
    """Add the fields of ``groups`` to the table entities of one catalog, in place.

    One statement per group, scoped to the schemas of ``entities``. Without a
    runner, or when a statement fails, the group's fields are left out and
    marked unavailable with the reason.
    """
    if not entities or not groups:
        return
    schemas = {str(e.get('schema') or '') for e in entities}
    steps = (
        (TAGS, tags_statement, apply_tag_rows),
        (LINEAGE, lineage_statement, apply_lineage_rows),
    )
    for group, build, apply in steps:
        if group not in groups:
            continue
        if runner is None:
            mark_unavailable(entities, group, REASON_NO_WAREHOUSE)
            continue
        statement, params = build(catalog, schemas)
        try:
            rows = runner.rows(statement, params)
        except SourceUnavailable as e:
            logger.warning(
                "Could not read %s for the tables of catalog %s (%s): %s",
                GROUP_SOURCE[group], catalog, e.reason, e,
            )
            mark_unavailable(entities, group, e.reason)
            continue
        apply(entities, rows)


class WarehouseSqlRunner:
    """Runs statements on a SQL warehouse through the Statement Execution API."""

    WAIT_TIMEOUT = '50s'

    def __init__(self, workspace_client: Any, warehouse_id: str):
        self.ws = workspace_client
        self.warehouse_id = warehouse_id

    def rows(self, statement: str, parameters: Dict[str, str]) -> List[Dict[str, Any]]:
        from databricks.sdk.service.sql import (
            ExecuteStatementRequestOnWaitTimeout, StatementParameterListItem,
        )

        try:
            response = self.ws.statement_execution.execute_statement(
                statement=statement,
                warehouse_id=self.warehouse_id,
                parameters=[
                    StatementParameterListItem(name=k, value=v) for k, v in parameters.items()
                ],
                wait_timeout=self.WAIT_TIMEOUT,
                on_wait_timeout=ExecuteStatementRequestOnWaitTimeout.CANCEL,
            )
            state = getattr(getattr(response.status, 'state', None), 'value', None)
            if state != 'SUCCEEDED':
                error = getattr(response.status, 'error', None)
                raise SourceUnavailable(
                    _reason(getattr(error, 'message', '') or ''),
                    f"statement {state}: {getattr(error, 'message', '')}",
                )
            columns = [c.name for c in response.manifest.schema.columns]
            data = list(getattr(response.result, 'data_array', None) or [])
            chunk = getattr(response.result, 'next_chunk_index', None)
            while chunk is not None:
                part = self.ws.statement_execution.get_statement_result_chunk_n(
                    response.statement_id, chunk,
                )
                data.extend(part.data_array or [])
                chunk = part.next_chunk_index
        except SourceUnavailable:
            raise
        except Exception as e:
            raise SourceUnavailable(_reason(str(e)), str(e)) from e
        return [dict(zip(columns, row)) for row in data]


def _reason(message: str) -> str:
    upper = message.upper()
    if 'PERMISSION' in upper or 'NOT AUTHORIZED' in upper or 'INSUFFICIENT' in upper:
        return REASON_NO_ACCESS
    return REASON_QUERY_FAILED
