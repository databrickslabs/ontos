"""Versioning fields reach the wire under the camelCase keys the frontend reads.

The detail views gate the personal-draft UI (Commit / Discard buttons, draft
banner) on ``draftOwnerId``, and family navigation on ``versionFamilyId`` /
``parentProductId`` / ``parentContractId``:

- Products: GET /data-products[/{id}] dumped by field name, so these went out
  as ``draft_owner_id`` etc. and the Commit button never rendered.
- Contracts: ``_build_contract_api_model`` never populated them, and
  ``DataContractRead`` serialized them under their snake_case alias.
"""
import os

os.environ['TESTING'] = 'true'
os.environ['SKIP_STARTUP_TASKS'] = 'true'

import uuid
from pathlib import Path

from src.controller.data_contracts_manager import DataContractsManager
from src.db_models.data_contracts import DataContractDb
from src.models.data_products import DataProduct
from src.repositories.data_contracts_repository import data_contract_repo

VERSIONING_KEYS = {"draftOwnerId", "parentProductId", "versionFamilyId", "baseName", "changeSummary"}


def _product(**overrides):
    return DataProduct(
        id="p2", name="Orders", version="1.0.0-draft", status="draft",
        draft_owner_id="jane@example.com", parent_product_id="p1",
        version_family_id="fam", base_name="Orders", change_summary="wip",
        inputPorts=[{"name": "in", "version": "1.0.0", "contractId": "c1"}],
        **overrides,
    )


class TestProductWireDict:
    def test_versioning_fields_use_camel_case_keys(self):
        data = _product().to_wire_dict()

        assert VERSIONING_KEYS <= data.keys()
        assert data["draftOwnerId"] == "jane@example.com"
        assert data["parentProductId"] == "p1"
        assert not {"draft_owner_id", "parent_product_id", "version_family_id"} & data.keys()

    def test_other_fields_keep_their_field_names(self):
        """Ports must stay camelCase field names (not the snake_case aliases)."""
        data = _product().to_wire_dict()

        assert "inputPorts" in data and "input_ports" not in data

    def test_dump_kwargs_pass_through(self):
        data = _product().to_wire_dict(exclude_none=True)

        assert "versionCount" not in data  # None → excluded
        assert data["versionFamilyId"] == "fam"


class TestContractDetailVersioningFields:
    def test_personal_draft_fields_reach_the_wire(self, db_session):
        parent_id, family_id = str(uuid.uuid4()), str(uuid.uuid4())
        draft = DataContractDb(
            id=str(uuid.uuid4()), name="c", version="1.0.0-draft", status="draft",
            parent_contract_id=parent_id, version_family_id=family_id,
            base_name="c", change_summary="wip", draft_owner_id="jane@example.com",
        )
        db_session.add(draft)
        db_session.flush()

        api = DataContractsManager(data_dir=Path("/tmp"))._build_contract_api_model(
            db_session, data_contract_repo.get_with_all(db_session, id=draft.id)
        )
        wire = api.model_dump(by_alias=True)  # what FastAPI's response_model emits

        assert wire["draftOwnerId"] == "jane@example.com"
        assert wire["parentContractId"] == parent_id
        assert wire["versionFamilyId"] == family_id
        assert wire["baseName"] == "c"
        assert wire["changeSummary"] == "wip"
        assert "draft_owner_id" not in wire
