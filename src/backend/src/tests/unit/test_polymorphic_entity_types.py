"""Polymorphic metadata/cost models accept every entity kind the UI renders panels for.

Regression: the metadata models only accepted domain/product/contract/dataset, so
saving a note, link or document on an asset, compliance policy, concept,
collection or authority relation failed with 422 even though the panel rendered.
"""
import pytest
from pydantic import ValidationError

from src.models.costs import CostItemCreate
from src.models.metadata import (
    METADATA_ENTITY_TYPES,
    DocumentCreate,
    LinkCreate,
    RichTextCreate,
)


def _rich_text(entity_type):
    return RichTextCreate(entity_id="x", entity_type=entity_type, title="t", content_markdown="c")


def _link(entity_type):
    return LinkCreate(entity_id="x", entity_type=entity_type, title="t", url="https://example.com")


def _document(entity_type):
    return DocumentCreate(entity_id="x", entity_type=entity_type, title="t")


@pytest.mark.parametrize("build", [_rich_text, _link, _document])
@pytest.mark.parametrize("entity_type", METADATA_ENTITY_TYPES)
def test_metadata_accepts_every_panel_entity_type(build, entity_type):
    assert build(entity_type).entity_type == entity_type


@pytest.mark.parametrize("build", [_rich_text, _link, _document])
@pytest.mark.parametrize("entity_type", ["", "unknown", "../etc", "asset/x", "ASSET"])
def test_metadata_rejects_other_entity_types(build, entity_type):
    with pytest.raises(ValidationError):
        build(entity_type)


def test_frontend_metadata_kinds_are_accepted():
    # Mirrors the EntityKind union in components/metadata/entity-metadata-panel.tsx.
    for kind in ("data_domain", "data_product", "data_contract", "concept",
                 "collection", "compliance_policy", "asset"):
        assert kind in METADATA_ENTITY_TYPES


def test_costs_accept_assets():
    item = CostItemCreate(entity_id="x", entity_type="asset", cost_center="STORAGE",
                          amount_cents=100, currency="USD", start_month="2026-10-01")
    assert item.entity_type == "asset"
