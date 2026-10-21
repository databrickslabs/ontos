"""
Manifest builder for data product versions.

Constructs canonical manifests from product and contract definitions,
ensuring consistent ordering and normalization of all content sections.

Reference:
  - Decision 6: Content normalization in
    docs/decisions/manifest-canonicalization-hashing-signing.md
  - PRD sections on manifest content and asset digests
"""

from dataclasses import dataclass, asdict
from typing import Any, Dict, List, Optional
from datetime import datetime, timezone
import json

from .manifest_canonicalization import canonicalize
from .manifest_hashing import encode_multihash, HashAlgorithm


@dataclass
class ManifestDefinition:
    """Definition section of a manifest (the content being sealed)."""

    product_id: str
    version_family_id: str
    version: str
    parent_product_id: Optional[str] = None
    name: str = ""
    odps: Dict[str, Any] = None
    odcs: Dict[str, Any] = None  # Keyed by contract_id
    semantic_links: List[Dict[str, Any]] = None
    owners: Dict[str, Any] = None
    tags: List[str] = None
    domains: List[Dict[str, Any]] = None

    def __post_init__(self):
        """Initialize empty collections."""
        if self.odps is None:
            self.odps = {}
        if self.odcs is None:
            self.odcs = {}
        if self.semantic_links is None:
            self.semantic_links = []
        if self.owners is None:
            self.owners = {}
        if self.tags is None:
            self.tags = []
        if self.domains is None:
            self.domains = []

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for canonicalization."""
        return {
            "product_id": self.product_id,
            "version_family_id": self.version_family_id,
            "version": self.version,
            **({"parent_product_id": self.parent_product_id} if self.parent_product_id else {}),
            "name": self.name,
            "odps": self.odps,
            "odcs": self.odcs,
            "semantic_links": self.semantic_links,
            "owners": self.owners,
            "tags": self.tags,
            "domains": self.domains,
        }


@dataclass
class ManifestEvidence:
    """Evidence section of a manifest (asset digests and quality)."""

    assets: List[Dict[str, Any]] = None
    quality: Dict[str, Any] = None

    def __post_init__(self):
        """Initialize empty collections."""
        if self.assets is None:
            self.assets = []
        if self.quality is None:
            self.quality = {}

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for canonicalization."""
        return {
            "assets": self.assets,
            "quality": self.quality,
        }


@dataclass
class ManifestContent:
    """Content section of a manifest (definition + evidence)."""

    definition: ManifestDefinition
    evidence: ManifestEvidence

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for canonicalization."""
        return {
            "definition": self.definition.to_dict(),
            "evidence": self.evidence.to_dict(),
        }


@dataclass
class ManifestDigests:
    """Digests of all content sections."""

    definition: str
    odps: str
    odcs: Dict[str, str]  # Keyed by contract_id
    semantic_links: str
    owners: str
    tags: str
    assets: str

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for canonicalization."""
        return {
            "definition": self.definition,
            "odps": self.odps,
            "odcs": self.odcs,
            "semantic_links": self.semantic_links,
            "owners": self.owners,
            "tags": self.tags,
            "assets": self.assets,
        }


