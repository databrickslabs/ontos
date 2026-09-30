"""
Domain Sync Manager.

Syncs data domains between Ontos and Unity Catalog in both directions (#761):

- **Import** (UC -> Ontos): read UC's flat domain list, rebuild its two-level tree
  (root domains + subdomains via ``parent_domain_id``), and create/link matching
  Ontos domains — optionally under a chosen target root. Idempotent: matches by
  ``uc_domain_id`` first, then by name.
- **Export** (Ontos -> UC): from a configurable anchor, map the anchor's children
  to UC root domains and its grandchildren to UC subdomains; domains deeper than
  UC's two-level cap are skipped and reported. Matches by ``uc_domain_id`` first,
  then by name.

Both directions offer a dry-run preview that writes nothing.

Domains are low-cardinality (tens), so this runs synchronously in the request. If
accounts prove large, the async run pattern from the Schema Importer
(``schema_import_runs_manager``) can be layered on later.
"""

from typing import Dict, List, Optional
from uuid import UUID

from sqlalchemy.orm import Session

from src.common.logging import get_logger
from src.common.uc_domains_client import UcDomainsClient, UcDomain
from src.db_models.data_domains import DataDomain
from src.models.domain_sync import (
    DomainSyncNode,
    DomainSyncPreview,
    DomainSyncResult,
    SyncAction,
    SyncDirection,
)

logger = get_logger(__name__)


