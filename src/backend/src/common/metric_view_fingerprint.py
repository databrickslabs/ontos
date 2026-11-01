"""Fingerprints, data footprint and similarity of metric view measures (#1263).

Every measure of a parsed metric view spec (``parse_metric_view_definition``)
gets a three-level fingerprint, built from normalized components:

========== ================================================================
Level      Content
========== ================================================================
expression ``expr``, references to other fields inlined
scope      expression + effective source + view ``filter`` + the joins the
           measure uses (with ``cardinality``)
full       scope + ``window`` + the ``parameters`` the measure uses
========== ================================================================

Normalization is textual, aligned with the Databricks metric-view advisor:

- identifiers and keywords are lower-cased (string literals are values and
  keep their case), whitespace doesn't count, and the ``source.`` prefix is
  stripped;
- a join alias (``customers.region``) is resolved to the join's source
  (``main.crm.customers.region``);
- ``MEASURE(name)`` and a bare reference to another dimension or measure are
  inlined, at most ``MAX_REFERENCE_DEPTH`` levels deep; a cycle is refused
  (the measure gets ``error = 'reference_cycle'`` and no fingerprint). Inside
  a field's own expression its own name is a source column, not a reference;
- the view ``filter`` is split on top-level ``AND`` into a set of predicates;
- a window ``range`` is parsed into (kind, value, unit, inclusive), so
  ``trailing 30 day`` equals ``trailing 30 days exclusive``.

``display_name``, ``format`` and the comments are not part of a fingerprint,
as in the drift digest (``metric_view_normalization``), whose rules this
module doesn't change.

The data footprint is the set of source columns a measure reads
(``catalog.schema.table.column``), through its expression, the effective
source (an FQN, or the tables a source query reads), the view filter and
the joins it uses, plus its aggregation functions. Measures are compared
approximately (``similarity``) only when their footprints overlap.

Pure functions, no database.
"""
import re
from typing import Any, Dict, Iterable, List, Optional, Sequence, Set, Tuple

from src.common.metric_view_normalization import canonical_json, definition_digest

# Bump when a rule changes: stored fingerprints of another version are recomputed
FINGERPRINT_VERSION = 1
MAX_REFERENCE_DEPTH = 10
# Default similarity at or above which two overlapping measures are near duplicates
DEFAULT_SIMILARITY_THRESHOLD = 0.75

LEVELS = ('expression', 'scope', 'full')

# Weight of each component in the similarity score (sum 1)
SIMILARITY_WEIGHTS: Dict[str, float] = {
    'aggregation': 0.2,
    'columns': 0.35,
    'source': 0.15,
    'filter': 0.1,
    'window': 0.1,
    'joins': 0.05,
    'parameters': 0.05,
}

AGGREGATE_FUNCTIONS = frozenset({
    'sum', 'count', 'avg', 'mean', 'min', 'max', 'median', 'mode', 'any_value',
    'approx_count_distinct', 'count_if', 'sum_distinct', 'collect_list', 'collect_set',
    'stddev', 'stddev_pop', 'stddev_samp', 'variance', 'var_pop', 'var_samp',
    'percentile', 'percentile_approx', 'approx_percentile', 'first', 'last',
    'first_value', 'last_value', 'bool_and', 'bool_or', 'every', 'some',
    'max_by', 'min_by', 'corr', 'covar_pop', 'covar_samp', 'kurtosis', 'skewness',
})

