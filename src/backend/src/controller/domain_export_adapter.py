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

# Legacy round-trip key (still READ on import for backward compat with files exported
# before #851; no longer WRITTEN — superseded by the namespaced ontos* keys below).
ADDITIONAL_DOMAINS_PROPERTY = "additionalDomains"

# Reserved, namespaced round-trip keys (#851), emitted/read as ODCS/ODPS customProperties:
#   ontosDomainId       — list of all assigned Ontos domain UUIDs, primary first.
#                         Authoritative for rebind; re-derived from the live entity on export.
#   ontosOriginalDomain — list of the original domain string(s) from the source YAML
#                         (provenance). Preserved verbatim across round-trips.
# The standard single-value ``domain`` field still carries the primary domain NAME.
ONTOS_DOMAIN_ID_PROPERTY = "ontosDomainId"
ONTOS_ORIGINAL_DOMAIN_PROPERTY = "ontosOriginalDomain"

UC_DOMAIN_TAG = "data_domain"


def _is_uuid(value: Any) -> bool:
    import uuid as _uuid
    try:
        _uuid.UUID(str(value))
        return True
    except (ValueError, AttributeError, TypeError):
        return False


def _get_custom_property(odcs: Dict[str, Any], key: str) -> Optional[Any]:
    """Return the value of a customProperties entry by property name, or None."""
    for c in odcs.get("customProperties", []) or []:
        if isinstance(c, dict) and c.get("property") == key:
            return c.get("value")
    return None


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

    # customProperties entries this adapter manages on export (re-derived each time).
    _MANAGED_EXPORT_PROPERTIES = (ONTOS_DOMAIN_ID_PROPERTY,)

    def apply_odcs(self, odcs: Dict[str, Any], db: Session, entity_type: str, entity_id: str) -> Dict[str, Any]:
        """Apply domain fields onto an ODCS/ODPS dict in place (#851).

        * ``domain`` = primary domain name (ODCS standard single value).
        * ``customProperties`` gains ``ontosDomainId`` = list of all assigned domain UUIDs,
          primary first — the authoritative key for a lossless re-import rebind.

        ``ontosOriginalDomain`` (provenance) is a *stored* custom property carried through the
        export builder's own customProperties rebuild, so it is not re-derived here. The legacy
        top-level ``domainIds``/``primaryDomainId`` and ``customProperties.additionalDomains``
        are no longer emitted (superseded by ``ontosDomainId``).
        """
        assigned = self.get_assigned(db, entity_type, entity_id)
        if not assigned:
            return odcs
        primary, _additional = self.split_primary_additional(assigned)

        if primary and primary.domain_name:
            odcs["domain"] = primary.domain_name

        # ontosDomainId = all ids, primary first.
        ordered_ids = ([primary.domain_id] if primary else []) + [
            d.domain_id for d in assigned if not d.is_primary
        ]
        custom = [
            c for c in odcs.get("customProperties", []) or []
            if not (isinstance(c, dict) and c.get("property") == ONTOS_DOMAIN_ID_PROPERTY)
        ]
        custom.append({"property": ONTOS_DOMAIN_ID_PROPERTY, "value": ordered_ids})
        odcs["customProperties"] = custom
        return odcs

    def merge_custom_properties(
        self, rebuilt: List[Any], previous: Optional[List[Any]]
    ) -> List[Any]:
        """Re-attach the domain-managed customProperties entry (``ontosDomainId``) onto a
        freshly rebuilt customProperties list.

        Export builders that reconstruct ``customProperties`` from the entity's own stored
        properties would otherwise overwrite the ``ontosDomainId`` entry that
        :meth:`apply_odcs` injected, silently dropping the round-trip rebind key. Call this
        with the newly built list and the value ``apply_odcs`` had placed on the dict.
        (``ontosOriginalDomain`` is itself a stored property and rides along in ``rebuilt``.)
        """
        if not previous:
            return rebuilt
        preserved = [
            c for c in previous
            if isinstance(c, dict) and c.get("property") in self._MANAGED_EXPORT_PROPERTIES
        ]
        if not preserved:
            return rebuilt
        # Drop any stale managed entries the rebuilt list may carry, then re-attach.
        kept = [
            c for c in rebuilt
            if not (isinstance(c, dict) and c.get("property") in self._MANAGED_EXPORT_PROPERTIES)
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

    def parse_odcs(
        self,
        odcs: Dict[str, Any],
        db: Session,
        create_missing: bool = False,
        created_by: Optional[str] = None,
    ) -> Tuple[List[str], Optional[str]]:
        """Reconcile the source domain reference(s) to Ontos domain IDs (#851).

        Best-effort match, **ID first, then name**, in this priority:
          1. ``ontosDomainId`` custom property (the authoritative round-trip key).
          2. Legacy app keys ``domainIds``/``primaryDomainId`` or ``domainId``.
          3. ODCS-standard ``domain`` name (+ legacy ``customProperties.additionalDomains``).

        For name references, a value that is itself an existing domain UUID is matched by
        id first, then by unique name. On **no match** the reference is left unassigned
        (and captured as provenance by :meth:`extract_original_domain_strings`), unless
        ``create_missing`` is True — then a domain is auto-created by name and assigned.
        Returns ``(domain_ids, primary_domain_id)``.
        """
        # 1. Authoritative namespaced round-trip key.
        ontos_ids = _get_custom_property(odcs, ONTOS_DOMAIN_ID_PROPERTY)
        if isinstance(ontos_ids, list) and ontos_ids:
            ids, primary = self._filter_existing(db, [str(x) for x in ontos_ids], str(ontos_ids[0]))
            if ids:
                return ids, primary
            # else fall through — the recorded ids no longer exist; try other signals.

        # 2. Legacy app round-trip keys.
        raw_ids = odcs.get("domainIds")
        if isinstance(raw_ids, list) and raw_ids:
            ids, primary = self._filter_existing(
                db, [str(x) for x in raw_ids], odcs.get("primaryDomainId") or str(raw_ids[0])
            )
            if ids:
                return ids, primary

        single_id = odcs.get("domainId")
        if single_id and self.domain_repo.get(db, str(single_id)):
            return [str(single_id)], str(single_id)

        # 3. ODCS-standard name(s): primary `domain` + legacy additionalDomains.
        names: List[str] = []
        primary_name = odcs.get("domain")
        if primary_name:
            names.append(str(primary_name))
        legacy_additional = _get_custom_property(odcs, ADDITIONAL_DOMAINS_PROPERTY)
        if isinstance(legacy_additional, list):
            names.extend(str(v) for v in legacy_additional)

        resolved: List[str] = []
        for name in names:
            # ID-first: a free-form `domain` value might be an existing UUID.
            if _is_uuid(name) and self.domain_repo.get(db, name):
                if name not in resolved:
                    resolved.append(name)
                continue
            domain = self.domain_repo.get_by_name(db, name=name)
            if domain:
                if domain.id not in resolved:
                    resolved.append(domain.id)
            elif create_missing:
                created = self._create_domain(db, name, created_by)
                if created and created.id not in resolved:
                    resolved.append(created.id)
            else:
                logger.info(
                    "DomainExportAdapter: domain %r not found on import; left unassigned "
                    "(create_missing off). Original preserved as %s.",
                    name, ONTOS_ORIGINAL_DOMAIN_PROPERTY,
                )
        primary = resolved[0] if resolved else None
        return resolved, primary

    def extract_original_domain_strings(self, odcs: Dict[str, Any]) -> List[str]:
        """Return the original domain string(s) from the source for the ``ontosOriginalDomain``
        provenance custom property.

        Prefers an existing ``ontosOriginalDomain`` entry (preserves the true origin across
        repeated round-trips); otherwise falls back to the source ``domain`` name plus any
        legacy ``additionalDomains`` names. Returns an empty list when the source carries no
        domain string at all.
        """
        existing = _get_custom_property(odcs, ONTOS_ORIGINAL_DOMAIN_PROPERTY)
        if isinstance(existing, list) and existing:
            return [str(v) for v in existing]
        if isinstance(existing, str) and existing:
            return [existing]

        originals: List[str] = []
        primary_name = odcs.get("domain")
        if primary_name:
            originals.append(str(primary_name))
        legacy_additional = _get_custom_property(odcs, ADDITIONAL_DOMAINS_PROPERTY)
        if isinstance(legacy_additional, list):
            originals.extend(str(v) for v in legacy_additional)
        # De-dupe, preserve order.
        seen: set = set()
        return [x for x in originals if not (x in seen or seen.add(x))]

    def _create_domain(self, db: Session, name: str, created_by: Optional[str]):
        """Auto-create a domain by name during import (only when the caller opted in via the
        'Create missing domains' toggle). Returns the created domain or None on failure."""
        try:
            from src.models.data_domains import DataDomainCreate
            created = self.domain_repo.create(db=db, obj_in=DataDomainCreate(name=name))
            logger.info("DomainExportAdapter: auto-created missing domain %r (id=%s) on import.", name, created.id)
            return created
        except Exception as e:
            logger.warning("DomainExportAdapter: failed to auto-create domain %r on import: %s", name, e)
            return None

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