class DomainSyncManager:
    """Bidirectional Ontos <-> UC domain sync (synchronous, with dry-run preview)."""

    def __init__(self, uc_client: UcDomainsClient):
        self._uc = uc_client

    # ==================================================================
    # Shared helpers
    # ==================================================================

    def _load_ontos(self, db: Session) -> List[DataDomain]:
        """Load all Ontos domains (low cardinality) for in-memory tree building."""
        return db.query(DataDomain).all()

    @staticmethod
    def _children_map(domains: List[DataDomain]) -> Dict[Optional[str], List[DataDomain]]:
        """Group domains by parent_id (None key = top-level)."""
        out: Dict[Optional[str], List[DataDomain]] = {}
        for d in domains:
            out.setdefault(d.parent_id, []).append(d)
        for kids in out.values():
            kids.sort(key=lambda d: (d.name or "").lower())
        return out

    @staticmethod
    def _uc_trees(uc_domains: List[UcDomain]):
        """Return (roots, children_by_parent_id) for a flat UC domain list."""
        roots = [d for d in uc_domains if not d.parent_domain_id]
        children: Dict[str, List[UcDomain]] = {}
        for d in uc_domains:
            if d.parent_domain_id:
                children.setdefault(d.parent_domain_id, []).append(d)
        roots.sort(key=lambda d: (d.name or "").lower())
        for kids in children.values():
            kids.sort(key=lambda d: (d.name or "").lower())
        return roots, children

    # ==================================================================
    # Import: UC -> Ontos
    # ==================================================================

    def preview_import(self, db: Session, target_root_id: Optional[UUID]) -> DomainSyncPreview:
        return self._import(db, target_root_id, apply=False, user_id=None)

    def execute_import(self, db: Session, target_root_id: Optional[UUID], user_id: str) -> DomainSyncResult:
        preview = self._import(db, target_root_id, apply=True, user_id=user_id)
        return DomainSyncResult(
            direction=SyncDirection.IMPORT_FROM_UC,
            created=preview.to_create,
            matched=preview.to_match,
            skipped=preview.to_skip,
            errors=sum(1 for n in preview.nodes if n.action == SyncAction.ERROR),
            error_messages=[n.reason for n in preview.nodes if n.action == SyncAction.ERROR and n.reason],
            nodes=preview.nodes,
        )

    def _import(self, db: Session, target_root_id, apply: bool, user_id: Optional[str]) -> DomainSyncPreview:
        uc_domains = self._uc.list_domains()
        roots, uc_children = self._uc_trees(uc_domains)

        ontos = self._load_ontos(db)
        by_uc_id = {d.uc_domain_id: d for d in ontos if d.uc_domain_id}
        by_name = {(d.name or "").lower(): d for d in ontos}

        target_root_str = str(target_root_id) if target_root_id else None
        nodes: List[DomainSyncNode] = []
        warnings: List[str] = []

        def resolve(uc: UcDomain, parent_ontos: Optional[DataDomain], level: int) -> Optional[DataDomain]:
            """Match or create the Ontos domain for a UC domain. Returns the Ontos
            domain (or None on error/preview-create)."""
            existing = by_uc_id.get(uc.domain_id) or by_name.get((uc.name or "").lower())
            parent_id = parent_ontos.id if parent_ontos else target_root_str
            parent_name = parent_ontos.name if parent_ontos else None

            if existing is not None:
                node = DomainSyncNode(
                    name=uc.name, level=level, action=SyncAction.MATCH,
                    parent_name=parent_name, ontos_id=UUID(existing.id), uc_domain_id=uc.domain_id,
                )
                nodes.append(node)
                if apply and not existing.uc_domain_id:
                    existing.uc_domain_id = uc.domain_id  # backfill link
                    db.add(existing)
                return existing

            # create
            node = DomainSyncNode(
                name=uc.name, level=level, action=SyncAction.CREATE,
                parent_name=parent_name, uc_domain_id=uc.domain_id,
            )
            nodes.append(node)
            if not apply:
                return None
            created = DataDomain(
                name=uc.name,
                description=uc.description,
                parent_id=parent_id,
                uc_domain_id=uc.domain_id,
                created_by=user_id or "system",
            )
            db.add(created)
            db.flush()
            db.refresh(created)
            # keep lookup maps current so a re-used name later in the run matches
            by_name[(created.name or "").lower()] = created
            by_uc_id[uc.domain_id] = created
            node.ontos_id = UUID(created.id)
            return created

        for uc_root in roots:
            ontos_root = resolve(uc_root, None, 1)
            for uc_sub in uc_children.get(uc_root.domain_id, []):
                # In preview, ontos_root may be None (not yet created); parent shown by name.
                sub_parent = ontos_root
                if sub_parent is None and not apply:
                    # synthesize a name-only parent reference for preview readability
                    self._resolve_preview_sub(uc_sub, uc_root, by_uc_id, by_name, nodes)
                    continue
                resolve(uc_sub, sub_parent, 2)

        if apply:
            db.commit()

        return DomainSyncPreview(
            direction=SyncDirection.IMPORT_FROM_UC,
            nodes=nodes,
            to_create=sum(1 for n in nodes if n.action == SyncAction.CREATE),
            to_match=sum(1 for n in nodes if n.action == SyncAction.MATCH),
            to_skip=sum(1 for n in nodes if n.action == SyncAction.SKIP),
            warnings=warnings,
        )

    @staticmethod
    def _resolve_preview_sub(uc_sub, uc_root, by_uc_id, by_name, nodes):
        """Preview-only classification of a UC subdomain whose parent isn't created yet."""
        existing = by_uc_id.get(uc_sub.domain_id) or by_name.get((uc_sub.name or "").lower())
        action = SyncAction.MATCH if existing is not None else SyncAction.CREATE
        nodes.append(DomainSyncNode(
            name=uc_sub.name, level=2, action=action,
            parent_name=uc_root.name,
            ontos_id=UUID(existing.id) if existing is not None else None,
            uc_domain_id=uc_sub.domain_id,
        ))

    # ==================================================================
    # Export: Ontos -> UC
    # ==================================================================

    def preview_export(self, db: Session, anchor_domain_id: Optional[UUID]) -> DomainSyncPreview:
        return self._export(db, anchor_domain_id, apply=False)

    def execute_export(self, db: Session, anchor_domain_id: Optional[UUID], user_id: str) -> DomainSyncResult:
        preview = self._export(db, anchor_domain_id, apply=True)
        return DomainSyncResult(
            direction=SyncDirection.EXPORT_TO_UC,
            created=preview.to_create,
            matched=preview.to_match,
            skipped=preview.to_skip,
            errors=sum(1 for n in preview.nodes if n.action == SyncAction.ERROR),
            error_messages=[n.reason for n in preview.nodes if n.action == SyncAction.ERROR and n.reason],
            nodes=preview.nodes,
        )

    def _export(self, db: Session, anchor_domain_id, apply: bool) -> DomainSyncPreview:
        ontos = self._load_ontos(db)
        children_of = self._children_map(ontos)
        by_id = {d.id: d for d in ontos}

        anchor_str = str(anchor_domain_id) if anchor_domain_id else None
        if anchor_str and anchor_str not in by_id:
            raise ValueError(f"Anchor domain '{anchor_str}' not found")

        # Level-1 export set = children of the anchor (or top-level domains if no anchor).
        level1 = children_of.get(anchor_str, [])

        # Existing UC domains for idempotent matching.
        uc_domains = self._uc.list_domains()
        uc_by_id = {d.domain_id: d for d in uc_domains}
        uc_roots, uc_children = self._uc_trees(uc_domains)
        uc_root_by_name = {(d.name or "").lower(): d for d in uc_roots}

        nodes: List[DomainSyncNode] = []
        warnings: List[str] = []

        def flatten(dom: DataDomain, level: int):
            yield dom, level
            for child in children_of.get(dom.id, []):
                yield from flatten(child, level + 1)

        # Order: all level-1 first (so UC roots exist before subdomains on apply), then level-2.
        planned = []  # (dom, level)
        for l1 in level1:
            planned.extend(list(flatten(l1, 1)))
        planned.sort(key=lambda t: (t[1], (t[0].name or "").lower()))

        # Track UC parent id per Ontos level-1 domain for subdomain creation.
        uc_parent_for: Dict[str, Optional[str]] = {}

        for dom, level in planned:
            if level >= 3:
                nodes.append(DomainSyncNode(
                    name=dom.name, level=level, action=SyncAction.SKIP,
                    reason=f"UC supports only 2 levels; this domain is at depth {level} below the anchor.",
                ))
                warnings.append(f"Skipped '{dom.name}': deeper than UC's two-level limit.")
                continue

            parent_uc_id = None
            parent_name = None
            if level == 2:
                parent_uc_id = uc_parent_for.get(dom.parent_id)
                parent_name = by_id[dom.parent_id].name if dom.parent_id in by_id else None
                if parent_uc_id is None and apply:
                    # Parent wasn't created (e.g. errored/skipped) — cannot attach.
                    nodes.append(DomainSyncNode(
                        name=dom.name, level=2, action=SyncAction.ERROR,
                        reason="Parent UC domain unavailable; cannot create subdomain.",
                        parent_name=parent_name,
                    ))
                    continue

            # Match existing UC domain: by stored uc_domain_id, else by name at the right level.
            match = None
            if dom.uc_domain_id and dom.uc_domain_id in uc_by_id:
                match = uc_by_id[dom.uc_domain_id]
            elif level == 1:
                match = uc_root_by_name.get((dom.name or "").lower())
            elif level == 2 and parent_uc_id:
                for cand in uc_children.get(parent_uc_id, []):
                    if (cand.name or "").lower() == (dom.name or "").lower():
                        match = cand
                        break

            if match is not None:
                nodes.append(DomainSyncNode(
                    name=dom.name, level=level, action=SyncAction.MATCH,
                    parent_name=parent_name, ontos_id=UUID(dom.id), uc_domain_id=match.domain_id,
                ))
                if level == 1:
                    uc_parent_for[dom.id] = match.domain_id
                if apply and not dom.uc_domain_id:
                    dom.uc_domain_id = match.domain_id
                    db.add(dom)
                continue

            # create on UC
            node = DomainSyncNode(
                name=dom.name, level=level, action=SyncAction.CREATE,
                parent_name=parent_name, ontos_id=UUID(dom.id),
            )
            nodes.append(node)
            if not apply:
                if level == 1:
                    uc_parent_for[dom.id] = None  # unknown until applied
                continue
            try:
                created = self._uc.create_domain(
                    dom.name,
                    parent_domain_id=parent_uc_id if level == 2 else None,
                    description=dom.description,
                )
                node.uc_domain_id = created.domain_id
                dom.uc_domain_id = created.domain_id
                db.add(dom)
                if level == 1:
                    uc_parent_for[dom.id] = created.domain_id
            except Exception as exc:  # noqa: BLE001
                node.action = SyncAction.ERROR
                node.reason = str(exc)
                logger.error("Failed to create UC domain '%s': %s", dom.name, exc)

        if apply:
            db.commit()

        return DomainSyncPreview(
            direction=SyncDirection.EXPORT_TO_UC,
            nodes=nodes,
            to_create=sum(1 for n in nodes if n.action == SyncAction.CREATE),
            to_match=sum(1 for n in nodes if n.action == SyncAction.MATCH),
            to_skip=sum(1 for n in nodes if n.action == SyncAction.SKIP),
            warnings=warnings,
        )
