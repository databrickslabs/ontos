"""Unit tests for the MCP get-tool projections.

The agent cannot answer ownership questions for imported ODPS/ODCS entities
unless `_serialize_product` / `_serialize_contract` surface the imported team
block (with roles). It also cannot reconcile an upstream reference unless
`original_id` (preserved as the `ontosOriginalId` custom property when
`adopt_ids=false`) comes down the wire. These tests pin that contract.
"""
from datetime import datetime
from types import SimpleNamespace

from src.tools.data_products import _serialize_product
from src.tools.data_contracts import _serialize_contract


def _member(username, name=None, role=None):
    return SimpleNamespace(
        username=username, name=name, role=role,
        dateIn="2026-01-01", dateOut=None, replacedByUsername=None,
    )


def _custom_prop(prop, value):
    return SimpleNamespace(property=prop, value=value)


def _product(**overrides):
    base = dict(
        id="p1", name="P1", domain="sales", description=None,
        status="active", version="1.0.0",
        owner_team_id=None, owner_team_name=None,
        outputPorts=[], tenant=None, team=None, customProperties=None,
        created_at=None, updated_at=None, published_at=None, productCreatedTs=None,
    )
    base.update(overrides)
    return SimpleNamespace(**base)


def _contract(**overrides):
    base = dict(
        id="c1", name="C1", domain="sales", description=None,
        status="active", version="1.0.0",
        owner_team_name=None, dataProduct=None,
        team=[], customProperties=None,
        created=None, updated=None, published_at=None,
    )
    base.update(overrides)
    return SimpleNamespace(**base)


# =====================================================================
# Products
# =====================================================================

class TestSerializeProduct:
    def test_includes_team_members_with_role(self):
        """ODPS team block + members[*].role must reach the agent — the whole
        point of this change. dateIn/dateOut/replacedByUsername are explicitly
        omitted (not useful for ownership answers)."""
        team = SimpleNamespace(
            name="Platform",
            description="Platform ops",
            members=[_member("eo@x", "Eve Operations", "owner"),
                     _member("js@x", "Jane Steward", "data steward")],
        )
        out = _serialize_product(_product(team=team))

        assert out["team"]["name"] == "Platform"
        assert out["team"]["description"] == "Platform ops"
        assert [m["role"] for m in out["team"]["members"]] == ["owner", "data steward"]
        assert out["team"]["members"][0]["name"] == "Eve Operations"
        # Verbose fields intentionally dropped from the projection:
        for m in out["team"]["members"]:
            assert "dateIn" not in m
            assert "dateOut" not in m
            assert "replacedByUsername" not in m

    def test_handles_no_team(self):
        """A product without imported ODPS team metadata serializes `team: None`
        — no KeyError, no empty-object surprise."""
        out = _serialize_product(_product(team=None))
        assert out["team"] is None

    def test_handles_malformed_member_with_only_username(self):
        """A member with just `username` (no `name`, no `role`) must still be
        projected — e.g. roles are optional on the ODPS TeamMember model."""
        team = SimpleNamespace(name="T", description=None,
                               members=[_member("only-un@x")])
        out = _serialize_product(_product(team=team))
        m = out["team"]["members"][0]
        assert m["username"] == "only-un@x"
        assert m["name"] is None
        assert m["role"] is None

    def test_timestamp_serialization(self):
        """datetime timestamps come down as ISO strings; `None` passes through."""
        now = datetime(2026, 10, 11, 12, 0, 0)
        out = _serialize_product(_product(
            created_at=now, updated_at=now, published_at=None, productCreatedTs=now,
        ))
        assert out["created_at"] == "2026-10-11T12:00:00"
        assert out["updated_at"] == "2026-10-11T12:00:00"
        assert out["published_at"] is None
        assert out["product_created_ts"] == "2026-10-11T12:00:00"

    def test_surfaces_original_id_from_custom_properties(self):
        """When `adopt_ids=false`, the YAML id is preserved as the
        `ontosOriginalId` custom property; the projection must surface it so an
        agent can reconcile the Ontos UUID with an upstream reference."""
        props = [
            _custom_prop("ontosOriginalDomain", "marketing-ops"),
            _custom_prop("ontosOriginalId", "upstream-abc-123"),
            _custom_prop("other", "ignore"),
        ]
        out = _serialize_product(_product(customProperties=props))
        assert out["original_id"] == "upstream-abc-123"

    def test_original_id_missing_is_none(self):
        """No `ontosOriginalId` entry (and no customProperties at all) returns
        `original_id: None`."""
        assert _serialize_product(_product(customProperties=None))["original_id"] is None
        assert _serialize_product(_product(customProperties=[]))["original_id"] is None
        other_only = [_custom_prop("foo", "bar")]
        assert _serialize_product(_product(customProperties=other_only))["original_id"] is None


# =====================================================================
# Contracts
# =====================================================================

class TestSerializeContract:
    def test_includes_team_members_with_role(self):
        """ODCS `team` is a flat List[TeamMember] (no Team wrapper), carrying
        username/role. Projection must include all with roles."""
        team = [
            SimpleNamespace(username="eo@x", name="Eve Operations", role="owner",
                            dateIn=None, dateOut=None, replacedByUsername=None),
            SimpleNamespace(username="js@x", name="Jane Steward", role="data steward",
                            dateIn=None, dateOut=None, replacedByUsername=None),
        ]
        out = _serialize_contract(_contract(team=team))
        assert len(out["team"]) == 2
        assert out["team"][0] == {"username": "eo@x", "name": "Eve Operations", "role": "owner"}
        assert out["team"][1]["role"] == "data steward"
        for m in out["team"]:
            assert set(m.keys()) == {"username", "name", "role"}

    def test_handles_no_team(self):
        """Empty team list serializes as an empty list, not None, matching the
        ODCS DataContractRead shape (team has `default_factory=list`)."""
        out = _serialize_contract(_contract(team=[]))
        assert out["team"] == []

    def test_timestamp_passthrough(self):
        """DataContractRead stores timestamps as ISO strings already — the
        projection must pass them through without re-serializing."""
        out = _serialize_contract(_contract(
            created="2026-10-01T10:00:00",
            updated="2026-10-05T11:00:00",
            published_at="2026-10-06T12:00:00",
        ))
        assert out["created_at"] == "2026-10-01T10:00:00"
        assert out["updated_at"] == "2026-10-05T11:00:00"
        assert out["published_at"] == "2026-10-06T12:00:00"

    def test_surfaces_original_id_from_dict_custom_properties(self):
        """Contracts expose customProperties as a Dict[str, Any] (not a list of
        CustomProperty like products). The lookup must handle the dict shape."""
        props = {"ontosOriginalId": "upstream-c-999", "other": "x"}
        out = _serialize_contract(_contract(customProperties=props))
        assert out["original_id"] == "upstream-c-999"

    def test_original_id_missing_is_none(self):
        assert _serialize_contract(_contract(customProperties=None))["original_id"] is None
        assert _serialize_contract(_contract(customProperties={}))["original_id"] is None
        assert _serialize_contract(_contract(customProperties={"foo": "bar"}))["original_id"] is None
