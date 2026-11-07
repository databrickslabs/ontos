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
from typing import Any, Dict, List, Optional, Sequence
from datetime import datetime, timezone
import copy
import json

from .manifest_canonicalization import (
    canonicalize,
    canonicalize_to_string,
    validate_canonical,
)
from .manifest_hashing import encode_multihash, HashAlgorithm


def _text_key(value: Any) -> bytes:
    """
    Sort key of one value: its UTF-16 code units, the order used for object keys.

    Missing and null sort like "". Non-string values (numbers, objects) sort by
    their canonical JSON text.
    """
    if value is None:
        return b""
    text = value if isinstance(value, str) else canonicalize_to_string(value)
    # surrogatepass: the order stays defined; canonicalize() rejects the string later
    return text.encode("utf-16-be", "surrogatepass")


def _sorted_by(items: Any, fields: Sequence[str]) -> Any:
    """
    Sort a list of objects by the given members (ADR, Decision 6).

    Elements equal on those members are ordered by their canonical JSON, so the
    result never depends on input order. Anything that isn't a list is returned
    unchanged.
    """
    if not isinstance(items, list):
        return items

    def key(item: Any) -> tuple:
        parts = tuple(
            _text_key(item.get(field) if isinstance(item, dict) else None)
            for field in fields
        )
        return parts + (_text_key(item),)

    return sorted(items, key=key)


# ODPS/ODCS members sorted wherever they appear (ADR, Decision 6). Their element
# values are opaque user data: the walk doesn't descend into them.
_CUSTOM_PROPERTIES = "customProperties"
_SORTED_EVERYWHERE: Dict[str, Sequence[str]] = {
    _CUSTOM_PROPERTIES: ("property",),
    "authoritativeDefinitions": ("type", "url"),
}
# ODCS only, at any depth of the schema tree: nested properties and quality rules
_ODCS_SORTED_EVERYWHERE: Dict[str, Sequence[str]] = {
    **_SORTED_EVERYWHERE,
    "properties": ("name",),
    "quality": ("type", "name", "rule"),
}
# Free-form members whose order is the author's (never walked or sorted)
_OPAQUE_KEYS = frozenset({"examples"})


def _normalize_nested(node: Any, rules: Dict[str, Sequence[str]]) -> Any:
    """
    Copy node with every list under a key of ``rules`` sorted, innermost first.

    Inner lists are sorted before the lists that contain them, so the order of
    an outer list never depends on the input order of an inner one. Lists under
    other keys keep their order (ADR, Decision 1: arrays are kept as given).
    """
    if isinstance(node, list):
        return [_normalize_nested(item, rules) for item in node]
    if not isinstance(node, dict):
        return node
    out: Dict[str, Any] = {}
    for key, value in node.items():
        if key in _OPAQUE_KEYS or key == _CUSTOM_PROPERTIES:
            value = copy.deepcopy(value)
        else:
            value = _normalize_nested(value, rules)
        if key in rules:
            value = _sorted_by(value, rules[key])
        out[key] = value
    return out