# Words that are never a column reference
_KEYWORDS = frozenset({
    'all', 'and', 'any', 'as', 'asc', 'between', 'both', 'by', 'case', 'cast', 'cross',
    'current_date', 'current_timestamp', 'day', 'days', 'desc', 'distinct', 'div', 'else',
    'end', 'escape', 'exists', 'false', 'filter', 'following', 'from', 'full', 'group',
    'having', 'hour', 'hours', 'ilike', 'in', 'inner', 'interval', 'is', 'join', 'last',
    'leading', 'left', 'like', 'limit', 'minute', 'minutes', 'month', 'months', 'not',
    'null', 'nulls', 'on', 'or', 'order', 'outer', 'over', 'partition', 'preceding',
    'quarter', 'range', 'rlike', 'right', 'rows', 'second', 'seconds', 'select', 'then',
    'trailing', 'true', 'unbounded', 'union', 'using', 'week', 'weeks', 'when', 'where',
    'with', 'within', 'year', 'years', 'first', 'semi', 'anti', 'lateral', 'regexp',
    # Type names (after AS in a CAST, or in a typed literal)
    'bigint', 'binary', 'boolean', 'byte', 'char', 'date', 'decimal', 'double', 'float',
    'int', 'integer', 'long', 'numeric', 'short', 'smallint', 'string', 'timestamp',
    'timestamp_ntz', 'tinyint', 'varchar', 'array', 'map', 'struct',
})

_TOKEN = re.compile(
    r"(?P<str>'(?:[^'\\]|\\.|'')*'|\"(?:[^\"\\]|\\.)*\")"
    r"|(?P<bt>`(?:[^`]|``)*`)"
    r"|(?P<param>:[A-Za-z_]\w*)"
    r"|(?P<ident>[A-Za-z_]\w*)"
    r"|(?P<num>\d+(?:\.\d+)?(?:[eE][+-]?\d+)?[a-zA-Z]*)"
    r"|(?P<ws>\s+)"
    r"|(?P<op>.)",
    re.S,
)
_SIMPLE_IDENT = re.compile(r'^[a-z_][a-z0-9_]*$')

# A token: (kind, text); identifiers are kept as kind 'ident' with their name
# lower-cased and unquoted (a backticked name is one identifier).
Token = Tuple[str, str]


class MeasureReferenceError(ValueError):
    """A measure's references can't be inlined (a cycle, or nested too deeply)."""

    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


def tokenize(text: Optional[str]) -> List[Token]:
    """``text`` as tokens: identifiers lower-cased and unquoted, whitespace dropped."""
    tokens: List[Token] = []
    for match in _TOKEN.finditer(text or ''):
        kind = match.lastgroup
        value = match.group()
        if kind == 'ws':
            continue
        if kind == 'bt':
            tokens.append(('ident', value[1:-1].replace('``', '`').lower()))
        elif kind == 'ident':
            tokens.append(('ident', value.lower()))
        elif kind in ('param', 'num'):
            tokens.append((kind, value.lower()))
        else:
            tokens.append((kind, value))
    return tokens


def _render_ident(name: str) -> str:
    return name if _SIMPLE_IDENT.match(name) else '`' + name.replace('`', '``') + '`'


def render(tokens: Sequence[Token]) -> str:
    """Tokens as text: a space only between two word-like tokens."""
    out: List[str] = []
    previous_word = False
    for kind, value in tokens:
        word = kind != 'op'
        text = _render_ident(value) if kind == 'ident' else value
        if out and word and previous_word:
            out.append(' ')
        out.append(text)
        previous_word = word
    return ''.join(out)


def _is_dot(tokens: Sequence[Token], i: int) -> bool:
    return 0 <= i < len(tokens) and tokens[i] == ('op', '.')


def _is_open(tokens: Sequence[Token], i: int) -> bool:
    return 0 <= i < len(tokens) and tokens[i] == ('op', '(')


def source_fqn(source: Any) -> Optional[str]:
    """The source as a lower-case ``catalog.schema.table`` when it's a name, else None."""
    if not isinstance(source, str) or not source.strip():
        return None
    tokens = tokenize(source)
    if not tokens or len(tokens) % 2 == 0:
        return None
    for i, (kind, value) in enumerate(tokens):
        if i % 2 == 0 and kind != 'ident':
            return None
        if i % 2 == 1 and (kind, value) != ('op', '.'):
            return None
    return '.'.join(value for kind, value in tokens if kind == 'ident')


