"""The lifecycle service: one place that knows the stages and transitions of entities.

Data products, data contracts and assets each belong to a Lifecycle Stage Group
(``lifecycle_stage_group_id``; NULL = the entity type's default group) and store
the key of their stage in ``status``. This service answers, for any of them and
for the MCP / chat tools:

- which stages an entity may move to (``allowed_targets``, ``check_transition``);
- which stage a named action (submit-review, approve, publish, deprecate, ...)
  moves it to (``resolve_action``): the action's seeded stage when the group has
  it, otherwise the only allowed stage of the action's Stage Category; none or
  several answer 409 (``invalid_status_transition`` /
  ``lifecycle_action_ambiguous``);
- the Stage Category of a stage (``category_of``, ``category_of_row``), which
  version visibility, the Marketplace and the standards export branch on;
- the stage and group a new or imported entity starts in, and a group change.

The database is the source of truth. While no group is stored for an entity
type (a database ``create_all()`` made before the startup seed ran, or the
in-memory test database), the seeded definitions in ``lifecycle_defaults`` are
used. Groups are cached per process: loaded at startup and after a save or
delete, and reloaded by the next call with a session once ``_CACHE_SECONDS``
passed (a change made by another worker).
"""
import threading
import time
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Iterable, List, Optional, Tuple

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, object_session

from src.common.api_errors import CodedValueError, InvalidStatusTransitionError
from src.common.lifecycle_defaults import (
    ACTIVE, DEFAULT_GROUP_IDS, DEFAULT_STAGE_CATEGORIES, LIFECYCLE_ENTITY_TYPES, STAGE_CATEGORIES,
    RETIRED, STANDARD_STATUS_BY_CATEGORY, default_group_definition,
)
from src.common.logging import get_logger

logger = get_logger(__name__)

_CACHE_SECONDS = 30.0

ONTOS_LIFECYCLE_STAGE_PROPERTY = 'ontosLifecycleStage'
ONTOS_LIFECYCLE_STAGE_GROUP_PROPERTY = 'ontosLifecycleStageGroup'
ONTOS_LIFECYCLE_STAGE_GROUP_ID_PROPERTY = 'ontosLifecycleStageGroupId'
LIFECYCLE_PROPERTIES = (
    ONTOS_LIFECYCLE_STAGE_PROPERTY, ONTOS_LIFECYCLE_STAGE_GROUP_PROPERTY,
    ONTOS_LIFECYCLE_STAGE_GROUP_ID_PROPERTY,
)

# Named actions: (seeded stage key, Stage Categories of the target, tried in order).
# A group with the seeded stage uses it; one without it, the categories.
NAMED_ACTIONS: Dict[str, Tuple[str, Tuple[str, ...]]] = {
    'move_to_sandbox': ('sandbox', ('draft',)),
    'submit_review': ('proposed', ('review',)),
    'start_review': ('under_review', ('review',)),
    # Approving a review: the next review step, else straight to active
    'approve': ('approved', ('review', 'active')),
    'reject': ('draft', ('draft',)),
    'publish': ('active', ('active',)),
    'deprecate': ('deprecated', ('deprecated',)),
    'retire': ('retired', ('retired',)),
}

_STAGE_KEY_CHARS = set('abcdefghijklmnopqrstuvwxyz0123456789_')

# Categories that decide what consumers, the Marketplace and search see: a stage
# with entities in it can't change into or out of them
_VISIBILITY_CATEGORIES = frozenset({'active', 'deprecated', 'retired'})


# --------------------------------------------------------------------------- errors

class LifecycleActionUnresolvedError(CodedValueError):
    """A named action with several allowed target stages in its category (HTTP 409).

    One with none raises ``InvalidStatusTransitionError`` (also 409 on the
    named action routes)."""

    code = 'lifecycle_action_ambiguous'


class LifecycleGroupNotFoundError(CodedValueError):
    code = 'lifecycle_group_not_found'


class LifecycleGroupInvalidError(CodedValueError):
    """A group that can't be saved; ``code`` says why."""

    def __init__(self, code: str, message: str, **params: Any):
        super().__init__(message, **params)
        self.code = code


class LifecycleGroupConflictError(CodedValueError):
    """A change the integrity rules refuse (HTTP 409); ``code`` says why."""

    def __init__(self, code: str, message: str, **params: Any):
        super().__init__(message, **params)
        self.code = code


# --------------------------------------------------------------------------- in-memory groups

@dataclass
class Stage:
    key: str
    label: str
    category: str
    color: Optional[str]
    order: int
    is_initial: bool

    def as_dict(self) -> Dict[str, Any]:
        return {
            'key': self.key, 'label': self.label, 'category': self.category,
            'color': self.color, 'order': self.order, 'is_initial': self.is_initial,
        }


@dataclass
class Group:
    id: Optional[str]
    name: str
    entity_type: str
    is_default_for_type: bool
    stages: Dict[str, Stage] = field(default_factory=dict)  # key -> stage, in order
    transitions: Dict[str, List[str]] = field(default_factory=dict)  # key -> next keys

    @property
    def initial(self) -> Optional[Stage]:
        return next((s for s in self.stages.values() if s.is_initial), None)

    def targets(self, key: Optional[str]) -> List[Stage]:
        """The stages ``key`` may move to, in stage order."""
        keys = self.transitions.get((key or '').lower(), [])
        return sorted((self.stages[k] for k in keys if k in self.stages), key=lambda s: s.order)

    def category(self, key: Optional[str]) -> Optional[str]:
        stage = self.stages.get((key or '').lower())
        return stage.category if stage else None


def _group_from_definition(definition: dict) -> Group:
    stages = sorted(definition['stages'], key=lambda s: s.get('order', 0))
    group = Group(
        id=definition.get('id'), name=definition['name'],
        entity_type=definition['entity_type'],
        is_default_for_type=bool(definition.get('is_default_for_type')),
    )
    for s in stages:
        group.stages[s['key']] = Stage(
            s['key'], s['label'], s['category'], s.get('color'), s.get('order', 0),
            bool(s.get('is_initial')),
        )
    for t in definition['transitions']:
        group.transitions.setdefault(t['from_key'], []).append(t['to_key'])
    return group


def _group_from_db(row) -> Group:
    ids = {s.id: s.key for s in row.stages}
    return _group_from_definition({
        'id': row.id, 'name': row.name, 'entity_type': row.entity_type,
        'is_default_for_type': row.is_default_for_type,
        'stages': [{
            'key': s.key, 'label': s.label, 'category': s.category, 'color': s.color,
            'order': s.order, 'is_initial': s.is_initial,
        } for s in row.stages],
        'transitions': [
            {'from_key': ids[t.from_stage_id], 'to_key': ids[t.to_stage_id]}
            for t in row.transitions if t.from_stage_id in ids and t.to_stage_id in ids
        ],
    })


