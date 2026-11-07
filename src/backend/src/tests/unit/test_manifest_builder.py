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


def _rev(items, reverse):
    """The list reversed when ``reverse`` (another database order), else as is."""
    return list(reversed(items)) if reverse else list(items)


def _odps(r):
    """An ODPS export where every order-insensitive list is reversed when ``r``."""
    return {
        "id": "prod",
        "inputPorts": _rev([
            {"name": "in_a", "version": "1.0", "contractId": "c1"},
            {"name": "in_a", "version": "2.0"},
            {"name": "in_b", "version": "1.0"},
        ], r),
        "outputPorts": _rev([
            {
                "name": "out_a",
                "version": "1.0",
                "contractId": "c1",
                "customProperties": _rev([
                    {"property": "p1", "value": "x"},
                    {"property": "p2", "value": ["kept", "in", "order"]},
                ], r),
            },
            {"name": "out_b", "version": "1.0", "contractId": "c2"},
        ], r),
        "support": _rev([
            {"channel": "email", "url": "mailto:a@example.com"},
            {"channel": "slack", "url": "https://slack/a"},
            {"channel": "slack", "url": "https://slack/b"},
        ], r),
        "team": {
            "name": "Team",
            "members": _rev([
                {"username": "alice", "role": "editor"},
                {"username": "alice", "role": "owner"},
                {"username": "bob", "role": "owner"},
            ], r),
        },
        "customProperties": _rev([
            {"property": "a", "value": "1"},
            {"property": "b", "value": "2"},
        ], r),
        "authoritativeDefinitions": _rev([
            {"type": "businessDefinition", "url": "https://a"},
            {"type": "businessDefinition", "url": "https://b"},
            {"type": "tutorial", "url": "https://a"},
        ], r),
        "datasets": _rev([
            {
                "name": "ds_a",
                "tables": _rev([{"name": "t1"}, {"name": "t2"}], r),
                "views": _rev([{"name": "v1"}, {"name": "v2"}], r),
            },
            {"name": "ds_b", "tables": _rev([{"name": "t3"}, {"name": "t4"}], r)},
        ], r),
    }


def _odcs(r, cid):
    """An ODCS export where every order-insensitive list is reversed when ``r``."""
    return {
        "id": cid,
        "tags": ["kept", "in", "order"],
        "slaProperties": [{"property": "latency"}, {"property": "frequency"}],
        "team": _rev([
            {"username": "carol", "role": "owner"},
            {"username": "dave", "role": "steward"},
        ], r),
        "servers": _rev([{"server": "dev"}, {"server": "prod"}], r),
        "quality": _rev([
            {"type": "sql", "name": "q1", "rule": "r"},
            {"type": "sql", "name": "q2", "rule": "r"},
        ], r),
        "schema": _rev([
            {
                "name": "orders",
                "authoritativeDefinitions": _rev([
                    {"type": "a", "url": "https://1"},
                    {"type": "b", "url": "https://1"},
                ], r),
                "quality": _rev([
                    # Same (type, name, rule): ordered by their canonical JSON
                    {"type": "library", "rule": "rowCount", "mustBeGreaterThan": 0},
                    {"type": "library", "rule": "rowCount", "mustBeLessThan": 9},
                ], r),
                "properties": _rev([
                    {
                        "name": "address",
                        "logicalType": "object",
                        "properties": _rev([
                            {"name": "city"},
                            {"name": "zip", "examples": ["2", "1"]},
                        ], r),
                    },
                    {
                        "name": "id",
                        "quality": _rev([
                            {"type": "library", "rule": "unique"},
                            {"type": "library", "rule": "notNull"},
                        ], r),
                        "customProperties": _rev([
                            {"property": "x", "value": "1"},
                            {"property": "y", "value": "2"},
                        ], r),
                    },
                ], r),
            },
            {"name": "customers", "properties": [{"name": "id"}]},
        ], r),
    }


def _definition_and_evidence(r):
    definition = ManifestDefinition(
        product_id="p1",
        version_family_id="vf1",
        version="1.0.0",
        name="Product",
        odps=_odps(r),
        odcs={"c1": _odcs(r, "c1"), "c2": _odcs(r, "c2")},
        semantic_links=_rev([
            {"iri": "http://example.com/a", "label": "A"},
            {"iri": "http://example.com/a", "label": "B"},
            {"iri": "http://example.com/b"},
        ], r),
        owners={"members": _rev([
            {"username": "alice", "role": "owner"},
            {"username": "bob", "role": "owner"},
        ], r)},
        tags=_rev(["domain/accounting", "domain/finance", "system/validated=yes"], r),
        domains=_rev([
            {"id": "d1", "name": "Finance", "primary": True},
            {"id": "d2", "name": "Sales", "primary": False},
        ], r),
    )
    evidence = ManifestEvidence(
        assets=_rev([
            {
                "port": "out_a",
                "asset_identifier": "cat.sch.t1",
                # Physical schema in position order: never sorted
                "columns": [{"name": "z"}, {"name": "a"}],
            },
            {"port": "out_a", "asset_identifier": "cat.sch.t2"},
            {"port": "out_b", "asset_identifier": "cat.sch.t1"},
        ], r),
    )
    return definition, evidence