def query_tables(tokens: Sequence[Token]) -> List[str]:
    """The tables a source query reads: the names after ``FROM`` and ``JOIN``."""
    tables: List[str] = []
    i = 0
    while i < len(tokens):
        if tokens[i][0] == 'ident' and tokens[i][1] in ('from', 'join') and i + 1 < len(tokens):
            j = i + 1
            if tokens[j][0] != 'ident' or tokens[j][1] == 'select':
                i += 1
                continue
            parts = [tokens[j][1]]
            while _is_dot(tokens, j + 1) and j + 2 < len(tokens) and tokens[j + 2][0] == 'ident':
                parts.append(tokens[j + 2][1])
                j += 2
            name = '.'.join(parts)
            if name not in tables:
                tables.append(name)
            i = j
        i += 1
    return sorted(tables)


def _strip_source_prefix(tokens: List[Token]) -> List[Token]:
    """Without the ``source.`` qualifier (the metric view's own source)."""
    out: List[Token] = []
    i = 0
    while i < len(tokens):
        if (tokens[i] == ('ident', 'source') and _is_dot(tokens, i + 1)
                and not _is_dot(tokens, i - 1)):
            i += 2
            continue
        out.append(tokens[i])
        i += 1
    return out


def _referenced_aliases(tokens: Sequence[Token], aliases: Iterable[str]) -> Set[str]:
    """The join aliases used as a qualifier (``alias.column``) in ``tokens``."""
    names = set(aliases)
    return {
        value for i, (kind, value) in enumerate(tokens)
        if kind == 'ident' and value in names and _is_dot(tokens, i + 1)
        and not _is_dot(tokens, i - 1)
    }


def _resolve_aliases(tokens: List[Token], alias_sources: Dict[str, str]) -> List[Token]:
    """``alias.column`` with ``alias`` replaced by the join's source name."""
    out: List[Token] = []
    for i, (kind, value) in enumerate(tokens):
        if (kind == 'ident' and value in alias_sources and _is_dot(tokens, i + 1)
                and not _is_dot(tokens, i - 1)):
            parts = alias_sources[value].split('.')
            for n, part in enumerate(parts):
                if n:
                    out.append(('op', '.'))
                out.append(('ident', part))
            continue
        out.append((kind, value))
    return out


class _Inliner:
    """Inlines references to other dimensions and measures in an expression."""

    def __init__(self, spec: Dict[str, Any]):
        self._fields: Dict[str, Tuple[str, Any]] = {}
        self._measures: Dict[str, Any] = {}
        for kind in ('dimensions', 'measures'):
            for field in spec.get(kind) or []:
                name = str(field.get('name') or '').lower()
                if not name:
                    continue
                self._fields.setdefault(name, (kind, field.get('expr')))
                if kind == 'measures':
                    self._measures.setdefault(name, field.get('expr'))

    def inline(self, name: str, expr: Any, stack: Tuple[str, ...] = ()) -> List[Token]:
        """The tokens of ``expr`` (the expression of field ``name``), references inlined.

        Raises ``MeasureReferenceError('reference_cycle')`` on a cycle and
        ``MeasureReferenceError('reference_depth')`` past ``MAX_REFERENCE_DEPTH``.
        """
        if name in stack:
            raise MeasureReferenceError('reference_cycle')
        if len(stack) >= MAX_REFERENCE_DEPTH:
            raise MeasureReferenceError('reference_depth')
        stack = stack + (name,)
        tokens = tokenize(expr if isinstance(expr, str) else '')
        out: List[Token] = []
        i = 0
        while i < len(tokens):
            kind, value = tokens[i]
            # MEASURE(other)
            if (kind == 'ident' and value == 'measure' and _is_open(tokens, i + 1)
                    and i + 3 < len(tokens) and tokens[i + 2][0] == 'ident'
                    and tokens[i + 3] == ('op', ')')
                    and tokens[i + 2][1] in self._measures):
                other = tokens[i + 2][1]
                out.extend(self._wrapped(other, self._measures[other], stack))
                i += 4
                continue
            is_reference = (
                kind == 'ident' and value != name and value in self._fields
                and not _is_dot(tokens, i - 1) and not _is_dot(tokens, i + 1)
                and not _is_open(tokens, i + 1)
            )
            if is_reference:
                out.extend(self._wrapped(value, self._fields[value][1], stack))
            else:
                out.append((kind, value))
            i += 1
        return out

    def _wrapped(self, name: str, expr: Any, stack: Tuple[str, ...]) -> List[Token]:
        return [('op', '(')] + self.inline(name, expr, stack) + [('op', ')')]

    def dimension_expr(self, name: str) -> Optional[Any]:
        field = self._fields.get(name)
        return field[1] if field and field[0] == 'dimensions' else None