def _action_target(
    group: Group, current: str, action: str,
) -> Tuple[Optional[str], Optional[str], List[str]]:
    """``(target, category, candidates)`` of a named action from ``current``: the
    action's seeded stage when it is an allowed move, else the only allowed
    target of the first of its categories with one. No target: ``candidates``
    lists the stages of an ambiguous ``category`` (empty when no move fits)."""
    seeded_key, categories = NAMED_ACTIONS[action]
    targets = group.targets(current)
    if any(s.key == seeded_key for s in targets):
        return seeded_key, None, []
    if seeded_key not in group.stages:
        for category in categories:
            candidates = [s.key for s in targets if s.category == category]
            if len(candidates) == 1:
                return candidates[0], category, []
            if candidates:
                return None, category, candidates
    return None, None, []


def _approved_review_stages(group: Group) -> set:
    """The review stages the approve action moves to from a review stage."""
    out = set()
    for stage in group.stages.values():
        if stage.category != 'review':
            continue
        target = _action_target(group, stage.key, 'approve')[0]
        if target is not None and group.category(target) == 'review':
            out.add(target)
    return out


# The seeded definitions, for an entity type with no stored group. Their id is
# None: an entity created meanwhile stores no group (= the default).
_BUILTIN: Dict[str, Group] = {
    t: _group_from_definition({**default_group_definition(t), 'id': None})
    for t in LIFECYCLE_ENTITY_TYPES
}


def _utc(value: Optional[datetime]) -> Optional[datetime]:
    """Aware UTC (a naive value, as SQLite returns, is taken as UTC)."""
    if value is None:
        return None
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else \
        value.astimezone(timezone.utc)


def _next_updated_at(previous: Optional[datetime]) -> datetime:
    """Now (UTC), and always later than ``previous``, so every save moves the token."""
    now = datetime.now(timezone.utc)
    if previous is not None and now <= _utc(previous):
        return _utc(previous) + timedelta(microseconds=1)
    return now


def _normalized(status: Any) -> str:
    value = getattr(status, 'value', status)
    return str(value or '').strip().lower()


def _entity_id(entity: Any) -> str:
    return str(getattr(entity, 'id', '') or '')


def row_session(row: Any) -> Optional[Session]:
    """The session an ORM ``row`` is attached to; None for anything else (API models,
    dicts, detached rows)."""
    if row is None or isinstance(row, (dict, str)):
        return None
    try:
        return object_session(row)
    except Exception:
        return None


_ENTITY_TYPE_BY_TABLE = {
    'data_products': 'data_product', 'data_contracts': 'data_contract', 'assets': 'asset',
}


def entity_type_of_row(row: Any) -> Optional[str]:
    """The lifecycle entity type of an ORM ``row`` (None for anything else)."""
    return _ENTITY_TYPE_BY_TABLE.get(getattr(getattr(row, '__table__', None), 'name', None))


# --------------------------------------------------------------------------- the service

_GROUP_NAME_CONSTRAINT = 'uq_lifecycle_stage_groups_type_name'


def _is_group_name_clash(exc: IntegrityError) -> bool:
    """Whether ``exc`` is the unique (entity type, name) constraint of the groups.

    Postgres names the constraint; SQLite (tests) lists its columns.
    """
    diag = getattr(getattr(exc, 'orig', None), 'diag', None)
    if getattr(diag, 'constraint_name', None) == _GROUP_NAME_CONSTRAINT:
        return True
    text_ = str(getattr(exc, 'orig', exc))
    return _GROUP_NAME_CONSTRAINT in text_ or (
        'lifecycle_stage_groups.entity_type, lifecycle_stage_groups.name' in text_
    )


