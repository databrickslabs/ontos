"""
Unity Catalog Domains client.

A thin, testable wrapper over the Databricks SDK's ``w.domains`` (``DomainsAPI``,
UC Discovery/Business Domains) so managers don't touch the SDK directly and unit
tests can mock a single seam.

Key UC facts this wrapper encodes (see the SDK 0.137 surface):
- Domains are **account-scoped** and require the ``MANAGE DISCOVERY`` permission.
- ``list_domains`` returns a flat list; hierarchy is expressed via
  ``parent_domain_id``. UC caps nesting at **two levels** (root domains + one
  layer of subdomains — subdomains cannot nest further).
- ``Domain.tag_key`` is **required** on create; it is the tag key UC uses to mark
  securable membership in the domain. We default it to a slug of the name.
"""

import re
from dataclasses import dataclass
from typing import List, Optional

from src.common.logging import get_logger

logger = get_logger(__name__)


class DomainPermissionError(PermissionError):
    """Raised when the caller lacks MANAGE DISCOVERY for UC domains."""


@dataclass
class UcDomain:
    """A UC domain, decoupled from the SDK's ``Domain`` type."""
    domain_id: Optional[str]
    name: str
    tag_key: Optional[str] = None
    description: Optional[str] = None
    parent_domain_id: Optional[str] = None

    @property
    def is_subdomain(self) -> bool:
        return bool(self.parent_domain_id)


def slugify_tag_key(name: str) -> str:
    """Derive a UC tag key from a domain name.

    UC requires a ``tag_key`` on every domain. We produce a stable, lowercase,
    underscore-separated key from the name (e.g. "Sales & Marketing" ->
    "sales_marketing"). Falls back to "domain" if the name has no usable chars.
    """
    key = re.sub(r"[^0-9a-zA-Z]+", "_", (name or "").strip().lower()).strip("_")
    return key or "domain"


def _to_uc_domain(sdk_domain) -> UcDomain:
    return UcDomain(
        domain_id=getattr(sdk_domain, "domain_id", None),
        name=getattr(sdk_domain, "name", None) or "",
        tag_key=getattr(sdk_domain, "tag_key", None),
        description=getattr(sdk_domain, "description", None),
        parent_domain_id=getattr(sdk_domain, "parent_domain_id", None),
    )


class UcDomainsClient:
    """Wrapper over ``workspace_client.domains``.

    Construct with a live ``WorkspaceClient``; all calls translate SDK errors and
    types into this module's plain shapes so callers stay SDK-agnostic.
    """

    def __init__(self, workspace_client):
        if workspace_client is None:
            raise ValueError("UcDomainsClient requires a workspace client")
        self._ws = workspace_client

    # ------------------------------------------------------------------
    # Reads
    # ------------------------------------------------------------------

    def list_domains(self) -> List[UcDomain]:
        """Return all UC domains (flat). Callers rebuild the 2-level tree from
        ``parent_domain_id``."""
        try:
            return [_to_uc_domain(d) for d in self._ws.domains.list_domains()]
        except Exception as exc:  # noqa: BLE001 - re-raised as typed below
            raise self._translate(exc)

    # ------------------------------------------------------------------
    # Writes
    # ------------------------------------------------------------------

    def create_domain(
        self,
        name: str,
        *,
        parent_domain_id: Optional[str] = None,
        description: Optional[str] = None,
        tag_key: Optional[str] = None,
    ) -> UcDomain:
        """Create a UC domain (or subdomain when ``parent_domain_id`` is set)."""
        from databricks.sdk.service.domains import Domain

        domain = Domain(
            name=name,
            tag_key=tag_key or slugify_tag_key(name),
            description=description,
            parent_domain_id=parent_domain_id,
        )
        try:
            created = self._ws.domains.create_domain(domain=domain)
            return _to_uc_domain(created)
        except Exception as exc:  # noqa: BLE001
            raise self._translate(exc)

    def update_domain(
        self,
        domain_id: str,
        *,
        name: Optional[str] = None,
        description: Optional[str] = None,
    ) -> UcDomain:
        """Update the name/description of an existing UC domain.

        Only the provided fields are sent (via an explicit ``update_mask``).
        Reparenting is intentionally NOT supported here — UC's 2-level model
        makes moving a domain between root/subdomain error-prone, so callers
        create/delete to restructure instead.
        """
        from databricks.sdk.service.domains import Domain, FieldMask

        paths = []
        if name is not None:
            paths.append("name")
        if description is not None:
            paths.append("description")
        if not paths:
            # Nothing to update; return current state.
            return self.get_domain(domain_id)

        # Domain() requires tag_key even though we don't change it; carry the
        # current value so construction succeeds and the server keeps it.
        current = self.get_domain(domain_id)
        domain = Domain(tag_key=current.tag_key, name=name, description=description)
        # update_mask is the SDK's FieldMask wrapper (the API calls .ToJsonString());
        # build it from a comma-separated field list.
        mask = FieldMask()
        mask.FromJsonString(",".join(paths))
        try:
            updated = self._ws.domains.update_domain(
                name=f"domains/{domain_id}",
                domain=domain,
                update_mask=mask,
            )
            return _to_uc_domain(updated)
        except Exception as exc:  # noqa: BLE001
            raise self._translate(exc)

    def get_domain(self, domain_id: str) -> UcDomain:
        try:
            return _to_uc_domain(self._ws.domains.get_domain(name=f"domains/{domain_id}"))
        except Exception as exc:  # noqa: BLE001
            raise self._translate(exc)

    # ------------------------------------------------------------------
    # Error translation
    # ------------------------------------------------------------------

    @staticmethod
    def _translate(exc: Exception) -> Exception:
        """Map SDK errors to friendlier types. PermissionDenied → DomainPermissionError."""
        name = type(exc).__name__
        msg = str(exc)
        if name == "PermissionDenied" or "not authorized" in msg.lower():
            return DomainPermissionError(
                "Access to Unity Catalog domains was denied. The caller needs the "
                "MANAGE DISCOVERY permission (UC domains are account-scoped)."
            )
        return exc
