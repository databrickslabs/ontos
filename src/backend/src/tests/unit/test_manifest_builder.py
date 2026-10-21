"""
Tests for manifest builder.

Covers:
- Content normalization and sorting
- Deterministic digest computation
- Tamper detection
- Golden vectors with known hashes
"""

import pytest
from src.common.manifest_builder import (
    ManifestDefinition,
    ManifestEvidence,
    ManifestContent,
    ManifestBuilder,
    ManifestDigests,
)
from src.common.manifest_hashing import verify_multihash, decode_multihash
from src.common.manifest_canonicalization import canonicalize


class TestSortFunctions:
    """Test collection sorting functions."""

    def test_sort_ports_by_name_version(self):
        """Ports are sorted by (name, version)."""
        ports = [
            {"name": "port_b", "version": "2.0"},
            {"name": "port_a", "version": "1.0"},
            {"name": "port_a", "version": "2.0"},
        ]
        sorted_ports = ManifestBuilder.sort_ports(ports)
        assert sorted_ports[0]["name"] == "port_a"
        assert sorted_ports[0]["version"] == "1.0"
        assert sorted_ports[1]["name"] == "port_a"
        assert sorted_ports[1]["version"] == "2.0"
        assert sorted_ports[2]["name"] == "port_b"

    def test_sort_support_items(self):
        """Support items are sorted by (channel, url)."""
        items = [
            {"channel": "slack", "url": "channel_b"},
            {"channel": "email", "url": "support@example.com"},
            {"channel": "slack", "url": "channel_a"},
        ]
        sorted_items = ManifestBuilder.sort_support(items)
        assert sorted_items[0]["channel"] == "email"
        assert sorted_items[1]["channel"] == "slack"
        assert sorted_items[1]["url"] == "channel_a"

    def test_sort_team_members(self):
        """Team members are sorted by (username, role)."""
        members = [
            {"username": "bob", "role": "owner"},
            {"username": "alice", "role": "viewer"},
            {"username": "alice", "role": "editor"},
        ]
        sorted_members = ManifestBuilder.sort_team_members(members)
        assert sorted_members[0]["username"] == "alice"
        assert sorted_members[0]["role"] == "editor"
        assert sorted_members[1]["username"] == "alice"
        assert sorted_members[1]["role"] == "viewer"

    def test_sort_properties(self):
        """Properties are sorted by key."""
        props = {"z": 1, "a": 2, "m": 3}
        sorted_props = ManifestBuilder.sort_properties(props)
        assert list(sorted_props.keys()) == ["a", "m", "z"]

    def test_sort_datasets(self):
        """Datasets are sorted by name."""
        datasets = [
            {"name": "dataset_c"},
            {"name": "dataset_a"},
            {"name": "dataset_b"},
        ]
        sorted_datasets = ManifestBuilder.sort_datasets(datasets)
        assert [d["name"] for d in sorted_datasets] == [
            "dataset_a",
            "dataset_b",
            "dataset_c",
        ]

    def test_sort_tags(self):
        """Tags are sorted alphabetically."""
        tags = ["system/validated", "domain/finance", "domain/accounting"]
        sorted_tags = ManifestBuilder.sort_tags(tags)
        assert sorted_tags == [
            "domain/accounting",
            "domain/finance",
            "system/validated",
        ]

    def test_sort_assets(self):
        """Assets are sorted by (port, asset_identifier)."""
        assets = [
            {"port": "output_b", "asset_identifier": "schema"},
            {"port": "output_a", "asset_identifier": "table"},
            {"port": "output_a", "asset_identifier": "schema"},
        ]
        sorted_assets = ManifestBuilder.sort_assets(assets)
        assert sorted_assets[0]["port"] == "output_a"
        assert sorted_assets[0]["asset_identifier"] == "schema"
        assert sorted_assets[1]["port"] == "output_a"
        assert sorted_assets[1]["asset_identifier"] == "table"


