"""
Entity-type allowlists for the polymorphic metadata and costs panels.

The asset detail view renders the metadata and costs panels with
``entityType="asset"``; the request models must accept it, or every
note/link/document/cost item on an asset fails with a 422.
"""
from datetime import date

import pytest
from pydantic import ValidationError

from src.models.costs import CostItemCreate
from src.models.metadata import DocumentCreate, LinkCreate, RichTextCreate

METADATA_ENTITY_TYPES = ["data_domain", "data_product", "data_contract", "dataset", "asset"]
COST_ENTITY_TYPES = ["data_domain", "data_product", "data_contract", "asset"]


def _rich_text(entity_type: str) -> RichTextCreate:
    return RichTextCreate(entity_id="e-1", entity_type=entity_type, title="Note", content_markdown="Body")


def _link(entity_type: str) -> LinkCreate:
    return LinkCreate(entity_id="e-1", entity_type=entity_type, title="Link", url="https://example.com")


def _document(entity_type: str) -> DocumentCreate:
    return DocumentCreate(entity_id="e-1", entity_type=entity_type, title="Doc")


def _cost_item(entity_type: str) -> CostItemCreate:
    return CostItemCreate(
        entity_id="e-1",
        entity_type=entity_type,
        cost_center="OTHER",
        amount_cents=100,
        currency="USD",
        start_month=date(2026, 1, 1),
    )


@pytest.mark.parametrize("build", [_rich_text, _link, _document])
@pytest.mark.parametrize("entity_type", METADATA_ENTITY_TYPES)
def test_metadata_models_accept_supported_entity_types(build, entity_type):
    assert build(entity_type).entity_type == entity_type


@pytest.mark.parametrize("build", [_rich_text, _link, _document])
def test_metadata_models_reject_unknown_entity_type(build):
    with pytest.raises(ValidationError):
        build("not_an_entity")


@pytest.mark.parametrize("entity_type", COST_ENTITY_TYPES)
def test_cost_item_accepts_supported_entity_types(entity_type):
    assert _cost_item(entity_type).entity_type == entity_type


def test_cost_item_rejects_unknown_entity_type():
    with pytest.raises(ValidationError):
        _cost_item("not_an_entity")