class LifecycleService:

    def __init__(self):
        self._lock = threading.Lock()
        self._loaded_at = 0.0
        self._groups: Dict[str, Group] = {}
        self._defaults: Dict[str, str] = {}
        # Unknown group ids already logged by a lookup without a session
        self._warned_unknown: set = set()

    # ---- cache

    def invalidate(self) -> None:
        with self._lock:
            self._loaded_at = 0.0
            self._groups = {}
            self._defaults = {}
            self._warned_unknown = set()

    def _load(self, db: Session) -> None:
        from src.db_models.lifecycle_stage_groups import LifecycleStageGroupDb

        groups: Dict[str, Group] = {}
        defaults: Dict[str, str] = {}
        # Savepoint: a failed read must not abort the caller's transaction
        with db.begin_nested():
            rows = db.query(LifecycleStageGroupDb).all()
        for row in rows:
            group = _group_from_db(row)
            groups[row.id] = group
            if row.is_default_for_type:
                defaults[row.entity_type] = row.id
        with self._lock:
            self._groups, self._defaults = groups, defaults
            self._loaded_at = time.monotonic()

    def warm(self, db: Session) -> None:
        """Load the groups now (startup, after a save): rows read without a session
        (API models) get their category from this cache."""
        try:
            self._load(db)
        except Exception as e:
            logger.warning("Could not load lifecycle stage groups: %s", e)

    def _ensure(self, db: Optional[Session]) -> None:
        if db is None:
            return
        if time.monotonic() - self._loaded_at < _CACHE_SECONDS:
            return
        try:
            self._load(db)
        except Exception as e:  # e.g. a database without the tables yet
            logger.warning("Could not load lifecycle stage groups: %s", e)

    def _ensure_all_known(self, db: Optional[Session]) -> None:
        """For SQL built from the cache: reload when the table holds a group id the
        cache doesn't know (a group another worker created less than
        ``_CACHE_SECONDS`` ago), so its rows aren't judged by the default group."""
        self._ensure(db)
        if db is None:
            return
        from src.db_models.lifecycle_stage_groups import LifecycleStageGroupDb
        try:
            # Savepoint: a failed read must not abort the caller's transaction
            with db.begin_nested():
                ids = {i for (i,) in db.query(LifecycleStageGroupDb.id).all()}
            if ids - set(self._groups):
                self._load(db)
        except Exception as e:
            logger.warning("Could not check the lifecycle stage groups: %s", e)

    # ---- groups of entities

    def default_group(self, db: Optional[Session], entity_type: str) -> Group:
        """The entity type's default group (the seeded definition while none is stored)."""
        self._ensure(db)
        group_id = self._defaults.get(entity_type)
        return self._groups.get(group_id) if group_id else _BUILTIN[entity_type]

    def group(self, db: Optional[Session], group_id: Optional[str]) -> Optional[Group]:
        """The cached group; with ``db``, an id the cache doesn't know (a group
        another worker created less than ``_CACHE_SECONDS`` ago) reloads it once."""
        self._ensure(db)
        if not group_id:
            return None
        found = self._groups.get(group_id)
        seeded_only = not self._groups and group_id in DEFAULT_GROUP_IDS.values()
        if found is None and db is not None and not seeded_only:
            try:
                self._load(db)
            except Exception as e:
                logger.warning("Could not reload lifecycle stage groups: %s", e)
            found = self._groups.get(group_id)
        return found

    def _row_group(
        self, row: Any, db: Optional[Session] = None, entity_type: Optional[str] = None,
    ) -> Optional[Group]:
        """The group of ``row``, loaded through ``db`` or the row's own session. A row
        without a group belongs to its type's default group, once one is stored
        (``entity_type``, else the row's table); None when none is, or the type is not
        known. With no session, an id the cache doesn't know (a group another worker
        created less than ``_CACHE_SECONDS`` ago) logs a warning once and returns None:
        the caller falls back to the seeded stages."""
        group_id = getattr(row, 'lifecycle_stage_group_id', None)
        if not group_id:
            entity_type = entity_type or entity_type_of_row(row)
            if entity_type is None:
                return None
            self._ensure(db or row_session(row))
            default_id = self._defaults.get(entity_type)
            return self._groups.get(default_id) if default_id else None
        group_id = str(group_id)
        if db is None:
            db = row_session(row)
        group = self.group(db, group_id)
        if group is None and db is None and group_id not in DEFAULT_GROUP_IDS.values() \
                and group_id not in self._warned_unknown:
            if len(self._warned_unknown) < 1000:
                self._warned_unknown.add(group_id)
            logger.warning(
                "Lifecycle stage group %s is not cached and no session is at hand; "
                "using the seeded stage categories until the cache reloads", group_id,
            )
        return group

    def fill_status_category(self, model: Any, source: Any = None) -> Any:
        """For API model validators: set ``model.status_category`` from its group when
        unset, through the session of ``source`` (the ORM row it was validated from)."""
        if getattr(model, 'status_category', None) is None and getattr(model, 'status', None):
            model.status_category = self.category_of_row(
                model, db=row_session(source), entity_type=entity_type_of_row(source),
            )
        return model

    def groups(self, db: Session, entity_type: Optional[str] = None) -> List[Group]:
        self._ensure(db)
        types = [entity_type] if entity_type else list(LIFECYCLE_ENTITY_TYPES)
        out: List[Group] = []
        for t in types:
            stored = [g for g in self._groups.values() if g.entity_type == t]
            out.extend(sorted(stored, key=lambda g: (not g.is_default_for_type, g.name.lower()))
                       if stored else [_BUILTIN[t]])
        return out

    def group_for(self, db: Optional[Session], entity_type: str, entity: Any) -> Group:
        """The group of ``entity``: its own, or the type's default when it has none.

        A group id the cache doesn't know (a group another worker created less
        than ``_CACHE_SECONDS`` ago) reloads the groups once, through ``db`` or the
        entity's own session; a group still missing then raises
        ``LifecycleGroupNotFoundError`` instead of using the default's moves.
        """
        group_id = getattr(entity, 'lifecycle_stage_group_id', None)
        if not group_id:
            return self.default_group(db, entity_type)
        group_id = str(group_id)
        group = self.group(db, group_id)
        if group is None and db is None:
            try:
                db = object_session(entity)
            except Exception:
                db = None
            if db is not None:
                group = self.group(db, group_id)
        if group is None and db is not None:
            if not self._groups and group_id == DEFAULT_GROUP_IDS.get(entity_type):
                # The seeded default's id while no group is stored yet
                return self.default_group(db, entity_type)
            raise LifecycleGroupNotFoundError(
                f"Lifecycle stage group '{group_id}' not found", groupId=group_id,
            )
        if group is not None and group.entity_type == entity_type:
            return group
        return self.default_group(db, entity_type)

    def initial_stage_of(
        self, db: Optional[Session], entity_type: str, entity: Any,
    ) -> Tuple[Optional[str], str]:
        """``(group_id, initial stage key)`` of ``entity``'s group: where a new
        version or clone of it starts."""
        group = self.group_for(db, entity_type, entity)
        stage = group.initial or next(iter(group.stages.values()))
        return group.id, stage.key

    # ---- transitions

    def allowed_targets(self, db: Optional[Session], entity_type: str, entity: Any) -> List[Stage]:
        current = _normalized(getattr(entity, 'status', None)) or 'draft'
        return self.group_for(db, entity_type, entity).targets(current)

    def allowed_target_keys(
        self, db: Optional[Session], entity_type: str, entity: Any,
    ) -> List[str]:
        return [s.key for s in self.allowed_targets(db, entity_type, entity)]

    def check_transition(
        self, db: Optional[Session], entity_type: str, entity: Any, target: str,
    ) -> Tuple[str, str]:
        """``(from_key, to_key)`` of an allowed move, lowercase.

        Raises ``InvalidStatusTransitionError`` (with ``allowed``) otherwise; a
        status that isn't a stage of the group allows no move.
        """
        current = _normalized(getattr(entity, 'status', None)) or 'draft'
        target = _normalized(target)
        allowed = self.allowed_target_keys(db, entity_type, entity)
        if target not in allowed:
            raise InvalidStatusTransitionError(
                f"Invalid status transition from '{current}' to '{target}'. "
                f"Allowed transitions: {', '.join(allowed) if allowed else 'none'}",
                fromStatus=current, toStatus=target, allowed=allowed,
            )
        return current, target

    def resolve_action(
        self, db: Optional[Session], entity_type: str, entity: Any, action: str,
    ) -> str:
        """The stage key a named action moves ``entity`` to.

        The action's seeded stage when the group has that stage (refused when the
        move isn't allowed); in a group without it, the only allowed target in
        the action's Stage Category (``approve``: review, then active). None
        raises ``InvalidStatusTransitionError``, several
        ``LifecycleActionUnresolvedError`` (both HTTP 409 on the action routes).
        """
        group = self.group_for(db, entity_type, entity)
        current = _normalized(getattr(entity, 'status', None)) or 'draft'
        seeded_key = NAMED_ACTIONS[action][0]
        target, category, candidates = _action_target(group, current, action)
        if target is not None:
            return target
        if candidates:
            raise LifecycleActionUnresolvedError(
                f"'{action}' is ambiguous from '{current}': several allowed stages "
                f"are in category '{category}' ({', '.join(candidates)})",
                action=action, fromStatus=current, category=category,
                candidates=candidates,
            )
        # The refusal the UI already translates: a move the lifecycle doesn't allow
        allowed = [s.key for s in group.targets(current)]
        raise InvalidStatusTransitionError(
            f"Invalid status transition from '{current}' to '{seeded_key}'. "
            f"Allowed transitions: {', '.join(allowed) if allowed else 'none'}",
            fromStatus=current, toStatus=seeded_key, allowed=allowed, action=action,
        )

    def awaits_review_decision(self, db: Optional[Session], entity_type: str, entity: Any) -> bool:
        """In a review stage that awaits a decision: any review stage that the approve
        action doesn't move to from another review stage of the group (proposed /
        under_review by default, not approved; in ``draft -> review_a -> approved_x ->
        active``, review_a).

        Intended: a review stage reached by approving from another review stage is
        decided, as ``approved`` is in the default groups, whatever its own approve
        move: in ``draft -> review_a -> review_b -> active`` approve on review_b is
        refused (409) and Publish moves it to active, so nothing gets stuck."""
        group = self.group_for(db, entity_type, entity)
        key = _normalized(getattr(entity, 'status', None))
        if group.category(key) != 'review':
            return False
        return key not in _approved_review_stages(group)

    def submit_review_stage(self, db: Optional[Session], entity_type: str,
                            entity: Any) -> Optional[str]:
        """The stage submit-review moves the entity's group to (``proposed`` by
        default): the action's seeded stage when the group has it, else the only
        review stage a draft-category stage moves to; None when there are several."""
        group = self.group_for(db, entity_type, entity)
        seeded = NAMED_ACTIONS['submit_review'][0]
        if seeded in group.stages:
            return seeded
        candidates = {
            target.key
            for stage in group.stages.values() if stage.category == 'draft'
            for target in group.targets(stage.key) if target.category == 'review'
        }
        return candidates.pop() if len(candidates) == 1 else None

    def editable_in_place(self, db: Optional[Session], entity_type: str, entity: Any) -> bool:
        """Edited in place rather than versioned: a draft-category stage, or the stage
        submit-review reaches (draft, sandbox, proposed by default). Once a review
        has started, a breaking change is versioned. The update routes' versioning
        check and the clone-for-editing guard share this rule."""
        if self.category_of(db, entity_type, entity) == 'draft':
            return True
        key = _normalized(getattr(entity, 'status', None))
        return bool(key) and key == self.submit_review_stage(db, entity_type, entity)

    def review_activation_steps(
        self, db: Optional[Session], entity_type: str, entity: Any,
    ) -> Optional[List[str]]:
        """The stages a reviewed entity walks through to an active-category stage,
        from its review stage: at each step an allowed active stage, else the next
        review stage forward (``proposed -> under_review -> approved -> active`` by
        default). None when the entity isn't in review or no path reaches active."""
        group = self.group_for(db, entity_type, entity)
        current = _normalized(getattr(entity, 'status', None))
        if group.category(current) != 'review':
            return None
        steps: List[str] = []
        seen = {current}
        while group.category(current) != ACTIVE:
            targets = group.targets(current)
            active = [s for s in targets if s.category == ACTIVE]
            if active:
                nxt = next((s for s in active if s.key == ACTIVE), active[0])
            else:
                order = group.stages[current].order
                forward = [s for s in targets
                           if s.category == 'review' and s.order > order and s.key not in seen]
                if not forward:
                    return None
                nxt = forward[0]
            steps.append(nxt.key)
            seen.add(nxt.key)
            current = nxt.key
        return steps

    def contract_publishable(self, db: Optional[Session], entity: Any) -> bool:
        """A contract may be published (or its publication requested): it is in an
        active-category stage, or in the approve action's review stage (``approved``,
        a review stage that no longer awaits a decision)."""
        category = self.category_of(db, 'data_contract', entity)
        if category == ACTIVE:
            return True
        return category == 'review' and not self.awaits_review_decision(
            db, 'data_contract', entity,
        )

    # ---- categories

    def category_of(self, db: Optional[Session], entity_type: str, entity: Any) -> Optional[str]:
        return self.group_for(db, entity_type, entity).category(getattr(entity, 'status', None))

    def category_of_row(
        self, row: Any, db: Optional[Session] = None, entity_type: Optional[str] = None,
    ) -> Optional[str]:
        """The Stage Category of a product, contract or asset row of any kind.

        Uses the row's group when it is cached (loading the cache through ``db``
        or the row's own session), or the type's stored default group for a row
        without one; else the seeded categories of the stage key. ``entity_type``
        names the type of a row that isn't an ORM row (an API model).
        """
        key = _normalized(getattr(row, 'status', None))
        group = self._row_group(row, db, entity_type)
        if group is not None:
            return group.category(key)
        return DEFAULT_STAGE_CATEGORIES.get(key)

    def keys_of_category_anywhere(self, category: str, db: Optional[Session] = None) -> set:
        """Stage keys in ``category`` in any known group (seeded or cached; with ``db``
        the groups are (re)loaded first)."""
        self._ensure(db)
        keys = {k for k, c in DEFAULT_STAGE_CATEGORIES.items() if c == category}
        for group in list(self._groups.values()):
            keys.update(s.key for s in group.stages.values() if s.category == category)
        return keys

    def is_side_draft_stage(self, row: Any, db: Optional[Session] = None) -> bool:
        """A draft-category stage other than its group's first (``sandbox`` by default)."""
        group = self._row_group(row, db) or _BUILTIN[entity_type_of_row(row) or 'data_product']
        stage = group.stages.get(_normalized(getattr(row, 'status', None)))
        return bool(stage and stage.category == 'draft' and not stage.is_initial)

    def stage_order_of_row(self, row: Any, db: Optional[Session] = None) -> int:
        key = _normalized(getattr(row, 'status', None))
        group = self._row_group(row, db)
        stages = (group or _BUILTIN[entity_type_of_row(row) or 'data_product']).stages
        stage = stages.get(key)
        return stage.order if stage else 999

    def keys_in_categories(
        self, db: Optional[Session], entity_type: str, categories: Iterable[str],
    ) -> Dict[Optional[str], List[str]]:
        """Per group id (None = no group, i.e. the default), its stage keys in ``categories``."""
        categories = set(categories)
        out: Dict[Optional[str], List[str]] = {}
        self._ensure_all_known(db)
        default = self.default_group(db, entity_type)
        for group in self.groups(db, entity_type) if db is not None else [default]:
            out[group.id] = [s.key for s in group.stages.values() if s.category in categories]
        default_keys = [s.key for s in default.stages.values() if s.category in categories]
        out[None] = default_keys
        # Rows backfilled with the seeded default's id, while the groups aren't
        # loaded (the cache holds the built-in default, whose id is None)
        out.setdefault(DEFAULT_GROUP_IDS[entity_type], default_keys)
        return out

    def first_stage_of_row(self, row: Any, entity_type: str) -> bool:
        """Whether ``row`` is in its own group's first stage (a personal draft's)."""
        group = self.group_for(None, entity_type, row)
        initial = group.initial
        return initial is not None and _normalized(getattr(row, 'status', None)) == initial.key

    def first_stage_filter(self, model: Any, entity_type: str, db: Optional[Session] = None):
        """SQL condition: the row is in its own group's first stage (rows of other or
        unknown groups in the default group's first stage). With ``db`` the groups
        are (re)loaded first, so a cold or stale cache doesn't miss a custom group."""
        from sqlalchemy import and_, func, or_

        self._ensure_all_known(db)
        status = func.lower(func.trim(func.coalesce(model.status, '')))
        column = model.lifecycle_stage_group_id
        default = self.default_group(db, entity_type)
        others = [g for g in list(self._groups.values())
                  if g.entity_type == entity_type and g.id != default.id and g.initial]
        default_key = (default.initial or next(iter(default.stages.values()))).key
        clauses = [and_(column == g.id, status == g.initial.key) for g in others]
        in_other = column.in_([g.id for g in others]) if others else None
        default_rows = status == default_key
        if in_other is not None:
            default_rows = and_(or_(column.is_(None), ~in_other), default_rows)
        return or_(default_rows, *clauses)

    def category_filter(self, db: Session, model: Any, entity_type: str,
                        categories: Iterable[str]):
        """SQL condition: the row's stage is in one of ``categories`` (in its own group)."""
        from sqlalchemy import and_, false, func, or_

        clauses = []
        status = func.lower(func.trim(func.coalesce(model.status, '')))
        for group_id, keys in self.keys_in_categories(db, entity_type, categories).items():
            if not keys:
                continue
            column = model.lifecycle_stage_group_id
            in_group = column.is_(None) if group_id is None else column == group_id
            clauses.append(and_(in_group, status.in_(keys)))
        return or_(*clauses) if clauses else false()

    # ---- new and imported entities

    def stage_for_new(
        self, db: Optional[Session], entity_type: str, group_id: Optional[str],
        status: Optional[str], default_category: Optional[str] = None,
        model_default: Optional[str] = None,
    ) -> Tuple[Optional[str], str]:
        """``(group_id, stage key)`` a new entity starts in.

        ``model_default``: the status the create model fills in when none is sent
        (``draft``); in a group without that stage it means "no status".

        ``group_id`` must be a group of ``entity_type`` (None = the default
        group). Without a status the entity starts in the initial stage, or in
        the first stage of ``default_category`` when given (assets start
        active). A status must be a stage of the group; ``certified`` is not.
        """
        from src.common.lifecycle_status import CertifiedIsNotAStatusError, InvalidStatusError

        group = self.require_group(db, entity_type, group_id) if group_id else \
            self.default_group(db, entity_type)
        key = _normalized(status)
        if key and key == model_default and key not in group.stages:
            key = ''
        if not key:
            stage = None
            if default_category:
                stage = next(
                    (s for s in group.stages.values() if s.category == default_category), None,
                )
            stage = stage or group.initial or next(iter(group.stages.values()))
            return group.id, stage.key
        if key == 'certified':
            raise CertifiedIsNotAStatusError()
        if key not in group.stages:
            raise InvalidStatusError(key, list(group.stages))
        return group.id, key

    def require_group(self, db: Optional[Session], entity_type: str, group_id: str) -> Group:
        group = self.group(db, group_id)
        if group is None and group_id == DEFAULT_GROUP_IDS.get(entity_type):
            # The seeded default's id, before (or without) the seed being stored
            group = self.default_group(db, entity_type)
        if group is None:
            raise LifecycleGroupNotFoundError(
                f"Lifecycle stage group '{group_id}' not found", groupId=group_id,
            )
        if group.entity_type != entity_type:
            raise LifecycleGroupInvalidError(
                'lifecycle_group_wrong_entity_type',
                f"Lifecycle stage group '{group.name}' is for {group.entity_type}, "
                f"not {entity_type}",
                groupId=group_id, groupEntityType=group.entity_type, entityType=entity_type,
            )
        return group

    def export_status(
        self, db: Optional[Session], entity_type: str, entity: Any,
    ) -> Tuple[str, Dict[str, str]]:
        """The ODCS / ODPS ``status`` (the category's standard value) and the
        ``ontosLifecycleStage`` / ``ontosLifecycleStageGroup`` /
        ``ontosLifecycleStageGroupId`` custom properties (the id survives a rename)."""
        group = self.group_for(db, entity_type, entity)
        key = _normalized(getattr(entity, 'status', None)) or 'draft'
        # A status that isn't a stage of the group (stored before the clean-up):
        # its seeded category, else draft, so the export stays a standard value
        category = group.category(key) or DEFAULT_STAGE_CATEGORIES.get(key) or 'draft'
        status = STANDARD_STATUS_BY_CATEGORY[category]
        return status, {
            ONTOS_LIFECYCLE_STAGE_PROPERTY: key,
            ONTOS_LIFECYCLE_STAGE_GROUP_PROPERTY: group.name,
            ONTOS_LIFECYCLE_STAGE_GROUP_ID_PROPERTY: group.id or DEFAULT_GROUP_IDS[entity_type],
        }

    def import_stage(
        self, db: Optional[Session], entity_type: str, status: Any, custom_props: Any,
    ) -> Tuple[Optional[str], Optional[str], Optional[Dict[str, Any]]]:
        """``(group_id, stage key, note)`` of an imported entity.

        Pops ``ontosLifecycleStage`` / ``ontosLifecycleStageGroup`` /
        ``ontosLifecycleStageGroupId`` from ``customProperties`` (list or dict
        form). The stage and group are restored when this install has a group of
        that id (of that name when the id is unknown here, e.g. another install)
        with that stage (the default group when no group is named or it is
        unknown here).
        Otherwise the status is kept when it is a stage key of the default
        group, or mapped by Stage Category to the first stage of its category
        (``proposed`` -> the first review stage). ``stage key`` None = let the
        caller apply its status rules (``import_status``) in the default group.
        """
        props = pop_lifecycle_properties(custom_props)
        stage_key = _normalized(props.get(ONTOS_LIFECYCLE_STAGE_PROPERTY))
        group_name = str(props.get(ONTOS_LIFECYCLE_STAGE_GROUP_PROPERTY) or '').strip()
        group_id = str(props.get(ONTOS_LIFECYCLE_STAGE_GROUP_ID_PROPERTY) or '').strip()
        default = self.default_group(db, entity_type)
        named = None
        if group_id:
            self._ensure(db)
            by_id = self._groups.get(group_id)
            if by_id is None and group_id == DEFAULT_GROUP_IDS[entity_type]:
                by_id = default
            if by_id is not None and by_id.entity_type == entity_type:
                named = by_id
        if named is None and group_name:
            named = next(
                (g for g in self.groups(db, entity_type) if g.name.lower() == group_name.lower()),
                None,
            ) if db is not None else (default if default.name.lower() == group_name.lower()
                                      else None)
        group = named or default
        note = None
        if (group_name or group_id) and named is None:
            note = {
                'code': 'imported_lifecycle_group_unknown',
                'params': {'group': group_name, 'mappedTo': default.name},
                'message': (
                    f"Lifecycle stage group '{group_name}' doesn't exist here, so the "
                    f"entity was imported into '{default.name}'."
                ),
            }
        if stage_key and stage_key in group.stages:
            return group.id, stage_key, note
        key = _normalized(status)
        if key and key in default.stages:
            return default.id, key, note
        category = next((c for c, v in STANDARD_STATUS_BY_CATEGORY.items() if v == key), None)
        if category:
            stage = next((s for s in default.stages.values() if s.category == category), None)
            if stage is not None:
                return default.id, stage.key, note
        return default.id, None, note

    def imported_status(
        self, db: Optional[Session], entity_type: str, status: Any, custom_props: Any,
    ) -> Tuple[Optional[str], str, Optional[Dict[str, Any]]]:
        """``(group_id, stage key, note)`` of an imported entity, always with a stage.

        ``import_stage``, then for a status it can't place the import rules of
        ``import_status`` (older names, ``certified``, unknown -> initial stage)
        in the default group.
        """
        from src.common.lifecycle_status import import_status

        group_id, key, note = self.import_stage(db, entity_type, status, custom_props)
        if key is not None:
            return group_id, key, note
        default = self.default_group(db, entity_type)
        initial = default.initial or next(iter(default.stages.values()))
        key, status_note = import_status(status, list(default.stages), default=initial.key)
        return default.id, key, status_note or note

    # ---- entity read model and group change

    def entity_lifecycle(self, db: Session, entity_type: str, entity: Any) -> Dict[str, Any]:
        group = self.group_for(db, entity_type, entity)
        key = _normalized(getattr(entity, 'status', None)) or 'draft'
        stage = group.stages.get(key)
        return {
            'entity_type': entity_type,
            'entity_id': _entity_id(entity),
            'group': {
                'id': group.id, 'name': group.name, 'entity_type': group.entity_type,
                'is_default_for_type': group.is_default_for_type,
            },
            'status': key,
            'stage': stage.as_dict() if stage else None,
            'allowed_transitions': [s.as_dict() for s in group.targets(key)],
        }

    def change_group(
        self, db: Session, entity_type: str, entity_id: str, group_id: str,
        user: Optional[str],
    ) -> Dict[str, Any]:
        """Move an entity to another group of its type, in that group's initial stage.

        Refused (409) while a status change request or a paused workflow is
        pending for the entity. Writes a change-log entry; commits.
        """
        from src.repositories.lifecycle_stage_groups_repository import entity_model

        model = entity_model(entity_type)
        entity = db.get(model, _model_id(model, entity_id))
        if entity is None:
            raise LifecycleGroupNotFoundError(
                f"{entity_type} '{entity_id}' not found", entityId=entity_id,
            )
        target = self.require_group(db, entity_type, group_id)
        current = self.group_for(db, entity_type, entity)
        if (target.id or DEFAULT_GROUP_IDS[entity_type]) == \
                (current.id or DEFAULT_GROUP_IDS[entity_type]):
            raise LifecycleGroupConflictError(
                'lifecycle_change_same_group',
                f"The entity already follows '{target.name}'; change its status instead",
                entityId=str(entity.id), groupId=target.id,
            )
        pending = pending_workflow_request(db, entity_type, str(entity.id))
        if pending:
            raise LifecycleGroupConflictError(
                'lifecycle_change_pending_request',
                "The lifecycle can't change while a workflow request is pending for it",
                entityId=str(entity.id), requestId=pending,
            )
        initial = target.initial or next(iter(target.stages.values()))
        from_status = _normalized(entity.status)
        entity.lifecycle_stage_group_id = target.id
        entity.status = initial.key
        # Not a transition: no gates or on_status_change (the new group's moves
        # start from its first stage). A published entity leaves the Marketplace
        # unless that stage is published too.
        unpublished = False
        if (getattr(entity, 'publication_scope', None) or 'none').lower() != 'none' and \
                initial.category not in ('active', 'deprecated'):
            entity.publication_scope = 'none'
            entity.published_at = None
            entity.published_by = None
            unpublished = True
        if hasattr(entity, 'updated_by'):
            entity.updated_by = user
        db.add(entity)
        from src.controller.change_log_manager import change_log_manager
        change_log_manager.log_change_with_details(
            db, entity_type=entity_type, entity_id=str(entity.id),
            action='LIFECYCLE_GROUP_CHANGE', username=user,
            details={
                'from_group_id': current.id, 'from_group': current.name,
                'to_group_id': target.id, 'to_group': target.name,
                'from_status': from_status, 'to_status': initial.key,
                'unpublished': unpublished,
                'summary': (
                    f"Lifecycle changed from '{current.name}' to '{target.name}'; "
                    f"status reset from '{from_status}' to '{initial.key}'"
                ),
            },
        )
        db.commit()
        db.refresh(entity)
        _refresh_search_index(entity_type, entity, db)
        _request_tag_sync(entity_type, str(entity.id), from_status, initial.key)
        return self.entity_lifecycle(db, entity_type, entity)

    # ---- group writes (Settings)

    def validate_definition(self, data: Dict[str, Any]) -> None:
        """Raise ``LifecycleGroupInvalidError`` unless the group can be saved.

        Stage keys are lowercase ``[a-z0-9_]`` and unique; categories are Stage
        Categories; transitions join two stages of the group; exactly one stage
        is initial, every stage is reachable from it, at least one stage is in
        the active category, and every stage but a retired-category one has a
        move out.
        """
        stages = data.get('stages') or []
        keys: List[str] = []
        for stage in stages:
            key = stage['key']
            if not key or key != key.lower() or not set(key) <= _STAGE_KEY_CHARS:
                raise LifecycleGroupInvalidError(
                    'lifecycle_stage_invalid_key',
                    f"Stage key '{key}' must be lowercase letters, digits and underscores",
                    key=key,
                )
            if key in keys:
                raise LifecycleGroupInvalidError(
                    'lifecycle_stage_duplicate_key', f"Stage key '{key}' is used twice", key=key,
                )
            if stage['category'] not in STAGE_CATEGORIES:
                raise LifecycleGroupInvalidError(
                    'lifecycle_stage_invalid_category',
                    f"'{stage['category']}' is not a stage category", category=stage['category'],
                )
            keys.append(key)
        for t in data.get('transitions') or []:
            if t['from_key'] == t['to_key']:
                raise LifecycleGroupInvalidError(
                    'lifecycle_transition_self',
                    f"A stage can't move to itself ({t['from_key']})", key=t['from_key'],
                )
            for k in (t['from_key'], t['to_key']):
                if k not in keys:
                    raise LifecycleGroupInvalidError(
                        'lifecycle_transition_unknown_stage',
                        f"Transition {t['from_key']} -> {t['to_key']} names a stage the "
                        "group doesn't have",
                        fromKey=t['from_key'], toKey=t['to_key'],
                    )
        initial = [s['key'] for s in stages if s.get('is_initial')]
        if len(initial) != 1:
            raise LifecycleGroupInvalidError(
                'lifecycle_group_initial_stage',
                f"A group needs exactly one first stage; it has {len(initial)}",
                count=len(initial),
            )
        first = next(s for s in stages if s['key'] == initial[0])
        if first['category'] != 'draft':
            # A group change resets to the first stage: it must not skip review
            raise LifecycleGroupInvalidError(
                'lifecycle_group_initial_not_draft',
                f"The first stage '{initial[0]}' must be in the draft category",
                key=initial[0], category=first['category'],
            )
        reachable = {initial[0]}
        queue = deque(initial)
        nexts: Dict[str, List[str]] = {}
        for t in data.get('transitions') or []:
            nexts.setdefault(t['from_key'], []).append(t['to_key'])
        while queue:
            for nxt in nexts.get(queue.popleft(), []):
                if nxt not in reachable:
                    reachable.add(nxt)
                    queue.append(nxt)
        unreachable = [k for k in keys if k not in reachable]
        if unreachable:
            raise LifecycleGroupInvalidError(
                'lifecycle_group_unreachable_stages',
                f"Stages not reachable from '{initial[0]}': {', '.join(unreachable)}",
                stages=unreachable,
            )
        if not any(s['category'] == ACTIVE for s in stages):
            raise LifecycleGroupInvalidError(
                'lifecycle_group_no_active_stage', "A group needs at least one active stage",
            )
        # Only a retired-category stage may end the lifecycle
        dead_ends = [s['key'] for s in stages
                     if s['category'] != RETIRED and not nexts.get(s['key'])]
        if dead_ends:
            raise LifecycleGroupInvalidError(
                'lifecycle_group_dead_end_stages',
                f"Stages with no move out that aren't retired: {', '.join(dead_ends)}",
                stages=dead_ends,
            )

    def _check_stage_changes(self, db: Session, row, new_stages: List[Dict[str, Any]]) -> None:
        """Refuse removing a stage that entities are in or a workflow names, and moving
        a stage with entities across the active / deprecated / retired boundary (it
        would silently change what consumers, the Marketplace and search see)."""
        from src.repositories.lifecycle_stage_groups_repository import lifecycle_stage_groups_repo

        kept = {s['key']: s['category'] for s in new_stages}
        for stage in row.stages:
            if stage.key in kept:
                new_category = kept[stage.key]
                if new_category == stage.category or not (
                        {stage.category, new_category} & _VISIBILITY_CATEGORIES):
                    continue
                in_use = lifecycle_stage_groups_repo.count_entities_in_stage(
                    db, row.entity_type, row.id, stage.key,
                    include_unassigned=row.is_default_for_type,
                )
                if in_use:
                    raise LifecycleGroupConflictError(
                        'lifecycle_stage_category_in_use',
                        f"Stage '{stage.key}' can't move from category '{stage.category}' "
                        f"to '{new_category}': {in_use} entities are in it",
                        key=stage.key, fromCategory=stage.category,
                        toCategory=new_category, count=in_use,
                    )
                continue
            in_use = lifecycle_stage_groups_repo.count_entities_in_stage(
                db, row.entity_type, row.id, stage.key,
                include_unassigned=row.is_default_for_type,
            )
            if in_use:
                raise LifecycleGroupConflictError(
                    'lifecycle_stage_in_use',
                    f"Stage '{stage.key}' can't be removed: {in_use} entities are in it",
                    key=stage.key, count=in_use,
                )
            workflows = workflows_referencing_stage(db, row.entity_type, stage.key)
            if workflows:
                raise LifecycleGroupConflictError(
                    'lifecycle_stage_in_workflow',
                    f"Stage '{stage.key}' can't be removed: workflows use it "
                    f"({', '.join(workflows)})",
                    key=stage.key, workflows=workflows,
                )

    def _make_default(self, db: Session, row) -> None:
        """Make ``row`` its type's default; entities without a group keep the old one."""
        from src.repositories.lifecycle_stage_groups_repository import lifecycle_stage_groups_repo

        old = lifecycle_stage_groups_repo.get_default(db, row.entity_type)
        if old is not None and old.id != row.id:
            lifecycle_stage_groups_repo.assign_unassigned(db, row.entity_type, old.id)
            old.is_default_for_type = False
            db.flush()
        row.is_default_for_type = True

    def save_group(
        self, db: Session, data: Dict[str, Any], user: Optional[str],
        group_id: Optional[str] = None, expected_updated_at: Optional[datetime] = None,
    ):
        """Create (``group_id`` None) or replace a group; returns the stored row. Commits.

        ``expected_updated_at``: the ``updated_at`` the caller read; a group saved
        since then is refused (409 ``lifecycle_group_changed``) instead of the
        last write winning.
        """
        from src.db_models.lifecycle_stage_groups import LifecycleStageGroupDb
        from src.repositories.lifecycle_stage_groups_repository import lifecycle_stage_groups_repo

        # Stored trimmed, so "Foo " and "Foo" are the same name
        data = {**data, 'name': (data.get('name') or '').strip()}
        if not data['name']:
            raise LifecycleGroupInvalidError(
                'lifecycle_group_name_required', "A group needs a name",
            )
        self.validate_definition(data)
        same_name = lifecycle_stage_groups_repo.get_by_name(db, data['entity_type'], data['name'])
        if same_name is not None and same_name.id != group_id:
            raise LifecycleGroupConflictError(
                'lifecycle_group_name_taken',
                f"A {data['entity_type']} lifecycle named '{data['name']}' already exists",
                name=data['name'],
            )
        try:
            if group_id is None:
                lifecycle_stage_groups_repo.seed_defaults(db)
                row = LifecycleStageGroupDb(
                    entity_type=data['entity_type'], name=data['name'],
                    description=data.get('description'), created_by=user, updated_by=user,
                )
                db.add(row)
                db.flush()
            else:
                row = lifecycle_stage_groups_repo.get(db, group_id)
                if row is None:
                    raise LifecycleGroupNotFoundError(
                        f"Lifecycle stage group '{group_id}' not found", groupId=group_id,
                    )
                # The row as stored now, read under a lock (``FOR UPDATE`` on Postgres,
                # held until the commit) and refreshed, so a save committed since the
                # first read is seen, a concurrent save waits for this one, and every
                # check below sees current values
                locked = db.execute(
                    select(LifecycleStageGroupDb)
                    .where(LifecycleStageGroupDb.id == group_id)
                    .with_for_update()
                    .execution_options(populate_existing=True)
                ).scalar_one_or_none()
                if locked is None:  # deleted since the first read
                    raise LifecycleGroupNotFoundError(
                        f"Lifecycle stage group '{group_id}' not found", groupId=group_id,
                    )
                row = locked
                stored_token = row.updated_at
                if expected_updated_at is not None and \
                        _utc(stored_token) != _utc(expected_updated_at):
                    raise LifecycleGroupConflictError(
                        'lifecycle_group_changed',
                        f"'{row.name}' was changed since it was read; reload it first",
                        groupId=group_id, updatedBy=row.updated_by,
                    )
                new_token = _next_updated_at(stored_token)
                if row.entity_type != data['entity_type']:
                    raise LifecycleGroupInvalidError(
                        'lifecycle_group_entity_type_immutable',
                        "A group's entity type can't change", entityType=row.entity_type,
                    )
                if row.is_default_for_type and not data.get('is_default_for_type'):
                    raise LifecycleGroupConflictError(
                        'lifecycle_group_default_required',
                        "Make another group the default instead",
                        entityType=row.entity_type,
                    )
                self._check_stage_changes(db, row, data['stages'])
                row.name = data['name']
                row.description = data.get('description')
                row.updated_by = user
                # Set here: ``onupdate`` fires only when a column of the group row itself
                # changes, so a stage-only save by the same user would keep the old token
                row.updated_at = new_token
            if data.get('is_default_for_type'):
                self._make_default(db, row)
            lifecycle_stage_groups_repo.replace_stages(
                db, row, data['stages'], data.get('transitions') or [],
            )
            db.commit()
        except IntegrityError as exc:
            db.rollback()
            # The name check above runs before the lock: a create or rename racing
            # another one with the same name meets the unique constraint on flush
            if _is_group_name_clash(exc):
                raise LifecycleGroupConflictError(
                    'lifecycle_group_name_taken',
                    f"A {data['entity_type']} lifecycle named '{data['name']}' already exists",
                    name=data['name'],
                ) from None
            raise
        except Exception:
            db.rollback()
            raise
        finally:
            self.invalidate()
        db.refresh(row)
        self.warm(db)
        return row

    def delete_group(self, db: Session, group_id: str) -> None:
        """Delete a group: refused while it is its type's default or assigned to entities."""
        from src.repositories.lifecycle_stage_groups_repository import lifecycle_stage_groups_repo

        row = lifecycle_stage_groups_repo.get(db, group_id)
        if row is None:
            raise LifecycleGroupNotFoundError(
                f"Lifecycle stage group '{group_id}' not found", groupId=group_id,
            )
        if row.is_default_for_type:
            raise LifecycleGroupConflictError(
                'lifecycle_group_is_default',
                f"'{row.name}' is the default lifecycle of {row.entity_type}",
                groupId=group_id,
            )
        in_use = lifecycle_stage_groups_repo.count_entities(db, row.entity_type, group_id)
        if in_use:
            raise LifecycleGroupConflictError(
                'lifecycle_group_in_use',
                f"'{row.name}' is the lifecycle of {in_use} entities", groupId=group_id,
                count=in_use,
            )
        try:
            db.delete(row)
            db.commit()
        except Exception:
            db.rollback()
            raise
        finally:
            self.invalidate()
        self.warm(db)


