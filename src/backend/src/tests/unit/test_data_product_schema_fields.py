"""Unit tests for missing schema fields on DataProductCreate / DataProductUpdate.

Three columns exist on ``DataProductDb`` but were missing from the create/update
schemas:

* ``draft_owner_id`` — creator / single-user owner email
* ``base_name``      — stable base name shared across versions
* ``change_summary`` — free-text changelog string

Because Pydantic v2 silently drops undeclared fields when
``model_config.extra`` is not set to ``"allow"``, POSTs/PUTs that carried these
keys went to the repository as ``None``. Repository code attempting
``getattr(obj_in, 'draft_owner_id', None)`` therefore always saw ``None`` —
the bug was invisible at the API layer (no validation error) but observable
downstream (DB row never had the value).

These tests assert that the schemas now declare the fields, so values round-
trip through the schema layer.
"""
import uuid

import pytest

from src.models.data_products import DataProductCreate, DataProductUpdate


class TestDataProductCreateMissingFields:
    """The three columns must round-trip through ``DataProductCreate``."""

    def test_draft_owner_id_roundtrips(self):
        m = DataProductCreate(
            id=str(uuid.uuid4()),
            name="x",
            version="1.0.0",
            draft_owner_id="creator@example.com",
        )
        assert m.draft_owner_id == "creator@example.com"

    def test_base_name_roundtrips(self):
        m = DataProductCreate(
            id=str(uuid.uuid4()),
            name="x",
            version="1.0.0",
            base_name="customer-orders",
        )
        assert m.base_name == "customer-orders"

    def test_change_summary_roundtrips(self):
        m = DataProductCreate(
            id=str(uuid.uuid4()),
            name="x",
            version="1.0.0",
            change_summary="Initial release",
        )
        assert m.change_summary == "Initial release"

    def test_all_three_default_to_none_when_omitted(self):
        """Backward-compat: omitting the new fields is still valid."""
        m = DataProductCreate(id=str(uuid.uuid4()), name="x", version="1.0.0")
        assert m.draft_owner_id is None
        assert m.base_name is None
        assert m.change_summary is None


class TestDataProductUpdateMissingFields:
    """Same three fields must round-trip through ``DataProductUpdate``."""

    def test_draft_owner_id_roundtrips(self):
        m = DataProductUpdate(draft_owner_id="creator@example.com")
        assert m.draft_owner_id == "creator@example.com"

    def test_base_name_roundtrips(self):
        m = DataProductUpdate(base_name="customer-orders")
        assert m.base_name == "customer-orders"

    def test_change_summary_roundtrips(self):
        m = DataProductUpdate(change_summary="Patch for breaking change")
        assert m.change_summary == "Patch for breaking change"

    def test_clearing_draft_owner_id_is_distinguishable_from_omitted(self):
        """When promoting a personal draft, the update sets
        ``draft_owner_id=None`` explicitly. ``model_dump(exclude_unset=True)``
        must reflect that the caller set the field (so the repository can
        distinguish "clear" from "leave alone")."""
        m = DataProductUpdate(draft_owner_id=None)
        dump = m.model_dump(exclude_unset=True)
        assert "draft_owner_id" in dump
        assert dump["draft_owner_id"] is None

        m_omitted = DataProductUpdate()
        assert "draft_owner_id" not in m_omitted.model_dump(exclude_unset=True)