def _split_and(tokens: Sequence[Token]) -> List[List[Token]]:
    """``tokens`` split on top-level ``AND`` (outside parentheses)."""
    parts: List[List[Token]] = [[]]
    depth = 0
    between = False
    for kind, value in tokens:
        if (kind, value) == ('op', '('):
            depth += 1
        elif (kind, value) == ('op', ')'):
            depth -= 1
        if kind == 'ident' and value == 'between' and depth == 0:
            between = True
        elif kind == 'ident' and value == 'and' and depth == 0:
            if between:
                between = False  # the AND of BETWEEN x AND y
            else:
                parts.append([])
                continue
        parts[-1].append((kind, value))
    return [p for p in parts if p]


def _strip_outer_parens(tokens: List[Token]) -> List[Token]:
    while len(tokens) >= 2 and tokens[0] == ('op', '(') and tokens[-1] == ('op', ')'):
        depth = 0
        for i, (kind, value) in enumerate(tokens):
            if (kind, value) == ('op', '('):
                depth += 1
            elif (kind, value) == ('op', ')'):
                depth -= 1
            if depth == 0 and i < len(tokens) - 1:
                return tokens
        tokens = tokens[1:-1]
    return tokens


_RANGE = re.compile(
    r'^(?P<kind>trailing|leading)\s+(?P<value>\d+)\s+(?P<unit>[a-z]+?)s?'
    r'(?:\s+(?P<incl>inclusive|exclusive))?$'
)
_RANGE_SIMPLE = re.compile(
    r'^(?P<kind>current|cumulative|all)(?:\s+(?P<incl>inclusive|exclusive))?$'
)


def parse_window_range(text: Any) -> Dict[str, Any]:
    """A window ``range`` as ``{kind, value, unit, inclusive}``.

    ``trailing 30 day``, ``trailing 30 days`` and ``trailing 30 day exclusive``
    are equal: exclusive is the default, units are singular. A range in no
    known form is ``{kind: 'raw', value: <normalized text>}``.
    """
    normalized = ' '.join(str(text or '').lower().split())
    match = _RANGE.match(normalized)
    if match:
        return {
            'kind': match.group('kind'), 'value': int(match.group('value')),
            'unit': match.group('unit'), 'inclusive': match.group('incl') == 'inclusive',
        }
    match = _RANGE_SIMPLE.match(normalized)
    if match:
        return {'kind': match.group('kind'), 'value': None, 'unit': None,
                'inclusive': match.group('incl') == 'inclusive'}
    return {'kind': 'raw', 'value': normalized, 'unit': None, 'inclusive': False}


def _parameters_used(tokens: Iterable[Token]) -> Set[str]:
    return {value[1:] for kind, value in tokens if kind == 'param'}


