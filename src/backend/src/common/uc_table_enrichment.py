"""Governed tags and lineage counts for Unity Catalog tables in compliance rules.

``tables.list`` returns columns (see ``uc_table_columns``) but no tags and no
lineage. This module adds, for the tables of one catalog at a time:

- ``tags`` (``{tag_name: value}``, True for a tag without a value), from
  ``system.information_schema.table_tags``, in one statement per catalog;
- ``upstream_count`` / ``downstream_count``: distinct source / target tables in
  ``system.access.table_lineage`` over the last ``LINEAGE_WINDOW_DAYS`` days,
  in one statement per catalog.

- the key column fields (``primary_key_columns`` ...), from one ``tables.get`` per
  table: ``tables.list`` does not return ``table_constraints``, so a listed table
  can't tell a table without keys from a table whose keys weren't read. Only the
  tables a rule selects are read, up to ``MAX_TABLE_READS_PER_RUN`` reads and
  ``MAX_TABLE_READ_SECONDS`` per policy run, counted from the first read (the
  table listing and the LLM checks before it spend none of it).

The two statements run on the SQL warehouse and are filtered by the catalog and
the schemas in scope, so a run reads only what its rule can see. A source that
can't be read (no warehouse, no grant, a query error) leaves its fields out and
records why in ``entity[UNAVAILABLE_KEY]``; the caller decides what a rule that
needs them gets. The query building and row mapping are pure; the only I/O is
the ``SqlRunner`` passed in, so assets pointing to a UC table can reuse this.
"""

import json
import time
from typing import Any, Callable, Dict, Iterable, List, Optional, Protocol, Set, Tuple

from src.common.compliance_dsl import (
    BinaryOp, CaseExpression, FunctionCall, ListLiteral, PropertyAccess, TokenType, UnaryOp,
)
from src.common.logging import get_logger
from src.common.uc_table_columns import KEY_FIELDS, key_column_fields

logger = get_logger(__name__)

TABLE_TAGS_SOURCE = 'system.information_schema.table_tags'
LINEAGE_SOURCE = 'system.access.table_lineage'

# Lineage events older than this are not counted. system.access.table_lineage
# keeps a year of events; 90 days bounds the scan and still sees every table a
# pipeline that runs at least quarterly writes.
LINEAGE_WINDOW_DAYS = 90

# Field groups, each read by one statement, and the entity fields they give
TAGS = 'tags'
LINEAGE = 'lineage'
KEYS = 'keys'
GROUP_FIELDS = {
    TAGS: ('tags',),
    LINEAGE: ('upstream_count', 'downstream_count'),
    KEYS: KEY_FIELDS,
}
TABLE_GET_SOURCE = 'unity_catalog.tables.get'
GROUP_SOURCE = {
    TAGS: TABLE_TAGS_SOURCE,
    LINEAGE: LINEAGE_SOURCE,
    KEYS: TABLE_GET_SOURCE,
}
FIELD_GROUP = {field: group for group, fields in GROUP_FIELDS.items() for field in fields}

# Entity key with the fields that could not be loaded: {field: {source, reason}}
UNAVAILABLE_KEY = '_unavailable'
# details_json code of a result not evaluated because a field could not be loaded
NOT_EVALUATED_CODE = 'rule_field_unavailable'


def result_not_evaluated(details_json: Optional[str]) -> bool:
    """Whether a stored result's details say it was not evaluated (parsed, not matched)."""
    if not details_json:
        return False
    try:
        details = json.loads(details_json)
    except (TypeError, ValueError):
        return False
    return isinstance(details, dict) and details.get('code') == NOT_EVALUATED_CODE

