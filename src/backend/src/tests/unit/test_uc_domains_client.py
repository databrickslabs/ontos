"""Unit tests for the Unity Catalog domains SDK adapter."""

from types import SimpleNamespace
from unittest.mock import MagicMock

from src.common.uc_domains_client import UcDomainsClient


def _client():
    workspace = MagicMock()
    return workspace, UcDomainsClient(workspace)


def test_list_uses_tag_key_as_the_human_readable_name():
    workspace, client = _client()
    workspace.domains.list_domains.return_value = [
        SimpleNamespace(
            domain_id="domain-1",
            name="domains/domain-1",
            tag_key="Customer Operations",
            description="Customer-facing operational data",
            parent_domain_id=None,
        )
    ]

    result = client.list_domains()

    assert result[0].name == "Customer Operations"
    assert result[0].name != "domains/domain-1"
    assert result[0].tag_key == "Customer Operations"


def test_create_sends_the_label_as_tag_key_not_resource_name():
    workspace, client = _client()
    workspace.domains.create_domain.return_value = SimpleNamespace(
        domain_id="domain-1",
        name="domains/domain-1",
        tag_key="Customer Operations",
        description="Customer-facing operational data",
        parent_domain_id=None,
    )

    created = client.create_domain(
        "Customer Operations",
        description="Customer-facing operational data",
    )

    request = workspace.domains.create_domain.call_args.kwargs["domain"]
    assert request.tag_key == "Customer Operations"
    assert request.name is None
    assert created.name == "Customer Operations"


def test_update_maps_the_label_to_tag_key():
    workspace, client = _client()
    workspace.domains.get_domain.return_value = SimpleNamespace(
        domain_id="domain-1",
        name="domains/domain-1",
        tag_key="Customer Operations",
        description="Old description",
        parent_domain_id=None,
    )
    workspace.domains.update_domain.return_value = SimpleNamespace(
        domain_id="domain-1",
        name="domains/domain-1",
        tag_key="Customer Experience",
        description="New description",
        parent_domain_id=None,
    )

    updated = client.update_domain(
        "domain-1",
        name="Customer Experience",
        description="New description",
    )

    call = workspace.domains.update_domain.call_args.kwargs
    assert call["domain"].tag_key == "Customer Experience"
    assert call["domain"].name is None
    assert call["update_mask"].ToJsonString() == "tag_key,description"
    assert updated.name == "Customer Experience"