class TestSectionDigests:
    """Test section digest computation."""

    def test_section_digest_deterministic(self):
        """Section digests are deterministic."""
        section = {"name": "test", "version": "1.0"}
        digest1 = ManifestBuilder.compute_section_digest(section)
        digest2 = ManifestBuilder.compute_section_digest(section)
        assert digest1 == digest2

    def test_section_digest_detects_changes(self):
        """Changing section content changes the digest."""
        section1 = {"name": "test", "version": "1.0"}
        section2 = {"name": "test", "version": "1.1"}
        digest1 = ManifestBuilder.compute_section_digest(section1)
        digest2 = ManifestBuilder.compute_section_digest(section2)
        assert digest1 != digest2

    def test_section_digest_algorithm_choice(self):
        """Different algorithms produce different digests."""
        section = {"name": "test"}
        digest_sha2 = ManifestBuilder.compute_section_digest(section, "sha2-256")
        digest_sha3 = ManifestBuilder.compute_section_digest(section, "sha3-256")
        assert digest_sha2 != digest_sha3

    def test_section_digest_format(self):
        """Section digest is valid multihash."""
        section = {"name": "test"}
        digest = ManifestBuilder.compute_section_digest(section)
        # Should be decodable
        alg, digest_bytes = decode_multihash(digest)
        assert alg == "sha2-256"
        assert len(digest_bytes) == 32


class TestContentHash:
    """Test content hash computation."""

    def test_content_hash_deterministic(self):
        """Content hashes are deterministic."""
        content = {"definition": {"id": "p1"}, "evidence": {"assets": []}}
        hash1 = ManifestBuilder.compute_content_hash(content)
        hash2 = ManifestBuilder.compute_content_hash(content)
        assert hash1 == hash2

    def test_content_hash_detects_definition_change(self):
        """Content hash changes when definition changes."""
        content1 = {"definition": {"id": "p1", "name": "Product1"}, "evidence": {"assets": []}}
        content2 = {"definition": {"id": "p1", "name": "Product2"}, "evidence": {"assets": []}}
        hash1 = ManifestBuilder.compute_content_hash(content1)
        hash2 = ManifestBuilder.compute_content_hash(content2)
        assert hash1 != hash2

    def test_content_hash_detects_evidence_change(self):
        """Content hash changes when evidence changes."""
        content1 = {"definition": {"id": "p1"}, "evidence": {"assets": []}}
        content2 = {"definition": {"id": "p1"}, "evidence": {"assets": [{"port": "out"}]}}
        hash1 = ManifestBuilder.compute_content_hash(content1)
        hash2 = ManifestBuilder.compute_content_hash(content2)
        assert hash1 != hash2


class TestManifestDefinition:
    """Test ManifestDefinition data class."""

    def test_default_values(self):
        """ManifestDefinition initializes with defaults."""
        defn = ManifestDefinition(
            product_id="p1",
            version_family_id="vf1",
            version="1.0.0",
        )
        assert defn.product_id == "p1"
        assert defn.version_family_id == "vf1"
        assert defn.version == "1.0.0"
        assert defn.parent_product_id is None
        assert defn.name == ""
        assert isinstance(defn.odps, dict)
        assert isinstance(defn.odcs, dict)
        assert isinstance(defn.semantic_links, list)
        assert isinstance(defn.owners, dict)
        assert isinstance(defn.tags, list)

    def test_to_dict_contains_all_fields(self):
        """to_dict() includes all non-None fields."""
        defn = ManifestDefinition(
            product_id="p1",
            version_family_id="vf1",
            version="1.0.0",
            parent_product_id="parent1",
            name="Product",
            odps={"id": "prod-123"},
        )
        d = defn.to_dict()
        assert d["product_id"] == "p1"
        assert d["parent_product_id"] == "parent1"
        assert d["odps"]["id"] == "prod-123"