def _model_id(model: Any, entity_id: str) -> Any:
    """Assets have UUID primary keys; products and contracts strings."""
    from src.db_models.assets import AssetDb

    if model is AssetDb:
        import uuid
        try:
            return uuid.UUID(str(entity_id))
        except ValueError:
            return None
    return entity_id


def _refresh_search_index(entity_type: str, entity: Any, db: Session) -> None:
    """Best effort: the search index shows the entity's new status (an asset reset
    to a retired-category stage leaves it)."""
    from src.common.app_state import get_app_state_manager

    try:
        if entity_type == 'data_contract':
            from src.controller.data_contracts_manager import reindex_contract_in_search_index
            reindex_contract_in_search_index(entity, db)
            return
        search_manager = get_app_state_manager('search_manager')
        if search_manager is None:
            return
        if entity_type == 'asset':
            from src.controller.assets_manager import AssetsManager
            manager = AssetsManager()
            manager.set_search_manager(search_manager)
            manager._update_search_index(entity)
        elif entity_type == 'data_product':
            from src.controller.data_products_manager import DataProductsManager
            manager = DataProductsManager(
                db=db, notifications_manager=get_app_state_manager('notifications_manager'),
            )
            manager.set_search_manager(search_manager)
            product = manager.get_product(str(entity.id))
            if product is not None:
                manager._update_search_index(product)
    except Exception as e:
        logger.warning("Search index not refreshed after a lifecycle change of %s %s: %s",
                       entity_type, getattr(entity, 'id', None), e)


