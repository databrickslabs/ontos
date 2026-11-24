"""KPI consistency across metric views, phase 1 (#1263): stored fingerprints, read-only views.

The parsed spec of a Metric View asset and the fingerprints of its measures
(``common/metric_view_fingerprint.py``) are stored in
``AssetDb.properties['metric_view']`` when the view is imported, re-imported,
or read from Unity Catalog through the asset's metric view route. The views
built on them:

- by concept: the measures linked to a concept, grouped by full fingerprint,
  each group compared with the largest one;
- by asset: per measure, the other measures with the same or a similar
  definition over the same data, and conflicting links;
- a link check: the non-blocking warnings a new measure-to-concept link raises.

Definitions are shown only for views the caller's ``readable(fqn)`` accepts
(Unity Catalog read as the user); other measures carry their asset, name,
concepts and verdict only. Nothing is persisted here beyond the stored
fingerprints: candidates and decisions are phase 2.
"""
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Optional, Set
from uuid import UUID

from sqlalchemy.orm import Session

from src.common.api_errors import CodedValueError
from src.common.logging import get_logger
from src.common.metric_view_fingerprint import (
    DEFAULT_SIMILARITY_THRESHOLD, FINGERPRINT_VERSION, classify, fingerprint_metric_view,
    first_differing_level, similarity,
)
from src.common.metric_view_normalization import definition_digest, normalize_metric_view
from src.common.metric_views import metric_view_entity_id
from src.controller.term_mapping.naming import depluralize, normalize
from src.db_models.assets import AssetDb
from src.models.assets import METRIC_VIEW_PROPERTY
from src.models.metric_view_consistency import (
    ComponentDiff, FingerprintGroup, LinkCheck, LinkWarning, MeasureConsistency,
    MeasureDefinition, MeasureMatch, MeasureRef, MetricViewConsistency,
)
from src.repositories.assets_repository import asset_repo
from src.repositories.metric_view_fingerprints_repository import metric_view_fingerprints_repo

logger = get_logger(__name__)

STORE_KEY = METRIC_VIEW_PROPERTY
# Matches listed per measure, and names listed in a warning's params
MAX_MATCHES = 50
MAX_WARNING_ITEMS = 5

# Order of the verdicts in a measure's matches: the most actionable first
_VERDICT_ORDER = {
    'duplicate': 0, 'link_conflict': 1, 'conflict': 2, 'unrecognized_duplicate': 3,
    'variant': 4, 'near_duplicate': 5,
}

Readable = Callable[[str], bool]


class MetricViewAssetNotFoundError(CodedValueError):
    """The asset of a consistency request doesn't exist."""

    code = 'metric_view_asset_not_found'