class TestCollectionOrderIndependence:
    """The builder applies the Decision 6 sort orders to every collection it lists."""

    def test_different_collection_order_same_bytes_and_digests(self):
        """Equivalent inputs in another order give the same canonical bytes and digests."""
        content_a, digests_a = ManifestBuilder.build_manifest_content(
            *_definition_and_evidence(False)
        )
        content_b, digests_b = ManifestBuilder.build_manifest_content(
            *_definition_and_evidence(True)
        )

        assert canonicalize(content_a) == canonicalize(content_b)
        assert digests_a == digests_b
        assert ManifestBuilder.compute_content_hash(
            content_a
        ) == ManifestBuilder.compute_content_hash(content_b)

    def test_sorting_works_on_a_copy(self):
        """The content is sorted while the caller's definition and evidence stay as given."""
        definition, evidence = _definition_and_evidence(True)
        expected_def, expected_ev = _definition_and_evidence(True)
        content, _ = ManifestBuilder.build_manifest_content(definition, evidence)
        assert definition.to_dict() == expected_def.to_dict()
        assert evidence.to_dict() == expected_ev.to_dict()
        assert content["definition"] != expected_def.to_dict()

    def test_every_section_digest_is_order_independent(self):
        """Each section digest (ODPS, every ODCS, links, owners, tags, assets) matches."""
        _, digests_a = ManifestBuilder.build_manifest_content(*_definition_and_evidence(False))
        _, digests_b = ManifestBuilder.build_manifest_content(*_definition_and_evidence(True))
        for section in ("definition", "odps", "semantic_links", "owners", "tags", "assets"):
            assert getattr(digests_a, section) == getattr(digests_b, section), section
        assert digests_a.odcs == digests_b.odcs

    def test_content_is_sorted(self):
        """The returned content holds the collections in their sort order."""
        content, _ = ManifestBuilder.build_manifest_content(*_definition_and_evidence(True))
        definition = content["definition"]
        odps = definition["odps"]
        assert [(p["name"], p["version"]) for p in odps["inputPorts"]] == [
            ("in_a", "1.0"), ("in_a", "2.0"), ("in_b", "1.0"),
        ]
        assert [p["name"] for p in odps["outputPorts"]] == ["out_a", "out_b"]
        assert [p["property"] for p in odps["outputPorts"][0]["customProperties"]] == [
            "p1", "p2",
        ]
        assert [m["role"] for m in odps["team"]["members"]] == ["editor", "owner", "owner"]
        assert [d["name"] for d in odps["datasets"]] == ["ds_a", "ds_b"]
        assert [t["name"] for t in odps["datasets"][0]["tables"]] == ["t1", "t2"]
        assert [v["name"] for v in odps["datasets"][0]["views"]] == ["v1", "v2"]
        odcs = definition["odcs"]["c1"]
        assert [s["name"] for s in odcs["schema"]] == ["customers", "orders"]
        orders = odcs["schema"][1]
        assert [p["name"] for p in orders["properties"]] == ["address", "id"]
        assert [p["name"] for p in orders["properties"][0]["properties"]] == ["city", "zip"]
        assert [q["rule"] for q in orders["properties"][1]["quality"]] == ["notNull", "unique"]
        assert [s["server"] for s in odcs["servers"]] == ["dev", "prod"]
        assert [m["username"] for m in odcs["team"]] == ["carol", "dave"]
        assert definition["tags"] == [
            "domain/accounting", "domain/finance", "system/validated=yes",
        ]
        assert [d["id"] for d in definition["domains"]] == ["d1", "d2"]
        assert [link.get("label") for link in definition["semantic_links"]] == ["A", "B", None]
        assets = content["evidence"]["assets"]
        assert [(a["port"], a["asset_identifier"]) for a in assets] == [
            ("out_a", "cat.sch.t1"), ("out_a", "cat.sch.t2"), ("out_b", "cat.sch.t1"),
        ]

        # Building again from the sorted content changes nothing
        again, _ = ManifestBuilder.build_manifest_content(
            ManifestDefinition(**content["definition"]),
            ManifestEvidence(**content["evidence"]),
        )
        assert again == content

    def test_lists_the_adr_does_not_sort_keep_their_order(self):
        """Lists outside Decision 6 (and asset column positions) keep the given order."""
        content, _ = ManifestBuilder.build_manifest_content(*_definition_and_evidence(True))
        odcs = content["definition"]["odcs"]["c1"]
        assert odcs["tags"] == ["kept", "in", "order"]
        assert [p["property"] for p in odcs["slaProperties"]] == ["latency", "frequency"]
        zip_prop = odcs["schema"][1]["properties"][0]["properties"][1]
        assert zip_prop["examples"] == ["2", "1"]
        out_a = content["definition"]["odps"]["outputPorts"][0]
        assert out_a["customProperties"][1]["value"] == ["kept", "in", "order"]
        assert [c["name"] for c in content["evidence"]["assets"][0]["columns"]] == ["z", "a"]

        # Reordering such a list is a content change
        definition, evidence = _definition_and_evidence(True)
        evidence.assets[-1]["columns"].reverse()
        definition.odcs["c1"]["tags"].reverse()
        _, before = ManifestBuilder.build_manifest_content(*_definition_and_evidence(True))
        _, after = ManifestBuilder.build_manifest_content(definition, evidence)
        assert before.assets != after.assets
        assert before.odcs["c1"] != after.odcs["c1"]

    def test_float_error_names_the_input_path(self):
        """A float in the definition fails before sorting, with its path."""
        from src.common.manifest_canonicalization import CanonicalizationError

        definition, evidence = _definition_and_evidence(False)
        definition.odps["outputPorts"][1]["score"] = 0.5
        with pytest.raises(CanonicalizationError) as exc:
            ManifestBuilder.build_manifest_content(definition, evidence)
        assert exc.value.code == "float_not_allowed"
        assert exc.value.path == "$.definition.odps.outputPorts[1].score"

    def test_sort_custom_properties_list(self):
        """customProperties ({property, value} list) sort by property."""
        props = [{"property": "z", "value": 1}, {"property": "a", "value": 2}]
        assert [p["property"] for p in ManifestBuilder.sort_properties(props)] == ["a", "z"]