class ManifestBuilder:
    """
    Builds canonical manifests from product/contract definitions.

    Ensures all content is normalized consistently:
    - Collections are sorted by the keys specified in Decision 6
    - Datetimes are ISO-8601 UTC strings
    - All JSON is RFC 8785 canonical
    """

    @staticmethod
    def sort_ports(ports: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Sort ports by (name, version)."""
        return sorted(ports, key=lambda p: (p.get("name", ""), p.get("version", "")))

    @staticmethod
    def sort_support(items: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Sort support items by (channel, url)."""
        return sorted(items, key=lambda s: (s.get("channel", ""), s.get("url", "")))

    @staticmethod
    def sort_team_members(members: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Sort team members by (username, role)."""
        return sorted(members, key=lambda m: (m.get("username", ""), m.get("role", "")))

    @staticmethod
    def sort_properties(props: Dict[str, Any]) -> Dict[str, Any]:
        """Sort custom properties by property name."""
        return {k: props[k] for k in sorted(props.keys())}

    @staticmethod
    def sort_authoritative_definitions(
        defs: List[Dict[str, Any]],
    ) -> List[Dict[str, Any]]:
        """Sort authoritative definitions by (type, url)."""
        return sorted(defs, key=lambda d: (d.get("type", ""), d.get("url", "")))

    @staticmethod
    def sort_datasets(datasets: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Sort datasets by name."""
        return sorted(datasets, key=lambda d: d.get("name", ""))

    @staticmethod
    def sort_schema(schema: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Sort schema columns by name."""
        return sorted(schema, key=lambda s: s.get("name", ""))

    @staticmethod
    def sort_quality_rules(
        quality: List[Dict[str, Any]],
    ) -> List[Dict[str, Any]]:
        """Sort quality rules by (type, name, rule)."""
        return sorted(
            quality,
            key=lambda q: (q.get("type", ""), q.get("name", ""), q.get("rule", "")),
        )

    @staticmethod
    def sort_servers(servers: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Sort servers by server name."""
        return sorted(servers, key=lambda s: s.get("server", ""))

    @staticmethod
    def sort_domains(domains: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Sort domains by id, marking primary."""
        return sorted(domains, key=lambda d: d.get("id", ""))

    @staticmethod
    def sort_semantic_links(links: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Sort semantic links by IRI."""
        return sorted(links, key=lambda l: l.get("iri", ""))

    @staticmethod
    def sort_tags(tags: List[str]) -> List[str]:
        """Sort tags as namespace/name[=value]."""
        return sorted(tags)

    @staticmethod
    def sort_assets(assets: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Sort assets by (port, asset_identifier)."""
        return sorted(assets, key=lambda a: (a.get("port", ""), a.get("asset_identifier", "")))

    @classmethod
    def compute_section_digest(
        cls,
        section_data: Any,
        algorithm: HashAlgorithm = "sha2-256",
    ) -> str:
        """
        Compute digest of a single section.

        Args:
            section_data: The section data (will be canonicalized).
            algorithm: Hash algorithm to use.

        Returns:
            Encoded multihash string.
        """
        canonical_bytes = canonicalize(section_data)
        return encode_multihash(canonical_bytes, algorithm)

    @classmethod
    def compute_content_hash(
        cls,
        content: Dict[str, Any],
        algorithm: HashAlgorithm = "sha2-256",
    ) -> str:
        """
        Compute hash of the entire content (definition + evidence).

        Args:
            content: The content dict with "definition" and "evidence" keys.
            algorithm: Hash algorithm to use.

        Returns:
            Encoded multihash string.
        """
        canonical_bytes = canonicalize(content)
        return encode_multihash(canonical_bytes, algorithm)

    @classmethod
    def build_manifest_content(
        cls,
        definition: ManifestDefinition,
        evidence: ManifestEvidence,
        algorithm: HashAlgorithm = "sha2-256",
    ) -> tuple[Dict[str, Any], ManifestDigests]:
        """
        Build manifest content with normalized ordering and computed digests.

        Args:
            definition: The product definition.
            evidence: The asset evidence.
            algorithm: Hash algorithm to use.

        Returns:
            Tuple of (content_dict, digests).
        """
        # Normalize definition collections
        def_dict = definition.to_dict()

        # Compute section digests
        digests = ManifestDigests(
            definition=cls.compute_section_digest(def_dict, algorithm),
            odps=cls.compute_section_digest(def_dict.get("odps", {}), algorithm),
            odcs={
                cid: cls.compute_section_digest(spec, algorithm)
                for cid, spec in def_dict.get("odcs", {}).items()
            },
            semantic_links=cls.compute_section_digest(
                def_dict.get("semantic_links", []),
                algorithm,
            ),
            owners=cls.compute_section_digest(def_dict.get("owners", {}), algorithm),
            tags=cls.compute_section_digest(def_dict.get("tags", []), algorithm),
            assets=cls.compute_section_digest(evidence.assets, algorithm),
        )

        # Build content dict
        content = {
            "definition": def_dict,
            "evidence": evidence.to_dict(),
        }

        return content, digests