def _sort_members(team: Any) -> Any:
    """``team.members`` (ODPS, ODCS v3.1) or a bare member list (ODCS v3.0)."""
    if isinstance(team, list):
        return ManifestBuilder.sort_team_members(team)
    if isinstance(team, dict) and isinstance(team.get("members"), list):
        return {**team, "members": ManifestBuilder.sort_team_members(team["members"])}
    return team


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
        return _sorted_by(ports, ("name", "version"))

    @staticmethod
    def sort_support(items: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Sort support items by (channel, url)."""
        return _sorted_by(items, ("channel", "url"))

    @staticmethod
    def sort_team_members(members: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Sort team members by (username, role)."""
        return _sorted_by(members, ("username", "role"))

    @staticmethod
    def sort_properties(props: Any) -> Any:
        """
        Sort custom properties by property name.

        ODPS/ODCS ``customProperties`` is a list of ``{property, value}``; a dict
        (already keyed by name) is returned with its keys in order.
        """
        if isinstance(props, dict):
            return {k: props[k] for k in sorted(props.keys())}
        return _sorted_by(props, ("property",))

    @staticmethod
    def sort_authoritative_definitions(
        defs: List[Dict[str, Any]],
    ) -> List[Dict[str, Any]]:
        """Sort authoritative definitions by (type, url)."""
        return _sorted_by(defs, ("type", "url"))

    @staticmethod
    def sort_datasets(datasets: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Sort datasets (and their tables and views) by name."""
        return _sorted_by(datasets, ("name",))

    @staticmethod
    def sort_schema(schema: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Sort ODCS schema objects and properties by name."""
        return _sorted_by(schema, ("name",))

    @staticmethod
    def sort_quality_rules(
        quality: List[Dict[str, Any]],
    ) -> List[Dict[str, Any]]:
        """Sort quality rules by (type, name, rule)."""
        return _sorted_by(quality, ("type", "name", "rule"))

    @staticmethod
    def sort_servers(servers: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Sort servers by server name."""
        return _sorted_by(servers, ("server",))

    @staticmethod
    def sort_domains(domains: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Sort domains by id (each carries its primary flag)."""
        return _sorted_by(domains, ("id",))

    @staticmethod
    def sort_semantic_links(links: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Sort semantic links by IRI (then label)."""
        return _sorted_by(links, ("iri", "label"))

    @staticmethod
    def sort_tags(tags: List[str]) -> List[str]:
        """Sort tags rendered as namespace/name[=value]."""
        if not isinstance(tags, list):
            return tags
        return sorted(tags, key=_text_key)

    @staticmethod
    def sort_assets(assets: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """
        Sort assets by (port, asset_identifier).

        Only the list is sorted: members inside an asset (for example the
        physical schema columns, in position order) keep their order.
        """
        return _sorted_by(assets, ("port", "asset_identifier"))

    @classmethod
    def normalize_odps(cls, odps: Any) -> Any:
        """
        A copy of an ODPS export with the collections of Decision 6 sorted.

        ``inputPorts``/``outputPorts`` by (name, version), ``support`` by
        (channel, url), ``team.members`` by (username, role), ``datasets`` and
        their ``tables``/``views`` by name, and ``customProperties`` and
        ``authoritativeDefinitions`` at any depth. Other lists keep their order.
        """
        if not isinstance(odps, dict):
            return copy.deepcopy(odps)
        doc = _normalize_nested(odps, _SORTED_EVERYWHERE)
        for ports in ("inputPorts", "outputPorts"):
            if ports in doc:
                doc[ports] = cls.sort_ports(doc[ports])
        if "support" in doc:
            doc["support"] = cls.sort_support(doc["support"])
        if "team" in doc:
            doc["team"] = _sort_members(doc["team"])
        if isinstance(doc.get("datasets"), list):
            datasets = []
            for dataset in doc["datasets"]:
                if isinstance(dataset, dict):
                    dataset = {
                        k: cls.sort_datasets(v) if k in ("tables", "views") else v
                        for k, v in dataset.items()
                    }
                datasets.append(dataset)
            doc["datasets"] = cls.sort_datasets(datasets)
        return doc

    @classmethod
    def normalize_odcs(cls, odcs: Any) -> Any:
        """
        A copy of an ODCS export with the collections of Decision 6 sorted.

        ``schema`` and nested ``properties`` by name, ``quality`` by
        (type, name, rule) at any depth, ``servers`` by server, ``team`` members
        by (username, role), and ``customProperties`` and
        ``authoritativeDefinitions`` at any depth. Other lists keep their order.
        """
        if not isinstance(odcs, dict):
            return copy.deepcopy(odcs)
        doc = _normalize_nested(odcs, _ODCS_SORTED_EVERYWHERE)
        if "schema" in doc:
            doc["schema"] = cls.sort_schema(doc["schema"])
        if "servers" in doc:
            doc["servers"] = cls.sort_servers(doc["servers"])
        if "team" in doc:
            doc["team"] = _sort_members(doc["team"])
        return doc

    @classmethod
    def normalize_definition(cls, definition: Dict[str, Any]) -> Dict[str, Any]:
        """
        A copy of a definition dict with every order-insensitive collection sorted.

        ODPS and each ODCS as in normalize_odps/normalize_odcs, semantic links by
        IRI, owner members by (username, role), tags, and domains by id.
        """
        out = copy.deepcopy(definition)
        if "odps" in out:
            out["odps"] = cls.normalize_odps(out["odps"])
        if isinstance(out.get("odcs"), dict):
            out["odcs"] = {
                cid: cls.normalize_odcs(spec) for cid, spec in out["odcs"].items()
            }
        if "semantic_links" in out:
            out["semantic_links"] = cls.sort_semantic_links(out["semantic_links"])
        if "owners" in out:
            out["owners"] = _sort_members(out["owners"])
        if "tags" in out:
            out["tags"] = cls.sort_tags(out["tags"])
        if "domains" in out:
            out["domains"] = cls.sort_domains(out["domains"])
        return out

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

        The content is hashed as given, without sorting, as an independent
        verifier does; build_manifest_content produces it already normalized.

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
        # Reject what can't be canonicalized first, so errors name the input path
        raw_definition = definition.to_dict()
        validate_canonical(raw_definition, "$.definition")
        validate_canonical(evidence.assets, "$.evidence.assets")

        # Sort every order-insensitive collection (ADR, Decision 6), so the
        # database order of the inputs never changes the digests
        def_dict = cls.normalize_definition(raw_definition)
        evidence = ManifestEvidence(
            assets=cls.sort_assets(copy.deepcopy(evidence.assets)),
            quality=copy.deepcopy(evidence.quality),
        )

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