def _columns(
    tokens: Sequence[Token], base_tables: Sequence[str], join_sources: Iterable[str],
) -> Set[str]:
    """The source columns ``tokens`` read, as ``table.column``.

    A bare name is a column of the base source (of each table a source query
    reads); a name qualified by a join's source is a column of that table.
    Function names, keywords and parameters aren't columns.
    """
    joined = sorted(set(join_sources), key=len, reverse=True)
    columns: Set[str] = set()
    i = 0
    while i < len(tokens):
        kind, value = tokens[i]
        if kind != 'ident' or _is_dot(tokens, i - 1):
            i += 1
            continue
        parts = [value]
        j = i
        while _is_dot(tokens, j + 1) and j + 2 < len(tokens) and tokens[j + 2][0] == 'ident':
            parts.append(tokens[j + 2][1])
            j += 2
        after_as = i > 0 and tokens[i - 1] == ('ident', 'as')
        if _is_open(tokens, j + 1) or after_as or (len(parts) == 1 and value in _KEYWORDS):
            i = j + 1
            continue
        chain = '.'.join(parts)
        owner = next((s for s in joined if chain.startswith(s + '.')), None)
        if owner is not None:
            columns.add(owner + '.' + chain[len(owner) + 1:].split('.')[0])
        else:
            for table in base_tables or ('source',):
                columns.add(f'{table}.{parts[0]}')
        i = j + 1
    return columns


def _aggregations(tokens: Sequence[Token]) -> List[str]:
    found: Set[str] = set()
    for i, (kind, value) in enumerate(tokens):
        if kind == 'ident' and value in AGGREGATE_FUNCTIONS and _is_open(tokens, i + 1):
            distinct = i + 2 < len(tokens) and tokens[i + 2] == ('ident', 'distinct')
            found.add(f'{value}_distinct' if distinct else value)
    return sorted(found)


