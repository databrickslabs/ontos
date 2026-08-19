"""Helpers for representing Ontos data domains as Databricks governed tags.

Databricks Discover Domains are layered on governed tags. There is no public API
to create a Discover Domain *card* and no native "this tag is a domain" flag; the
programmatic contract is the tag key convention Discover reads:

- top-level domain:  ``{domain}``
- subdomain:         ``{parent}/{subdomain}``  (one level; Discover prefixes the parent)

These helpers are pure (no Databricks or DB imports) so both the cluster-side
tag-sync job and the app-side importer can share them and they stay unit-testable.

See docs/plans/nebw-domain-uc-sync.md.
"""
from __future__ import annotations

from typing import List, NamedTuple, Optional

# Governed tag key under which a domain assignment is written. Discover reads the
# tag *value* as the domain path; we use a stable key so reconcile can find it.
DOMAIN_TAG_KEY = "databricks_domain"

_SUBDOMAIN_SEP = "/"


def domain_tag_value(domain_name: str, parent_name: Optional[str] = None) -> str:
    """Build the governed-tag value for a domain / subdomain.

    Top-level -> ``domain``; subdomain -> ``parent/subdomain`` (Discover convention).
    """
    domain_name = (domain_name or "").strip()
    if not domain_name:
        raise ValueError("domain_name is required")
    if parent_name:
        parent_name = parent_name.strip()
        if parent_name:
            return f"{parent_name}{_SUBDOMAIN_SEP}{domain_name}"
    return domain_name


class ParsedDomainTag(NamedTuple):
    """A governed-tag value parsed back into a domain path."""
    parent_name: Optional[str]
    domain_name: str

    @property
    def is_subdomain(self) -> bool:
        return self.parent_name is not None


def parse_domain_tag_value(value: str) -> Optional[ParsedDomainTag]:
    """Parse a governed-tag value into ``(parent_name, domain_name)``.

    ``"Finance"`` -> ``(None, "Finance")``.
    ``"Finance/Payments"`` -> ``("Finance", "Payments")``.
    Deeper paths keep everything before the last separator as the parent name so a
    single level of hierarchy is honored while extra separators are not lost.
    Returns None for an empty/blank value.
    """
    if value is None:
        return None
    value = value.strip()
    if not value:
        return None
    if _SUBDOMAIN_SEP in value:
        parent, _, leaf = value.rpartition(_SUBDOMAIN_SEP)
        parent = parent.strip()
        leaf = leaf.strip()
        if leaf and parent:
            return ParsedDomainTag(parent_name=parent, domain_name=leaf)
        # Malformed (leading/trailing separator) — treat the whole thing as a name.
        return ParsedDomainTag(parent_name=None, domain_name=value.strip(_SUBDOMAIN_SEP))
    return ParsedDomainTag(parent_name=None, domain_name=value)


def domain_import_order(parsed_tags: List[ParsedDomainTag]) -> List[ParsedDomainTag]:
    """Order parsed tags so parents are created before their subdomains.

    Top-level domains first (stable within group), then subdomains. Ensures an
    auto-created parent exists before a subdomain that references it.
    """
    tops = [t for t in parsed_tags if not t.is_subdomain]
    subs = [t for t in parsed_tags if t.is_subdomain]
    return tops + subs