def build_stored_metric_view(spec: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """What ``properties['metric_view']`` holds for a parsed spec (None for no spec).

    ``{spec, digest, fingerprint_version, measures, stored_at}``: ``digest`` is
    the drift digest of the definition (``metric_view_normalization``) and
    ``measures`` the fingerprint records of ``fingerprint_metric_view``.
    """
    if not spec:
        return None
    return {
        'spec': spec,
        'digest': definition_digest(normalize_metric_view(spec)),
        'fingerprint_version': FINGERPRINT_VERSION,
        'measures': fingerprint_metric_view(spec),
        'stored_at': datetime.now(timezone.utc).isoformat(),
    }


def store_metric_view(db: Session, asset: AssetDb, spec: Optional[Dict[str, Any]]) -> bool:
    """Store ``spec`` and its fingerprints on a Metric View asset. Flushes, doesn't commit.

    Does nothing (returns False) without a spec, or when the asset already
    holds this spec with fingerprints of the current version.
    """
    if not spec:
        return False
    properties = dict(asset.properties or {})
    current = properties.get(STORE_KEY)
    if (isinstance(current, dict) and current.get('spec') == spec
            and current.get('fingerprint_version') == FINGERPRINT_VERSION):
        return False
    properties[STORE_KEY] = build_stored_metric_view(spec)
    # A new dict, so SQLAlchemy sees the JSON column change
    asset.properties = properties
    db.flush()
    return True


def _view_fqn(location: Optional[str]) -> Optional[str]:
    parts = [p.strip() for p in (location or '').split('.')]
    if len(parts) != 3 or not all(parts):
        return None
    return metric_view_entity_id('.'.join(parts))


def _stored_measures(asset: AssetDb) -> List[Dict[str, Any]]:
    """The fingerprint records stored on an asset, recomputed from its spec if outdated."""
    stored = (asset.properties or {}).get(STORE_KEY)
    if not isinstance(stored, dict):
        return []
    if stored.get('fingerprint_version') == FINGERPRINT_VERSION and isinstance(
            stored.get('measures'), list):
        return [m for m in stored['measures'] if isinstance(m, dict) and m.get('name')]
    spec = stored.get('spec')
    return fingerprint_metric_view(spec) if isinstance(spec, dict) else []


def _name_keys(record: Dict[str, Any]) -> Set[str]:
    """The normalized name, display name and synonyms of a measure (term mapping helpers)."""
    names = [record.get('name'), record.get('display_name'), *(record.get('synonyms') or [])]
    return {depluralize(normalize(str(n))) for n in names if n and normalize(str(n))}


@dataclass
class _Measure:
    record: Dict[str, Any]
    view: str
    entity_id: str
    asset_id: Optional[str] = None
    asset_name: Optional[str] = None
    concepts: Set[str] = field(default_factory=set)

    @property
    def full(self) -> Optional[str]:
        digests = self.record.get('digests')
        return digests['full'] if digests else None

    def ref(self, readable: Readable) -> MeasureRef:
        return MeasureRef(
            asset_id=self.asset_id, asset_name=self.asset_name, view=self.view,
            name=self.record['name'], display_name=self.record.get('display_name'),
            entity_id=self.entity_id, concepts=sorted(self.concepts),
            readable=readable(self.view),
        )

    def definition(self) -> Optional[MeasureDefinition]:
        components = self.record.get('components')
        return MeasureDefinition(**components) if components else None


def _diffs(differences: List[Dict[str, Any]]) -> List[ComponentDiff]:
    return [ComponentDiff(**d) for d in differences]


class _CachedReadable:
    """``readable`` asked at most once per view."""

    def __init__(self, readable: Readable):
        self._readable = readable
        self._seen: Dict[str, bool] = {}

    def __call__(self, view: str) -> bool:
        if view not in self._seen:
            try:
                self._seen[view] = bool(self._readable(view))
            except Exception:
                logger.warning("Could not check access to metric view %s", view, exc_info=True)
                self._seen[view] = False
        return self._seen[view]


class MetricViewConsistencyManager:
    def __init__(self, db: Session, threshold: float = DEFAULT_SIMILARITY_THRESHOLD):
        self._db = db
        self._repo = metric_view_fingerprints_repo
        self._threshold = threshold

    # ------------------------------------------------------------------ index

    def _index(self) -> List[_Measure]:
        """Every stored measure of every Metric View asset, with its linked concepts."""
        measures: List[_Measure] = []
        for asset in self._repo.list_metric_view_assets(self._db):
            view = _view_fqn(asset.location)
            if view is None:
                continue
            for record in _stored_measures(asset):
                measures.append(_Measure(
                    record=record, view=view, entity_id=f"{view}.{record['name']}",
                    asset_id=str(asset.id), asset_name=asset.name,
                ))
        by_entity: Dict[str, List[_Measure]] = {}
        for m in measures:
            by_entity.setdefault(m.entity_id.lower(), []).append(m)
        for link in self._repo.list_column_links_for_entities(self._db, by_entity):
            for m in by_entity.get(link.entity_id.lower(), []):
                m.concepts.add(link.iri)
        return measures

    def _classify(self, a: _Measure, b: _Measure) -> Optional[Dict[str, Any]]:
        return classify(
            a.record, b.record,
            same_concept=bool(a.concepts & b.concepts),
            same_name=bool(_name_keys(a.record) & _name_keys(b.record)),
            a_linked=bool(a.concepts), b_linked=bool(b.concepts),
            threshold=self._threshold,
        )

    # ------------------------------------------------------------------ by asset

    def for_asset(self, asset_id: UUID, readable: Readable) -> MetricViewConsistency:
        """Per measure of the asset's metric view: the other measures it matches.

        Raises ``MetricViewAssetNotFoundError`` when the asset doesn't exist. An
        asset without stored fingerprints has no measures.
        """
        if asset_repo.get(self._db, id=asset_id) is None:
            raise MetricViewAssetNotFoundError(
                'The asset was not found.', assetId=str(asset_id),
            )
        readable = _CachedReadable(readable)
        index = self._index()
        own = [m for m in index if m.asset_id == str(asset_id)]
        result: List[MeasureConsistency] = []
        for m in own:
            matches: List[MeasureMatch] = []
            for other in index:
                if other is m:
                    continue
                verdict = self._classify(m, other)
                if verdict is None:
                    continue
                visible = readable(m.view) and readable(other.view)
                matches.append(MeasureMatch(
                    measure=other.ref(readable), verdict=verdict['verdict'],
                    first_level=verdict['first_level'], score=verdict['score'],
                    differences=_diffs(verdict['differences']) if visible else None,
                ))
            matches.sort(key=lambda x: (_VERDICT_ORDER[x.verdict], -(x.score or 0),
                                        x.measure.entity_id))
            result.append(MeasureConsistency(
                measure=m.ref(readable), error=m.record.get('error'),
                matches=matches[:MAX_MATCHES],
            ))
        return MetricViewConsistency(
            asset_id=str(asset_id), measures=result, threshold=self._threshold,
        )

    # ------------------------------------------------------------------ by concept

    def for_concept(self, iri: str, readable: Readable) -> MetricViewConsistency:
        """The measures linked to ``iri``, grouped by full fingerprint.

        Groups are ordered largest first; every other group is compared with
        the first (first differing level, similarity, component differences).
        ``verdict``: ``none`` without fingerprinted measures, ``consistent``
        with one group, ``conflict`` with more.
        """
        readable = _CachedReadable(readable)
        index = self._index()
        by_entity = {m.entity_id.lower(): m for m in index}
        views = {m.view for m in index}
        linked: List[_Measure] = []
        unresolved: List[MeasureRef] = []
        seen: Set[str] = set()
        for link in self._repo.list_column_links_for_iri(self._db, iri):
            key = link.entity_id.lower()
            if key in seen:
                continue
            seen.add(key)
            m = by_entity.get(key)
            if m is not None and m.full is not None:
                linked.append(m)
                continue
            if m is not None:
                unresolved.append(m.ref(readable))
                continue
            parts = link.entity_id.split('.')
            # Not a stored metric view measure (a table column, a dimension, ...): ids only
            if len(parts) >= 4 and _view_fqn('.'.join(parts[:3])) in views:
                view = metric_view_entity_id('.'.join(parts[:3]))
                unresolved.append(MeasureRef(
                    view=view, name='.'.join(parts[3:]), entity_id=link.entity_id,
                    concepts=[iri], readable=readable(view),
                ))

        groups: Dict[str, List[_Measure]] = {}
        for m in linked:
            groups.setdefault(m.full, []).append(m)
        ordered = sorted(groups.values(), key=lambda g: (-len(g), min(x.entity_id for x in g)))
        result: List[FingerprintGroup] = []
        reference: Optional[_Measure] = None
        reference_visible = False
        for members in ordered:
            members.sort(key=lambda x: x.entity_id)
            visible_member = next((x for x in members if readable(x.view)), None)
            other_concepts = sorted({
                c for x in index if x.full == members[0].full for c in x.concepts if c != iri
            })
            group = FingerprintGroup(
                full_digest=members[0].full,
                measures=[x.ref(readable) for x in members],
                definition=visible_member.definition() if visible_member else None,
                other_concepts=other_concepts,
            )
            if reference is None:
                reference, reference_visible = members[0], visible_member is not None
            else:
                sim = similarity(reference.record, members[0].record) or {}
                group.first_level = first_differing_level(reference.record, members[0].record)
                group.score = sim.get('score')
                if reference_visible and visible_member is not None:
                    group.differences = _diffs(sim.get('differences') or [])
            result.append(group)
        verdict = 'none' if not result else ('consistent' if len(result) == 1 else 'conflict')
        return MetricViewConsistency(
            concept_iri=iri, verdict=verdict, groups=result, unresolved=unresolved,
            threshold=self._threshold,
        )

    # ------------------------------------------------------------------ link check

    def check_link(self, entity_id: str, iri: str) -> LinkCheck:
        """The warnings linking the measure ``entity_id`` to ``iri`` would raise.

        - ``concept_has_other_definitions``: measures already linked to the
          concept compute something else (a ``conflict``);
        - ``definition_linked_to_other_concepts``: measures with the same
          definition are linked to other concepts (a ``link_conflict``).

        Non-blocking: the link is created anyway. Only Ontos-level metadata
        (measure and concept names) goes into the params. No warning for a
        field that isn't a stored, fingerprinted measure.
        """
        index = self._index()
        target = next((m for m in index if m.entity_id.lower() == entity_id.lower()), None)
        check = LinkCheck(entity_id=entity_id, iri=iri)
        if target is None or target.full is None:
            return check
        others = [m for m in index if m is not target and m.full is not None]
        differing = sorted(
            {f'{m.view}.{m.record["name"]}' for m in others
             if iri in m.concepts and m.full != target.full}
        )
        if differing:
            check.warnings.append(LinkWarning(
                code='concept_has_other_definitions',
                message='Measures already linked to this concept compute something else.',
                params={'count': len(differing), 'measures': differing[:MAX_WARNING_ITEMS]},
            ))
        concepts = sorted({
            c for m in others if m.full == target.full for c in m.concepts if c != iri
        })
        if concepts:
            check.warnings.append(LinkWarning(
                code='definition_linked_to_other_concepts',
                message='Measures with the same definition are linked to other concepts.',
                params={'count': len(concepts), 'concepts': concepts[:MAX_WARNING_ITEMS]},
            ))
        return check