def _join_entries(spec: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    """The joins by lower-case name (a join without a name can't be referenced)."""
    joins: Dict[str, Dict[str, Any]] = {}
    for join in spec.get('joins') or []:
        name = str(join.get('name') or '').lower()
        if name and name not in joins:
            joins[name] = join
    return joins


def _join_source(join: Dict[str, Any]) -> str:
    fqn = source_fqn(join.get('source'))
    return fqn if fqn is not None else render(tokenize(join.get('source')))


def measure_fingerprint(
    spec: Dict[str, Any], measure: Dict[str, Any], inliner: Optional[_Inliner] = None,
) -> Dict[str, Any]:
    """The fingerprint record of one measure of a parsed spec.

    ``{name, display_name, synonyms, error, digests: {expression, scope, full},
    components: {expression, source, filter, joins, window, parameters},
    footprint: {source_tables, tables, columns, base_columns, aggregations}}``; ``digests``,
    ``components`` and ``footprint`` are None when ``error`` is set
    (``reference_cycle``, ``reference_depth`` or ``no_expression``).
    """
    inliner = inliner or _Inliner(spec)
    name = str(measure.get('name') or '')
    record: Dict[str, Any] = {
        'name': name,
        'display_name': measure.get('display_name'),
        'synonyms': [str(s) for s in measure.get('synonyms') or [] if s is not None],
        'error': None, 'digests': None, 'components': None, 'footprint': None,
    }
    if not isinstance(measure.get('expr'), str) or not measure['expr'].strip():
        record['error'] = 'no_expression'
        return record
    try:
        expr_tokens = inliner.inline(name.lower(), measure['expr'])
        window_orders = [
            inliner.inline(str(w.get('order') or '').lower(), inliner.dimension_expr(
                str(w.get('order') or '').lower()) or w.get('order'))
            for w in measure.get('window') or []
        ]
    except MeasureReferenceError as e:
        record['error'] = e.code
        return record
    expr_tokens = _strip_source_prefix(expr_tokens)
    filter_tokens = _strip_source_prefix(tokenize(spec.get('filter')))

    # The effective source: a name, or a query and the tables it reads
    base_fqn = source_fqn(spec.get('source'))
    source_tokens = tokenize(spec.get('source'))
    base_tables = [base_fqn] if base_fqn else query_tables(source_tokens)
    source_text = base_fqn if base_fqn else render(source_tokens)

    # The joins the expression and the filter use, and the joins those joins' ON use
    joins = _join_entries(spec)
    used = _referenced_aliases(expr_tokens + filter_tokens, joins)
    pending = list(used)
    while pending:
        on_tokens = tokenize(joins[pending.pop()].get('on'))
        for alias in _referenced_aliases(on_tokens, joins) - used:
            used.add(alias)
            pending.append(alias)
    alias_sources = {alias: _join_source(joins[alias]) for alias in used}
    # Aliases of joins on a table are replaced by its name; a join on a query keeps its alias
    alias_tables = {
        alias: fqn for alias in used
        if (fqn := source_fqn(joins[alias].get('source'))) is not None
    }
    owners = set(alias_tables.values()) | (used - set(alias_tables))

    def resolve(tokens: List[Token]) -> List[Token]:
        return _resolve_aliases(_strip_source_prefix(tokens), alias_tables)

    expr_resolved = resolve(expr_tokens)
    filter_resolved = resolve(filter_tokens)
    predicates = sorted({render(_strip_outer_parens(p)) for p in _split_and(filter_resolved)})
    join_components = sorted((
        {
            'source': alias_sources[alias],
            'on': render(resolve(tokenize(joins[alias].get('on')))) or None,
            'using': sorted(str(c).lower() for c in joins[alias].get('using') or []) or None,
            'cardinality': str(joins[alias]['cardinality']).lower()
            if joins[alias].get('cardinality') else None,
        } for alias in used
    ), key=canonical_json)

    windows = []
    for entry, order_tokens in zip(measure.get('window') or [], window_orders):
        windows.append({
            'order': render(resolve(order_tokens)) or None,
            'range': parse_window_range(entry.get('range')),
            'semiadditive': str(entry['semiadditive']).lower()
            if entry.get('semiadditive') else None,
            'offset': render(tokenize(str(entry['offset']))) if entry.get('offset') else None,
        })

    used_params = _parameters_used(expr_tokens + filter_tokens + source_tokens)
    for alias in used:
        used_params |= _parameters_used(tokenize(joins[alias].get('on')))
    parameters = sorted((
        {'name': str(p.get('name')).lower(),
         'data_type': str(p['data_type']).lower() if p.get('data_type') else None,
         'default': p.get('default')}
        for p in spec.get('parameters') or [] if str(p.get('name') or '').lower() in used_params
    ), key=canonical_json)

    components = {
        'expression': render(expr_resolved),
        'source': source_text,
        'filter': predicates,
        'joins': join_components,
        'window': windows,
        'parameters': parameters,
    }
    expression_level = {'expression': components['expression']}
    scope_level = dict(expression_level, source=source_text, filter=predicates,
                       joins=join_components)
    full_level = dict(scope_level, window=windows, parameters=parameters)
    record['digests'] = {
        'expression': definition_digest(expression_level),
        'scope': definition_digest(scope_level),
        'full': definition_digest(full_level),
    }
    record['components'] = components

    on_tokens = [t for alias in used for t in resolve(tokenize(joins[alias].get('on')))]
    base_columns = _columns(expr_resolved, base_tables, owners)
    all_columns = (base_columns | _columns(filter_resolved, base_tables, owners)
                   | _columns(on_tokens, base_tables, owners))
    record['footprint'] = {
        'source_tables': sorted(base_tables),
        'tables': sorted(set(base_tables) | set(alias_tables.values())),
        'columns': sorted(all_columns),
        'base_columns': sorted(base_columns),
        'aggregations': _aggregations(expr_resolved),
    }
    return record


def fingerprint_metric_view(spec: Optional[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """The fingerprint record of every measure of a parsed spec, in definition order."""
    if not spec:
        return []
    inliner = _Inliner(spec)
    return [measure_fingerprint(spec, m, inliner) for m in spec.get('measures') or []
            if isinstance(m, dict) and m.get('name')]


def footprints_overlap(a: Dict[str, Any], b: Dict[str, Any]) -> bool:
    """Whether two measures read some of the same data (and so are worth comparing).

    Columns in common, or, when one reads no column (``COUNT(*)``), a table in common.
    """
    fa, fb = a.get('footprint'), b.get('footprint')
    if not fa or not fb:
        return False
    if set(fa['columns']) & set(fb['columns']):
        return True
    if not fa['columns'] or not fb['columns']:
        return bool(set(fa['tables']) & set(fb['tables']))
    return False


def _component_sets(record: Dict[str, Any]) -> Dict[str, Set[str]]:
    c, f = record['components'], record['footprint']
    return {
        'aggregation': set(f['aggregations']),
        'columns': set(f['base_columns']),
        'source': set(f['source_tables']) or {c['source']},
        'filter': set(c['filter']),
        'window': {canonical_json(w) for w in c['window']},
        'joins': {canonical_json(j) for j in c['joins']},
        'parameters': {canonical_json(p) for p in c['parameters']},
    }


def similarity(a: Dict[str, Any], b: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """A 0..1 score of how alike two measures are, and the components that differ.

    Each component (aggregation, base columns, source, filter predicates,
    window, joins, parameters) is compared as a set of normalized tokens
    (Jaccard; two empty sets are equal) and weighted by ``SIMILARITY_WEIGHTS``.
    ``differences`` lists, per differing component, what only ``a`` and only
    ``b`` have. None when either measure has no fingerprint.
    """
    if not a.get('components') or not b.get('components'):
        return None
    sa, sb = _component_sets(a), _component_sets(b)
    score = 0.0
    differences = []
    for component, weight in SIMILARITY_WEIGHTS.items():
        x, y = sa[component], sb[component]
        union = x | y
        score += weight * (len(x & y) / len(union) if union else 1.0)
        if x != y:
            differences.append({
                'component': component,
                'only_a': sorted(x - y),
                'only_b': sorted(y - x),
            })
    return {'score': round(score, 3), 'differences': differences}


def first_differing_level(a: Dict[str, Any], b: Dict[str, Any]) -> Optional[str]:
    """The first fingerprint level at which two measures differ, or None when equal."""
    for level in LEVELS:
        if a['digests'][level] != b['digests'][level]:
            return level
    return None


def _only_filter_window_parameters(a: Dict[str, Any], b: Dict[str, Any]) -> bool:
    """Same expression, source and joins: only filter, window or parameters differ."""
    ca, cb = a['components'], b['components']
    return (a['digests']['expression'] == b['digests']['expression']
            and ca['source'] == cb['source']
            and canonical_json(ca['joins']) == canonical_json(cb['joins']))


def classify(
    a: Dict[str, Any], b: Dict[str, Any], *, same_concept: bool, same_name: bool,
    a_linked: bool, b_linked: bool, threshold: float = DEFAULT_SIMILARITY_THRESHOLD,
) -> Optional[Dict[str, Any]]:
    """The verdict on a pair of measures, or None when there's nothing to report.

    ``{verdict, first_level, score, differences}`` with ``verdict`` one of
    ``duplicate``, ``link_conflict``, ``unrecognized_duplicate``, ``variant``,
    ``conflict`` and ``near_duplicate`` (the PRD's classification table).
    ``same_concept``: the two share a linked concept; ``same_name``: equal
    normalized name, display name or synonym; ``*_linked``: linked to any concept.
    """
    if not a.get('digests') or not b.get('digests'):
        return None
    sim = similarity(a, b) or {'score': None, 'differences': []}
    level = first_differing_level(a, b)
    result = {'first_level': level, 'score': sim['score'], 'differences': sim['differences']}
    claimed = same_concept or same_name
    if level is None:
        if claimed:
            return dict(result, verdict='duplicate')
        if a_linked and b_linked:
            return dict(result, verdict='link_conflict')
        return dict(result, verdict='unrecognized_duplicate')
    if _only_filter_window_parameters(a, b):
        return dict(result, verdict='variant')
    if claimed:
        return dict(result, verdict='conflict')
    if footprints_overlap(a, b) and sim['score'] is not None and sim['score'] >= threshold:
        return dict(result, verdict='near_duplicate')
    return None