# Why a source could not be read (codes, also shown in run warnings)
REASON_NO_WAREHOUSE = 'no_warehouse'
REASON_NO_ACCESS = 'no_access'
REASON_QUERY_FAILED = 'query_failed'
REASON_TIMED_OUT = 'timed_out'
REASON_TRANSIENT = 'transient'
REASON_NOT_FOUND = 'not_found'
REASON_BUDGET_EXCEEDED = 'budget_exceeded'
# Not read for this object type (catalogs, schemas, functions, volumes have no tags yet)
REASON_NOT_LOADED = 'not_loaded'
# Why a table's constraints could not be read with ``tables.get``
REASON_TABLE_NO_ACCESS = 'table_no_access'
REASON_TABLE_NOT_FOUND = 'table_not_found'
REASON_TABLE_READ_FAILED = 'table_read_failed'
REASON_TABLE_READ_LIMIT = 'table_read_limit'
NOT_LOADED_SOURCE = 'unity_catalog'

# Statements one policy run may send. The policies of a compliance-checks job
# run share the cached rows, but each policy run has its own count, so results
# don't depend on the order the policies run in.
MAX_STATEMENTS_PER_RUN = 100
# Time one policy run may spend on statements, from its start. A user run is
# awaited by their HTTP request; past this, statements still to send and the one
# running are not waited for (reason ``timed_out``).
MAX_RUN_SECONDS = 900
# ``tables.get`` calls one policy run may make for key columns, and the time it
# may spend on them, counted from the first call
MAX_TABLE_READS_PER_RUN = 2000
MAX_TABLE_READ_SECONDS = 600
# Rows kept for reuse by later rules of the same run; past this, rows are not kept
MAX_CACHED_ROWS = 200_000
# Tables enriched together: the loader yields a catalog's tables in chunks of
# whole schemas of about this size, so a run that stops at its limit reads no
# more, and one statement result stays small
CHUNK_TABLES = 500


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
    """Field groups (TAGS / LINEAGE / KEYS) to load for the given fields."""
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
    """Table tags of the given schemas of one catalog.

    Column tags are not read: no rule can reach them (the DSL has no
    quantifier over ``columns``).
    """
    placeholders, params = _scope(catalog, schemas)
    # Both sides lowered, as in the lineage statement: the parameters are
    # lowercase and the system table may keep the names' case
    where = f"lower(catalog_name) = :catalog AND lower(schema_name) IN ({placeholders})"
    statement = (
        f"SELECT schema_name, table_name, tag_name, tag_value "
        f"FROM {TABLE_TAGS_SOURCE} WHERE {where}"
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
    """Set ``tags`` on each entity (empty when it has none)."""
    by_key = {_table_key(e): e for e in entities}
    for entity in entities:
        entity['tags'] = {}
    for row in rows:
        key = (str(row.get('schema_name') or '').lower(),
               str(row.get('table_name') or '').lower())
        entity = by_key.get(key)
        if entity is None or not row.get('tag_name'):
            continue
        entity['tags'][row['tag_name']] = _tag_value(row.get('tag_value'))


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


def mark_tags_not_loaded(entity: Dict[str, Any]) -> Dict[str, Any]:
    """Mark ``tags`` unavailable (``not_loaded``) on a UC object whose tags aren't read.

    Only tables and views get their governed tags. Without the marker, a
    catalog or schema would have no ``tags`` and ``NOT HAS_TAG('x')`` would pass
    it; with it, a rule reading tags reports it as not evaluated.
    """
    entity.setdefault(UNAVAILABLE_KEY, {})['tags'] = {
        'source': NOT_LOADED_SOURCE, 'reason': REASON_NOT_LOADED,
    }
    return entity


# --- statement reuse and budget ------------------------------------------------------

class StatementCache:
    """The statements of a run: their rows, reused by the later rules that send
    the same statement (same catalog, field group and schemas), and the budget
    of the current policy run.

    A statement that failed is not sent again in the same policy run. A later
    policy run of the job sends it again after a failure that may pass then
    (``timed_out``, ``transient``, ``query_failed``); one that won't
    (``no_access``, ``not_found``) is kept for the whole job. Past ``max_statements`` sent by
    the current policy run, a new statement is not sent and its group is
    unavailable (reason ``budget_exceeded``); past ``max_run_seconds`` since
    the policy run started, it is not sent either (reason ``timed_out``), and a
    statement still running then is cancelled. ``start_run`` begins the next
    policy run of a job: a new count and deadline, the same cached rows.
    """

    def __init__(
        self, max_statements: int = MAX_STATEMENTS_PER_RUN,
        max_cached_rows: int = MAX_CACHED_ROWS,
        max_run_seconds: float = MAX_RUN_SECONDS,
        clock: Callable[[], float] = time.monotonic,
    ):
        self.max_statements = max_statements
        self.max_cached_rows = max_cached_rows
        self.max_run_seconds = max_run_seconds
        self._clock = clock
        self._cached_rows = 0
        self._results: Dict[Any, Any] = {}
        # Failures that may pass on a later try, kept for the current policy run only
        self._run_failures: Dict[Any, SourceUnavailable] = {}
        self.start_run()

    def start_run(self) -> None:
        """Begin a policy run: statements sent and the deadline start over, and the
        statements that failed for a passing reason are sent again."""
        self.sent = 0
        self.deadline = self._clock() + self.max_run_seconds
        self._run_failures = {}

    def runner(self, inner: SqlRunner) -> SqlRunner:
        """``inner`` with this run's reuse and budget."""
        return _CachedRunner(inner, self)

    def rows(self, inner: SqlRunner, statement: str, parameters: Dict[str, str]):
        key = (statement, tuple(sorted(parameters.items())))
        if key in self._run_failures:
            raise self._run_failures[key]
        if key in self._results:
            result = self._results[key]
            if isinstance(result, SourceUnavailable):
                raise result
            return result
        if self.sent >= self.max_statements:
            raise SourceUnavailable(
                REASON_BUDGET_EXCEEDED, f"run already sent {self.sent} statements",
            )
        if self._clock() >= self.deadline:
            # Not cached: the next policy run of the job may still send it
            raise SourceUnavailable(
                REASON_TIMED_OUT, f"run past its {self.max_run_seconds}s for statements",
            )
        self.sent += 1
        try:
            if isinstance(inner, WarehouseSqlRunner):
                result = inner.rows(statement, parameters, deadline=self.deadline)
            else:
                result = inner.rows(statement, parameters)
        except SourceUnavailable as e:
            if e.reason in _LASTING_REASONS:
                self._results[key] = e  # no grant or no table: the same for the whole job
            elif not (e.reason == REASON_TIMED_OUT and self._clock() >= self.deadline):
                # The next policy run tries again (also when cut short by the deadline)
                self._run_failures[key] = e
            raise
        if self._cached_rows + len(result) <= self.max_cached_rows:
            self._cached_rows += len(result)
            self._results[key] = result
        return result


# Statement failures a later policy run of the job would get too
_LASTING_REASONS = (REASON_NO_ACCESS, REASON_NOT_FOUND)


class _CachedRunner:
    def __init__(self, inner: SqlRunner, cache: StatementCache):
        self.inner = inner
        self.cache = cache

    def rows(self, statement: str, parameters: Dict[str, str]) -> List[Dict[str, Any]]:
        return self.cache.rows(self.inner, statement, parameters)


# --- the rule object of a table ---------------------------------------------------

VIEW_TABLE_TYPES = ('VIEW', 'MATERIALIZED_VIEW', 'METRIC_VIEW')


def table_entity(
    table: Any, catalog: Optional[str] = None, schema: Optional[str] = None,
) -> Dict[str, Any]:
    """The rule object of one Unity Catalog table or view (a ``TableInfo``).

    The one builder for every caller that evaluates DSL rules on a UC table:
    the compliance loader and, for an asset that points to a table, its
    maturity gates. Add tags, lineage and the key columns with ``enrich_tables``:
    the listing has no ``table_constraints``, so the key fields are left out here.

    Tag keys are the governed tags' keys as Unity Catalog stores them
    (``tag_name``), with no namespace: unlike app tags (``namespace/name`` or
    the name), ``HAS_TAG('ns/x')`` doesn't match a UC tag ``x``.
    """
    from src.common.uc_table_columns import table_column_fields

    catalog = catalog or getattr(table, 'catalog_name', None)
    schema = schema or getattr(table, 'schema_name', None)
    # The SDK returns a TableType enum; rules compare strings.
    table_type = getattr(table, 'table_type', 'TABLE')
    table_type = getattr(table_type, 'value', table_type)
    full_name = getattr(table, 'full_name', None) or f"{catalog}.{schema}.{table.name}"
    return {
        'type': 'view' if table_type in VIEW_TABLE_TYPES else 'table',
        'name': table.name,
        'id': full_name,
        'full_name': full_name,
        'catalog': catalog,
        'schema': schema,
        'table_type': table_type,
        'owner': getattr(table, 'owner', None),
        'comment': getattr(table, 'comment', None),
        'created_at': getattr(table, 'created_at', None),
        'updated_at': getattr(table, 'updated_at', None),
        'storage_location': getattr(table, 'storage_location', None),
        **{k: v for k, v in table_column_fields(table).items() if k not in KEY_FIELDS},
    }


def enrich_tables(
    entities: List[Dict[str, Any]], groups: Set[str], runner: Optional[SqlRunner],
    table_reader: Optional['TableConstraintsReader'] = None,
) -> None:
    """``enrich_catalog_tables`` for table entities of any catalogs (one table or many).

    A caller evaluating a rule on them checks ``unavailable_fields_read`` first:
    a field it reads that is listed there is missing, not ``None``, and the rule
    is not evaluated rather than failed or passed.
    """
    by_catalog: Dict[str, List[Dict[str, Any]]] = {}
    for entity in entities:
        by_catalog.setdefault(str(entity.get('catalog') or ''), []).append(entity)
    for catalog, members in by_catalog.items():
        enrich_catalog_tables(catalog, members, groups, runner, table_reader)


# --- loading -------------------------------------------------------------------------

class TableConstraintsReader:
    """Reads the key column fields of tables with ``tables.get``.

    ``tables.list`` doesn't return ``table_constraints``. One reader serves one
    policy run: past ``max_reads`` calls or ``max_seconds`` since its first
    read, ``fields`` raises ``SourceUnavailable`` (``table_read_limit``)
    without a call. The time before that first read (the table listing, LLM
    checks) spends none of the budget.
    """

    def __init__(
        self, workspace_client: Any, max_reads: int = MAX_TABLE_READS_PER_RUN,
        max_seconds: float = MAX_TABLE_READ_SECONDS,
        clock: Callable[[], float] = time.monotonic,
    ):
        self.ws = workspace_client
        self.max_reads = max_reads
        self.max_seconds = max_seconds
        self.reads = 0
        self._clock = clock
        # Set at the first read, so the time before it spends none of the budget
        self._deadline: Optional[float] = None

    def _past_deadline(self) -> bool:
        """Whether the budget the first read started is spent (starting it there)."""
        now = self._clock()
        if self._deadline is None:
            self._deadline = now + self.max_seconds
        return now >= self._deadline

    def fields(self, full_name: str) -> Dict[str, Any]:
        """``KEY_FIELDS`` of the table; raises ``SourceUnavailable`` when it can't be read."""
        if self.reads >= self.max_reads or self._past_deadline():
            raise SourceUnavailable(REASON_TABLE_READ_LIMIT, 'run reached its table read limit')
        self.reads += 1
        try:
            table = self.ws.tables.get(full_name=full_name)
        except Exception as e:
            from databricks.sdk.errors import NotFound, PermissionDenied
            if isinstance(e, PermissionDenied):
                reason = REASON_TABLE_NO_ACCESS
            elif isinstance(e, NotFound):
                reason = REASON_TABLE_NOT_FOUND
            else:
                reason = REASON_TABLE_READ_FAILED
            raise SourceUnavailable(reason, type(e).__name__) from e
        return key_column_fields(table)


def enrich_key_columns(
    entities: List[Dict[str, Any]], reader: Optional[TableConstraintsReader],
) -> None:
    """Set the key column fields of each table entity from ``reader``, in place.

    A table whose constraints can't be read keeps none of them and is marked
    unavailable with the reason, so a rule on them isn't passed or failed on
    the empty lists a missing read would give.
    """
    if reader is None:
        mark_unavailable(entities, KEYS, REASON_TABLE_READ_FAILED)
        return
    failures: Dict[str, int] = {}
    for entity in entities:
        try:
            entity.update(reader.fields(str(entity.get('full_name') or '')))
        except SourceUnavailable as e:
            failures[e.reason] = failures.get(e.reason, 0) + 1
            mark_unavailable([entity], KEYS, e.reason)
    for reason, count in failures.items():
        logger.warning("Could not read the key columns of %d tables (%s)", count, reason)


def enrich_catalog_tables(
    catalog: str,
    entities: List[Dict[str, Any]],
    groups: Set[str],
    runner: Optional[SqlRunner],
    table_reader: Optional[TableConstraintsReader] = None,
) -> None:
    """Add the fields of ``groups`` to the table entities of one catalog, in place.

    One statement per SQL group (tags, lineage), scoped to the schemas of
    ``entities``; without a runner, or when a statement fails, the group's
    fields are left out and marked unavailable with the reason. The key
    columns (KEYS) are read per table with ``table_reader`` (see
    ``enrich_key_columns``).
    """
    if not entities or not groups:
        return
    if KEYS in groups:
        enrich_key_columns(entities, table_reader)
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
    """Runs statements on a SQL warehouse through the Statement Execution API.

    A statement still running after the first wait is not cancelled: it is
    polled until it ends or ``DEADLINE_SECONDS`` have passed since it was
    sent, and only then cancelled (reason ``timed_out``).
    """

    WAIT_TIMEOUT = '50s'
    DEADLINE_SECONDS = 300
    POLL_SECONDS = 5
    # A transient error (429, 503, a timeout) is retried after these waits
    RETRY_BACKOFF_SECONDS = (2, 8)

    def __init__(
        self, workspace_client: Any, warehouse_id: str, *,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
    ):
        self.ws = workspace_client
        self.warehouse_id = warehouse_id
        self._clock = clock
        self._sleep = sleep

    def rows(
        self, statement: str, parameters: Dict[str, str], deadline: Optional[float] = None,
    ) -> List[Dict[str, Any]]:
        """Rows of the statement; a transient error is retried with backoff, and
        is reported as ``transient`` when every attempt failed.

        ``deadline``: the run's (``clock`` time); a statement still running then
        is cancelled as at its own deadline, and no retry starts past it.
        """
        for wait in self.RETRY_BACKOFF_SECONDS:
            try:
                return self._rows_once(statement, parameters, deadline)
            except SourceUnavailable as e:
                if e.reason != REASON_TRANSIENT:
                    raise
                if deadline is not None and self._clock() + wait >= deadline:
                    raise SourceUnavailable(
                        REASON_TIMED_OUT, f"no time left in the run to retry: {e}",
                    ) from e
                logger.info("Transient error on the SQL warehouse, retrying in %ss: %s", wait, e)
                self._sleep(wait)
        return self._rows_once(statement, parameters, deadline)

    def _rows_once(
        self, statement: str, parameters: Dict[str, str], run_deadline: Optional[float] = None,
    ) -> List[Dict[str, Any]]:
        from databricks.sdk.service.sql import (
            ExecuteStatementRequestOnWaitTimeout, StatementParameterListItem,
        )

        try:
            deadline = self._clock() + self.DEADLINE_SECONDS
            if run_deadline is not None:
                deadline = min(deadline, run_deadline)
            response = self.ws.statement_execution.execute_statement(
                statement=statement,
                warehouse_id=self.warehouse_id,
                parameters=[
                    StatementParameterListItem(name=k, value=v) for k, v in parameters.items()
                ],
                wait_timeout=self.WAIT_TIMEOUT,
                on_wait_timeout=ExecuteStatementRequestOnWaitTimeout.CONTINUE,
            )
            response = self._wait(response, deadline)
            state = _state(response)
            if state != 'SUCCEEDED':
                error = getattr(response.status, 'error', None)
                code = getattr(getattr(error, 'error_code', None), 'value', None)
                raise SourceUnavailable(
                    _reason(getattr(error, 'message', '') or '', code),
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
            raise SourceUnavailable(_reason(str(e), error=e), str(e)) from e
        return [dict(zip(columns, row)) for row in data]

    def _wait(self, response: Any, deadline: float) -> Any:
        """Poll a statement still pending or running until it ends or the deadline.

        The statement is cancelled at the deadline and on any error while
        polling (a 503 from ``get_statement``), so a retry never leaves the
        first copy running on the warehouse.
        """
        statement_id = getattr(response, 'statement_id', None)
        try:
            while _state(response) in _RUNNING_STATES:
                if self._clock() >= deadline:
                    raise SourceUnavailable(
                        REASON_TIMED_OUT, "statement still running at the deadline",
                    )
                self._sleep(self.POLL_SECONDS)
                response = self.ws.statement_execution.get_statement(statement_id)
        except BaseException:
            self._cancel(statement_id)
            raise
        return response

    def _cancel(self, statement_id: Optional[str]) -> None:
        if not statement_id:
            return
        try:
            self.ws.statement_execution.cancel_execution(statement_id)
        except Exception:
            logger.warning("Could not cancel statement %s", statement_id)


_RUNNING_STATES = ('PENDING', 'RUNNING')


def _state(response: Any) -> Optional[str]:
    return getattr(getattr(getattr(response, 'status', None), 'state', None), 'value', None)


# Statement error codes and SQL error classes, by reason
_TRANSIENT_CODES = {
    'TEMPORARILY_UNAVAILABLE', 'WORKSPACE_TEMPORARILY_UNAVAILABLE', 'SERVICE_UNDER_MAINTENANCE',
    'RESOURCE_EXHAUSTED', 'DEADLINE_EXCEEDED', 'IO_ERROR',
}
_TRANSIENT_MARKERS = (
    'TEMPORARILY_UNAVAILABLE', 'TOO_MANY_REQUESTS', 'RESOURCE_EXHAUSTED', 'DEADLINE_EXCEEDED',
    'SERVICE_UNDER_MAINTENANCE', 'TIMED OUT', 'TIMEOUT',
)
_NOT_FOUND_MARKERS = ('TABLE_OR_VIEW_NOT_FOUND', 'SCHEMA_NOT_FOUND', 'CATALOG_NOT_FOUND')
_NO_ACCESS_MARKERS = ('PERMISSION', 'NOT AUTHORIZED', 'INSUFFICIENT')


def _reason(
    message: str, error_code: Optional[str] = None, error: Optional[BaseException] = None,
) -> str:
    """The REASON_* code of a failed statement or SDK call."""
    from databricks.sdk import errors as sdk_errors

    upper = message.upper()
    if isinstance(error, (sdk_errors.PermissionDenied, sdk_errors.Unauthenticated)) or any(
        m in upper for m in _NO_ACCESS_MARKERS
    ):
        return REASON_NO_ACCESS
    # The system schema not enabled, or a system table not there
    if (isinstance(error, sdk_errors.NotFound) or error_code == 'NOT_FOUND'
            or any(m in upper for m in _NOT_FOUND_MARKERS)):
        return REASON_NOT_FOUND
    if (isinstance(error, (
            sdk_errors.TooManyRequests, sdk_errors.TemporarilyUnavailable,
            sdk_errors.DeadlineExceeded, ConnectionError, TimeoutError,
    )) or _is_network_error(error) or error_code in _TRANSIENT_CODES
            or any(m in upper for m in _TRANSIENT_MARKERS)):
        return REASON_TRANSIENT
    return REASON_QUERY_FAILED


def _is_network_error(error: Optional[BaseException]) -> bool:
    try:
        from requests.exceptions import ConnectionError as RequestsConnectionError, Timeout
    except ImportError:  # pragma: no cover - requests comes with the SDK
        return False
    return isinstance(error, (RequestsConnectionError, Timeout))
