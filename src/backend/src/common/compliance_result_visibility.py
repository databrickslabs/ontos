"""Which stored compliance results a viewer may see.

A run stores a result per entity it evaluated, with the entity's name and the
reason it passed or failed. A user-started run reads Unity Catalog as that
user, and a scheduled run as the app, so the stored results can name Unity
Catalog objects the viewer has no grant on. The result routes keep only the
results the viewer can read, checked at read time with the viewer's own token:

- a table or view: listed by ``tables.list`` of its schema;
- a schema: listed by ``schemas.list`` of its catalog;
- a catalog: listed by ``catalogs.list``;
- a function or volume: listed by ``functions.list`` / ``volumes.list`` of its schema.

Each listing is made once per request (``tables.list`` once per schema, not per
table), and a listing that fails, or a viewer without a token, hides that part:
the check fails closed. Results on app entities (data products, contracts,
domains...) are not filtered here; compliance read access already covers them,
as the policy and run pages do.
"""

from typing import Any, Callable, Dict, Iterable, List, Optional, Set, Tuple, TypeVar

from src.common.logging import get_logger

logger = get_logger(__name__)

UC_RESULT_TYPES = ('catalog', 'schema', 'table', 'view', 'function', 'volume')

T = TypeVar('T')


class ViewerReadChecks:
    """Whether the viewer can read the Unity Catalog object of a stored result.

    ``client_factory`` gives the viewer's workspace client (see
    ``viewer_read_checks``); it is called once, on the first UC result.
    """

    def __init__(self, client_factory: Callable[[], Any]):
        self._factory = client_factory
        self._client: Any = None
        self._client_failed = False
        self._listed: Dict[Tuple[str, ...], Set[str]] = {}

    def _ws(self) -> Any:
        if self._client is None and not self._client_failed:
            try:
                self._client = self._factory()
            except Exception as e:
                # No token, or no client: no UC result is shown (fails closed)
                logger.info("Viewer's workspace client unavailable; hiding UC results: %s", e)
                self._client_failed = True
        return self._client

    def _names(self, key: Tuple[str, ...], list_names: Callable[[Any], Iterable[Any]]) -> Set[str]:
        """Lowercased names of one listing, made once per instance."""
        if key not in self._listed:
            names: Set[str] = set()
            ws = self._ws()
            if ws is not None:
                try:
                    names = {str(getattr(o, 'name', '') or '').lower() for o in list_names(ws)}
                except Exception as e:
                    logger.info("Viewer can't list %s; hiding its results: %s", '.'.join(key), e)
            self._listed[key] = names
        return self._listed[key]

    def can_read(self, object_type: Optional[str], object_id: Optional[str]) -> bool:
        """True for a result the viewer may see (always for non-UC types)."""
        if object_type not in UC_RESULT_TYPES:
            return True
        parts = str(object_id or '').split('.')
        if object_type == 'catalog':
            return len(parts) == 1 and parts[0].lower() in self._names(
                ('catalogs',), lambda ws: ws.catalogs.list(),
            )
        if object_type == 'schema':
            if len(parts) != 2:
                return False
            catalog, schema = parts
            return schema.lower() in self._names(
                ('schemas', catalog.lower()), lambda ws: ws.schemas.list(catalog_name=catalog),
            )
        if len(parts) != 3:
            return False
        catalog, schema, name = parts
        if object_type in ('table', 'view'):
            key, lister = 'tables', (lambda ws: ws.tables.list(
                catalog_name=catalog, schema_name=schema))
        elif object_type == 'function':
            key, lister = 'functions', (lambda ws: ws.functions.list(
                catalog_name=catalog, schema_name=schema))
        else:
            key, lister = 'volumes', (lambda ws: ws.volumes.list(
                catalog_name=catalog, schema_name=schema))
        return name.lower() in self._names((key, catalog.lower(), schema.lower()), lister)


def visible_results(
    results: List[T], checks: ViewerReadChecks,
    key: Callable[[T], Tuple[Optional[str], Optional[str]]] = (
        lambda r: (getattr(r, 'object_type', None), getattr(r, 'object_id', None))
    ),
) -> Tuple[List[T], int]:
    """The results the viewer can read, and how many were left out."""
    shown = [r for r in results if checks.can_read(*key(r))]
    return shown, len(results) - len(shown)


# A stored result as ``ComplianceResultRepository.typed_result_rows`` reads it:
# (run_id, object_type, object_id, passed, not_evaluated)
ResultRow = Tuple[str, str, str, bool, bool]


def result_outcome(passed: bool, not_evaluated: bool) -> str:
    """'passed', 'failed' or 'not_evaluated' (stored as not passed, not a failure)."""
    if passed:
        return 'passed'
    return 'not_evaluated' if not_evaluated else 'failed'


def hidden_result_tallies(
    rows: Iterable[ResultRow], checks: ViewerReadChecks,
) -> Dict[str, Dict[str, int]]:
    """Per run id, the results the viewer can't read, by outcome (``result_outcome``).
    Runs without a hidden result are left out."""
    tallies: Dict[str, Dict[str, int]] = {}
    for run_id, object_type, object_id, passed, not_evaluated in rows:
        if checks.can_read(object_type, object_id):
            continue
        per_run = tallies.setdefault(run_id, {'passed': 0, 'failed': 0, 'not_evaluated': 0})
        per_run[result_outcome(passed, not_evaluated)] += 1
    return tallies


def viewer_read_checks(request: Any) -> ViewerReadChecks:
    """Read checks with the requesting user's own token (``RunIdentity.for_request``)."""
    from src.common.run_identity import RunIdentity

    return ViewerReadChecks(RunIdentity.for_request(request).workspace_client)