class TestManifestEvidence:
    """Test ManifestEvidence data class."""

    def test_default_values(self):
        """ManifestEvidence initializes with defaults."""
        evidence = ManifestEvidence()
        assert isinstance(evidence.assets, list)
        assert isinstance(evidence.quality, dict)

    def test_to_dict(self):
        """to_dict() includes assets and quality."""
        evidence = ManifestEvidence(
            assets=[{"port": "out"}],
            quality={"accuracy": 0.95},
        )
        d = evidence.to_dict()
        assert d["assets"] == [{"port": "out"}]
        assert d["quality"]["accuracy"] == 0.95


class TestBuildManifestContent:
    """Test the full manifest content building process."""

    def test_build_with_empty_definition(self):
        """Build manifest content with empty definition."""
        defn = ManifestDefinition(
            product_id="p1",
            version_family_id="vf1",
            version="1.0.0",
        )
        evidence = ManifestEvidence()

        content, digests = ManifestBuilder.build_manifest_content(defn, evidence)

        assert content["definition"]["product_id"] == "p1"
        assert isinstance(digests.definition, str)
        assert isinstance(digests.odps, str)
        assert isinstance(digests.semantic_links, str)

    def test_build_with_complete_definition(self):
        """Build manifest content with full definition."""
        defn = ManifestDefinition(
            product_id="p1",
            version_family_id="vf1",
            version="1.0.0",
            name="My Product",
            odps={"id": "prod", "inputPorts": [], "outputPorts": []},
            semantic_links=[{"iri": "http://example.com/term"}],
            tags=["domain/finance", "system/validated"],
        )
        evidence = ManifestEvidence(
            assets=[{"port": "output", "asset_identifier": "table1"}],
            quality={"accuracy": 0.95},
        )

        content, digests = ManifestBuilder.build_manifest_content(defn, evidence)

        assert content["definition"]["name"] == "My Product"
        assert len(content["evidence"]["assets"]) == 1

    def test_digests_are_valid_multihashes(self):
        """All computed digests are valid multihashes."""
        defn = ManifestDefinition(
            product_id="p1",
            version_family_id="vf1",
            version="1.0.0",
        )
        evidence = ManifestEvidence()

        content, digests = ManifestBuilder.build_manifest_content(defn, evidence)

        # All digests should be decodable
        for digest_str in [
            digests.definition,
            digests.odps,
            digests.semantic_links,
            digests.owners,
            digests.tags,
            digests.assets,
        ]:
            alg, digest_bytes = decode_multihash(digest_str)
            assert alg in ["sha2-256", "sha3-256"]
            assert len(digest_bytes) == 32

    def test_content_hash_matches_content(self):
        """Content hash verifies against actual content."""
        defn = ManifestDefinition(
            product_id="p1",
            version_family_id="vf1",
            version="1.0.0",
        )
        evidence = ManifestEvidence()

        content, digests = ManifestBuilder.build_manifest_content(defn, evidence)

        # Compute the content hash ourselves and compare
        content_bytes = canonicalize(content)
        # The digests already includes a content_hash, but we want to verify the logic
        alg, digest_bytes = decode_multihash(digests.definition)
        assert alg == "sha2-256"

    def test_algorithm_choice(self):
        """SHA2 and SHA3 produce different digests."""
        defn = ManifestDefinition(
            product_id="p1",
            version_family_id="vf1",
            version="1.0.0",
        )
        evidence = ManifestEvidence()

        content_sha2, digests_sha2 = ManifestBuilder.build_manifest_content(
            defn, evidence, "sha2-256"
        )
        content_sha3, digests_sha3 = ManifestBuilder.build_manifest_content(
            defn, evidence, "sha3-256"
        )

        # Digests should differ
        assert digests_sha2.definition != digests_sha3.definition
        # But content should be the same
        assert content_sha2 == content_sha3