def _request_tag_sync(entity_type: str, entity_id: str, from_status: str,
                      to_status: str) -> None:
    """A group change resets the status: request a uc_tag_sync run as a transition
    into or out of a deprecated / retired stage does (never raises)."""
    from src.common.uc_tag_sync_trigger import request_uc_tag_sync_after_transition

    request_uc_tag_sync_after_transition(entity_type, entity_id, from_status, to_status)


def pop_lifecycle_properties(custom_props: Any) -> Dict[str, Any]:
    """Remove ``ontosLifecycleStage`` / ``ontosLifecycleStageGroup`` from an imported
    ``customProperties`` (ODCS / ODPS list form or legacy dict form); return them."""
    found: Dict[str, Any] = {}
    if isinstance(custom_props, list):
        for item in list(custom_props):
            if isinstance(item, dict) and item.get('property') in LIFECYCLE_PROPERTIES:
                found[item['property']] = item.get('value')
                custom_props.remove(item)
    elif isinstance(custom_props, dict):
        for prop in LIFECYCLE_PROPERTIES:
            if prop in custom_props:
                found[prop] = custom_props.pop(prop)
    return found


def pending_workflow_request(db: Session, entity_type: str, entity_id: str) -> Optional[str]:
    """The id of a pending status change request, or of a paused workflow run, of an entity."""
    import json

    from src.db_models.process_workflows import WorkflowExecutionDb

    if entity_type in ('data_product', 'data_contract'):
        from src.controller.certified_deprecation_guard import pending_request_id
        try:
            request_id = pending_request_id(db, entity_type, entity_id)
        except Exception as e:
            logger.warning("Pending request lookup failed for %s %s: %s", entity_type, entity_id, e)
            request_id = None
        if request_id:
            return request_id
    paused = (
        db.query(WorkflowExecutionDb)
        .filter(
            WorkflowExecutionDb.status == 'paused',
            WorkflowExecutionDb.trigger_context.contains(entity_id),
        )
        .all()
    )
    for execution in paused:
        try:
            context = json.loads(execution.trigger_context or '{}')
        except (TypeError, ValueError):
            continue
        if str(context.get('entity_id')) == entity_id and \
                str(context.get('entity_type') or entity_type) == entity_type:
            return execution.id
    return None


def workflows_referencing_stage(db: Session, entity_type: str, key: str) -> List[str]:
    """Names of the workflows whose trigger matches ``key`` as from / to status."""
    import json

    from src.db_models.process_workflows import ProcessWorkflowDb

    names = []
    for workflow in db.query(ProcessWorkflowDb).all():
        try:
            trigger = json.loads(workflow.trigger_config or '{}')
        except (TypeError, ValueError):
            continue
        types = trigger.get('entity_types') or []
        if types and entity_type not in types:
            continue
        statuses = {_normalized(trigger.get('from_status')), _normalized(trigger.get('to_status'))}
        if key in statuses:
            names.append(workflow.name)
    return names


lifecycle_service = LifecycleService()
