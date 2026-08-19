"""Inbound import of Databricks governed-tag domains into Ontos DataDomains.

Reads domain governed tags discovered in Unity Catalog, computes which
``DataDomain`` rows would need to be created or updated (auto-creating missing
parents for subdomains), and routes the proposal through the Asset Review flow
for human approval before anything is written. Applying an approved import
creates the domains, honoring the parent-before-subdomain ordering.

Governed-tag key/value conventions live in ``src.common.governed_tags``.
See docs/plans/nebw-domain-uc-sync.md.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from sqlalchemy.orm import Session

from src.common.governed_tags import (
    ParsedDomainTag,
    parse_domain_tag_value,
    domain_import_order,
)
from src.common.logging import get_logger

logger = get_logger(__name__)


class DomainImportProposal:
    """A single proposed domain create/update derived from a UC governed tag."""
    def __init__(self, name: str, parent_name: Optional[str], action: str):
        self.name = name
        self.parent_name = parent_name
        self.action = action  # "create" | "exists"

    def to_dict(self) -> Dict[str, Any]:
        return {"name": self.name, "parent_name": self.parent_name, "action": self.action}


class DomainUcSyncManager:
    """Computes and applies inbound domain imports from UC governed tags."""

    def __init__(self, domains_manager, asset_reviews_manager=None):
        self._domains = domains_manager
        self._reviews = asset_reviews_manager

    # ------------------------------------------------------------------
    # Proposal computation
    # ------------------------------------------------------------------

    def compute_proposals(self, db: Session, tag_values: List[str]) -> List[DomainImportProposal]:
        """Turn raw governed-tag values into ordered create/exists proposals.

        Deduplicates tag values, orders parents before subdomains, and marks each
        domain that does not already exist (by name) as a "create". Missing parents
        of subdomains are inserted as their own "create" proposals.
        """
        parsed: List[ParsedDomainTag] = []
        seen_values = set()
        for value in tag_values:
            p = parse_domain_tag_value(value)
            if p is None:
                continue
            key = (p.parent_name, p.domain_name)
            if key in seen_values:
                continue
            seen_values.add(key)
            parsed.append(p)

        # Ensure a subdomain's parent has its own proposal even if UC only tagged
        # the subdomain path.
        existing_names = {(t.parent_name, t.domain_name) for t in parsed}
        for t in list(parsed):
            if t.is_subdomain and (None, t.parent_name) not in existing_names:
                parsed.append(ParsedDomainTag(parent_name=None, domain_name=t.parent_name))
                existing_names.add((None, t.parent_name))

        ordered = domain_import_order(parsed)

        proposals: List[DomainImportProposal] = []
        for t in ordered:
            exists = self._domains.repository.get_by_name(db, name=t.domain_name) is not None
            proposals.append(
                DomainImportProposal(
                    name=t.domain_name,
                    parent_name=t.parent_name,
                    action="exists" if exists else "create",
                )
            )
        return proposals

    # ------------------------------------------------------------------
    # Review gating
    # ------------------------------------------------------------------

    def create_import_review(
        self,
        db: Session,
        tag_values: List[str],
        reviewer_email: str,
        requester_email: str,
    ) -> Optional[str]:
        """Open an Asset Review proposing the domain imports. Returns review id.

        Returns None when there is nothing to create or no reviews manager is wired.
        """
        proposals = self.compute_proposals(db, tag_values)
        to_create = [p for p in proposals if p.action == "create"]
        if not to_create:
            logger.info("No new domains to import from UC governed tags")
            return None
        if self._reviews is None:
            logger.warning("No asset_reviews_manager configured; cannot open domain import review")
            return None

        from src.models.data_asset_reviews import DataAssetReviewRequestCreate

        lines = ["Proposed domain imports from Unity Catalog governed tags:"]
        for p in to_create:
            if p.parent_name:
                lines.append(f"  - subdomain '{p.name}' under '{p.parent_name}'")
            else:
                lines.append(f"  - domain '{p.name}'")

        # Use a stable synthetic FQN so the review is about the import batch.
        fqn = "domain-import://unity-catalog"
        request = DataAssetReviewRequestCreate(
            requester_email=requester_email,
            reviewer_email=reviewer_email,
            asset_fqns=[fqn],
            title=f"Import {len(to_create)} domain(s) from Unity Catalog",
            notes="\n".join(lines),
        )
        created = self._reviews.create_review_request(request, db=db)
        return getattr(created, "id", None)

    # ------------------------------------------------------------------
    # Apply (on approval)
    # ------------------------------------------------------------------

    def apply_import(
        self,
        db: Session,
        tag_values: List[str],
        current_user: str,
    ) -> Dict[str, Any]:
        """Create the proposed domains (parents before subdomains).

        Idempotent: domains that already exist by name are skipped. Subdomains are
        linked to their parent (auto-created earlier in the ordering). Returns a
        summary of created and skipped names.
        """
        from src.models.data_domains import DataDomainCreate

        proposals = self.compute_proposals(db, tag_values)
        created: List[str] = []
        skipped: List[str] = []
        for p in proposals:
            existing = self._domains.repository.get_by_name(db, name=p.name)
            if existing:
                skipped.append(p.name)
                continue
            parent_id = None
            if p.parent_name:
                parent = self._domains.repository.get_by_name(db, name=p.parent_name)
                if parent:
                    parent_id = parent.id
                else:
                    # Parent should have been created earlier in the ordering; if
                    # not, skip the subdomain rather than orphan it.
                    logger.warning("Parent domain '%s' missing for subdomain '%s'; skipping", p.parent_name, p.name)
                    skipped.append(p.name)
                    continue
            domain_in = DataDomainCreate(name=p.name, parent_id=parent_id)
            self._domains.create_domain_internal(
                db, domain_in, current_user_id=current_user, perform_commit=False
            )
            created.append(p.name)
        db.flush()
        return {"created": created, "skipped": skipped}