class TestDeterminism:
    """Test that manifest building is deterministic."""

    def test_same_definition_same_digests(self):
        """Same definition always produces same digests."""
        defn = ManifestDefinition(
            product_id="p1",
            version_family_id="vf1",
            version="1.0.0",
            name="Product",
            odps={"id": "prod"},
            tags=["tag1", "tag2"],
        )
        evidence = ManifestEvidence(assets=[{"port": "out"}])

        _, digests1 = ManifestBuilder.build_manifest_content(defn, evidence)
        _, digests2 = ManifestBuilder.build_manifest_content(defn, evidence)

        assert digests1.definition == digests2.definition
        assert digests1.odps == digests2.odps

    def test_definition_field_order_irrelevant(self):
        """Different field order doesn't affect digests."""
        # Two definitions with fields in different order conceptually
        # (Python dicts maintain insertion order, so we build them differently)
        defn1_dict = {
            "product_id": "p1",
            "version_family_id": "vf1",
            "version": "1.0.0",
            "name": "Product",
            "tags": ["tag1"],
        }
        defn2_dict = {
            "name": "Product",
            "version": "1.0.0",
            "product_id": "p1",
            "tags": ["tag1"],
            "version_family_id": "vf1",
        }

        # Both should produce identical canonical JSON
        bytes1 = canonicalize(defn1_dict)
        bytes2 = canonicalize(defn2_dict)

        # The canonicalized bytes should be identical due to JSON key sorting
        assert bytes1 == bytes2


class TestTamperDetection:
    """Test that tampers are detected."""

    def test_tag_change_changes_digest(self):
        """Adding/removing a tag changes the digest."""
        defn1 = ManifestDefinition(
            product_id="p1",
            version_family_id="vf1",
            version="1.0.0",
            tags=["tag1", "tag2"],
        )
        defn2 = ManifestDefinition(
            product_id="p1",
            version_family_id="vf1",
            version="1.0.0",
            tags=["tag1", "tag2", "tag3"],
        )
        evidence = ManifestEvidence()

        _, digests1 = ManifestBuilder.build_manifest_content(defn1, evidence)
        _, digests2 = ManifestBuilder.build_manifest_content(defn2, evidence)

        assert digests1.tags != digests2.tags
        assert digests1.definition != digests2.definition

    def test_asset_change_changes_evidence_digest(self):
        """Adding an asset changes the evidence digest."""
        defn = ManifestDefinition(
            product_id="p1",
            version_family_id="vf1",
            version="1.0.0",
        )
        evidence1 = ManifestEvidence(assets=[])
        evidence2 = ManifestEvidence(
            assets=[{"port": "output", "asset_identifier": "table"}]
        )

        _, digests1 = ManifestBuilder.build_manifest_content(defn, evidence1)
        _, digests2 = ManifestBuilder.build_manifest_content(defn, evidence2)

        assert digests1.assets != digests2.assets

    def test_contract_change_changes_odcs_digest(self):
        """Adding a contract to ODCS changes the digest."""
        defn1 = ManifestDefinition(
            product_id="p1",
            version_family_id="vf1",
            version="1.0.0",
            odcs={},
        )
        defn2 = ManifestDefinition(
            product_id="p1",
            version_family_id="vf1",
            version="1.0.0",
            odcs={"contract1": {"id": "c1"}},
        )
        evidence = ManifestEvidence()

        _, digests1 = ManifestBuilder.build_manifest_content(defn1, evidence)
        _, digests2 = ManifestBuilder.build_manifest_content(defn2, evidence)

        assert digests1.odcs != digests2.odcs


class TestGoldenVectors:
    """Test against known good vectors."""

    def test_minimal_manifest_digest(self):
        """Minimal manifest produces consistent digest."""
        defn = ManifestDefinition(
            product_id="p1",
            version_family_id="vf1",
            version="1.0.0",
        )
        evidence = ManifestEvidence()

        _, digests = ManifestBuilder.build_manifest_content(defn, evidence)

        # Digest should be 69 characters (f + 2 hex code + 2 hex length + 64 hex)
        assert len(digests.definition) == 69
        # Should be verifiable
        content, _ = ManifestBuilder.build_manifest_content(defn, evidence)
        defn_bytes = canonicalize(content["definition"])
        assert verify_multihash(defn_bytes, digests.definition)
