"""DomainExportAdapter — single place for domain export/import conventions.

Single-value integrations (ODCS/ODPS ``domain`` field, Unity Catalog ``data_domain`` tag)
consume the *primary* domain as their canonical value; *additional* domains are emitted
through extension fields (``customProperties.additionalDomains`` for ODCS/ODPS, numbered
``data_domain_1`` / ``data_domain_2`` / ... tags for UC — a securable holds one value per
tag key, so additional domains cannot share a single key). This adapter centralises those
conventions so both the export and import code paths stay consistent and testable.
"""
from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy.orm import Session

from src.common.logging import get_logger
from src.models.domain_associations import AssignedDomain
from src.repositories.data_domain_repository import data_domain_repo
from src.repositories.entity_domain_association_repository import entity_domain_repo

logger = get_logger(__name__)

ADDITIONAL_DOMAINS_PROPERTY = "additionalDomains"
UC_DOMAIN_TAG = "data_domain"


class DomainExportAdapter:
    def __init__(self, repo=entity_domain_repo, domain_repo=data_domain_repo):
        self.repo = repo
        self.domain_repo = domain_repo

    # ------------------------------------------------------------------ reads

    def get_assigned(self, db: Session, entity_type: str, entity_id: str) -> List[AssignedDomain]:
        return self.repo.get_domains_for_entity(db, entity_type=entity_type, entity_id=entity_id)

    def split_primary_additional(
        self, assigned: List[AssignedDomain]
    ) -> Tuple[Optional[AssignedDomain], List[AssignedDomain]]:
        primary = next((d for d in assigned if d.is_primary), None)
        additional = [d for d in assigned if not d.is_primary]
        return primary, additional

    # ---------------------------------------------------------------- exports

    def apply_odcs(self, odcs: Dict[str, Any], db: Session, entity_type: str, entity_id: str) -> Dict[str, Any]:
        """Apply domain fields onto an ODCS/ODPS dict in place.

        * ``domain`` = primary domain name (ODCS standard single value).
        * ``customProperties`` gains ``additionalDomains`` = list of additional domain names.
        * App round-trip helpers ``domainIds`` (all ids, primary first) and ``primaryDomainId``
          are also included so the UI and re-import preserve the full assignment.
        """
        assigned = self.get_assigned(db, entity_type, entity_id)
        if not assigned:
            return odcs
        primary, additional = self.split_primary_additional(assigned)

        if primary and primary.domain_name:
            odcs["domain"] = primary.domain_name
        odcs["domainIds"] = [d.domain_id for d in assigned]
        odcs["primaryDomainId"] = primary.domain_id if primary else None

        if additional:
            names = [d.domain_name for d in additional if d.domain_name]
            if names:
                custom = odcs.setdefault("customProperties", [])
                # Drop any stale additionalDomains entry, then append the current one.
                custom = [c for c in custom if not (isinstance(c, dict) and c.get("property") == ADDITIONAL_DOMAINS_PROPERTY)]
                custom.append({"property": ADDITIONAL_DOMAINS_PROPERTY, "value": names})
                odcs["customProperties"] = custom
        return odcs

    def merge_custom_properties(
        self, rebuilt: List[Any], previous: Optional[List[Any]]
    ) -> List[Any]:
        """Re-attach the domain-managed customProperties entries (``additionalDomains``)
        onto a freshly rebuilt customProperties list.

        Export builders that reconstruct ``customProperties`` from the entity's own stored
        properties would otherwise overwrite the ``additionalDomains`` entry that
        :meth:`apply_odcs` injected, silently dropping additional domains on export (and
        thus on ODCS/ODPS round-trip). Call this with the newly built list and the value
        ``apply_odcs`` had placed on the dict to preserve that entry.
        """
        if not previous:
            return rebuilt
        preserved = [
            c for c in previous
            if isinstance(c, dict) and c.get("property") == ADDITIONAL_DOMAINS_PROPERTY
        ]
        if not preserved:
            return rebuilt
        # Drop any stale additionalDomains the rebuilt list may carry, then re-attach.
        kept = [
            c for c in rebuilt
            if not (isinstance(c, dict) and c.get("property") == ADDITIONAL_DOMAINS_PROPERTY)
        ]
        return kept + preserved

    def uc_tags(self, db: Session, entity_type: str, entity_id: str) -> List[Tuple[str, str]]:
        """Return the Unity Catalog (tag_key, tag_value) pairs for an entity's domains:
        the primary as ``data_domain`` first, then one tag per additional domain.

        A UC securable holds one value per tag key, so additional domains cannot share
        a single ``data_domain_additional`` key — each gets its own numbered key derived
        from the primary key (``data_domain_1``, ``data_domain_2``, ...), matching the
        uc_tag_sync workflow. Names are sorted for deterministic key assignment."""
        assigned = self.get_assigned(db, entity_type, entity_id)
        primary, additional = self.split_primary_additional(assigned)
        tags: List[Tuple[str, str]] = []
        if primary and primary.domain_name:
            tags.append((UC_DOMAIN_TAG, primary.domain_name))
        additional_names = sorted(d.domain_name for d in additional if d.domain_name)
        for idx, name in enumerate(additional_names, start=1):
            tags.append((f"{UC_DOMAIN_TAG}_{idx}", name))
        return tags

    # ---------------------------------------------------------------- imports

    def parse_odcs(self, odcs: Dict[str, Any], db: Session) -> Tuple[List[str], Optional[str]]:
        """Extract (domain_ids, primary_domain_id) from an ODCS/ODPS dict.

        Prefers the app round-trip keys (``domainIds``/``primaryDomainId`` or ``domainId``),
        then falls back to the ODCS-standard ``domain`` name + ``customProperties.additionalDomains``.
        Names are resolved to IDs; unresolved names are skipped with a warning.
        """
        # 1. App round-trip keys.
        domain_ids: List[str] = []
        primary_domain_id: Optional[str] = None

        raw_ids = odcs.get("domainIds")
        if isinstance(raw_ids, list) and raw_ids:
            domain_ids = [str(x) for x in raw_ids]
            primary_domain_id = odcs.get("primaryDomainId") or (domain_ids[0] if domain_ids else None)
            return self._filter_existing(db, domain_ids, primary_domain_id)

        single_id = odcs.get("domainId")
        if single_id:
            return self._filter_existing(db, [str(single_id)], str(single_id))

        # 2. ODCS-standard: primary name + additionalDomains names.
        names: List[str] = []
        primary_name = odcs.get("domain")
        if primary_name:
            names.append(primary_name)
        for c in odcs.get("customProperties", []) or []:
            if isinstance(c, dict) and c.get("property") == ADDITIONAL_DOMAINS_PROPERTY:
                value = c.get("value") or []
                if isinstance(value, list):
                    names.extend(str(v) for v in value)

        resolved: List[str] = []
        for name in names:
            domain = self.domain_repo.get_by_name(db, name=name)
            if domain:
                resolved.append(domain.id)
            else:
                logger.warning("DomainExportAdapter: could not resolve domain name %r on import; skipped.", name)
        primary = resolved[0] if resolved else None
        return resolved, primary

    def _filter_existing(self, db: Session, domain_ids: List[str], primary: Optional[str]) -> Tuple[List[str], Optional[str]]:
        existing = []
        for did in domain_ids:
            if self.domain_repo.get(db, did):
                existing.append(did)
            else:
                logger.warning("DomainExportAdapter: domain id %r not found on import; skipped.", did)
        if primary not in existing:
            primary = existing[0] if existing else None
        return existing, primary


# Module-level singleton
domain_export_adapter = DomainExportAdapter()
