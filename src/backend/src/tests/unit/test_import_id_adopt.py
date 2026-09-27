"""Manager-level tests for adopting the YAML entity id (UUID) on import (#853).

Covers: valid new UUID adopted as PK, non-UUID falls back to a generated UUID (with
sourceId + ontosOriginalId provenance), duplicate-id handling (skip default / import as
new copy), and the ontosOriginalId / ontosEntityId export round-trip — for both products
and contracts.
"""
import uuid
from pathlib import Path

import pytest
from unittest.mock import MagicMock
from sqlalchemy.orm import Session

from src.controller.data_contracts_manager import DataContractsManager
from src.controller.data_products_manager import (
    DataProductsManager,
    ONTOS_ORIGINAL_ID_PROPERTY,
    ONTOS_ENTITY_ID_PROPERTY,
    SOURCE_ID_PROPERTY,
)
from src.db_models.data_products import DataProductDb
from src.db_models.data_contracts import DataContractDb


@pytest.fixture
def product_manager(db_session: Session) -> DataProductsManager:
    return DataProductsManager(
        db=db_session, ws_client=MagicMock(),
        notifications_manager=MagicMock(), tags_manager=MagicMock(),
    )


def _contract_manager() -> DataContractsManager:
    mgr = DataContractsManager(data_dir=Path("/tmp"))
    mgr._update_search_index = lambda *a, **k: None
    return mgr


def _product(name: str, **extra) -> dict:
    return {"name": name, "version": "1.0.0", "productType": "sourceAligned", **extra}


def _odcs(name: str, **extra) -> dict:
    return {"apiVersion": "v3.1.0", "kind": "DataContract", "name": name,
            "version": "1.0.0", "status": "draft", **extra}


def _cp(export: dict, key: str):
    return next((c["value"] for c in export.get("customProperties", []) if c.get("property") == key), None)


class TestProductIdAdoption:
    def test_adopts_valid_uuid_as_pk(self, product_manager, db_session):
        fid = str(uuid.uuid4())
        created = product_manager.create_product(
            _product("Adopt Me", id=fid), db=db_session, user="a@b.com",
            preserve_source_id=True, adopt_ids=True,
        )
        assert created.id == fid  # file UUID adopted → cross-entity links survive
        assert db_session.query(DataProductDb).filter_by(id=fid).first() is not None

    def test_adopt_off_generates_uuid_but_records_original(self, product_manager, db_session):
        fid = str(uuid.uuid4())
        created = product_manager.create_product(
            _product("No Adopt", id=fid), db=db_session, user="a@b.com",
            preserve_source_id=True, adopt_ids=False,
        )
        assert created.id != fid
        export = product_manager.build_odps_export(created.id, db=db_session)
        assert _cp(export, ONTOS_ORIGINAL_ID_PROPERTY) == fid

    def test_non_uuid_generates_uuid_and_records_sourceid(self, product_manager, db_session):
        created = product_manager.create_product(
            _product("Urn", id="urn:acme:product:orders"), db=db_session, user="a@b.com",
            preserve_source_id=True, adopt_ids=True,
        )
        assert uuid.UUID(created.id)  # generated, not the URN
        export = product_manager.build_odps_export(created.id, db=db_session)
        assert _cp(export, ONTOS_ORIGINAL_ID_PROPERTY) == "urn:acme:product:orders"
        assert _cp(export, SOURCE_ID_PROPERTY) == "urn:acme:product:orders"

    def test_export_emits_ontos_entity_id(self, product_manager, db_session):
        created = product_manager.create_product(_product("Entity Id"), db=db_session, user="a@b.com")
        export = product_manager.build_odps_export(created.id, db=db_session)
        assert _cp(export, ONTOS_ENTITY_ID_PROPERTY) == created.id

    def test_batch_duplicate_skipped_by_default(self, product_manager, db_session):
        fid = str(uuid.uuid4())
        product_manager.create_product(_product("Original", id=fid), db=db_session, user="a@b.com",
                                       preserve_source_id=True, adopt_ids=True)
        import json
        content = json.dumps(_product("Dupe", id=fid)).encode("utf-8")
        result = product_manager.create_products_from_files([("p.json", content)], user="a@b.com")
        assert result.created == 0 and result.skipped == 1
        assert result.items[0].status == "skipped" and result.items[0].entity_id == fid

    def test_batch_duplicate_import_as_new_copy(self, product_manager, db_session):
        fid = str(uuid.uuid4())
        product_manager.create_product(_product("Original2", id=fid), db=db_session, user="a@b.com",
                                       preserve_source_id=True, adopt_ids=True)
        import json
        content = json.dumps(_product("Copy", id=fid)).encode("utf-8")
        result = product_manager.create_products_from_files(
            [("p.json", content)], user="a@b.com", on_duplicate="new",
        )
        assert result.created == 1 and result.skipped == 0
        assert result.items[0].entity_id != fid  # fresh UUID for the copy


class TestContractIdAdoption:
    def test_adopts_valid_uuid_as_pk(self, db_session):
        mgr = _contract_manager()
        fid = str(uuid.uuid4())
        created = mgr.create_from_upload(db=db_session, parsed_odcs=_odcs("C Adopt", id=fid),
                                         current_user="a@b.com", adopt_ids=True)
        assert created.id == fid
        assert db_session.query(DataContractDb).filter_by(id=fid).first() is not None

    def test_adopt_off_generates_uuid(self, db_session):
        mgr = _contract_manager()
        fid = str(uuid.uuid4())
        created = mgr.create_from_upload(db=db_session, parsed_odcs=_odcs("C NoAdopt", id=fid),
                                         current_user="a@b.com", adopt_ids=False)
        assert created.id != fid
        export = mgr.build_odcs_from_db(created, db_session)
        assert _cp(export, ONTOS_ORIGINAL_ID_PROPERTY) == fid

    def test_export_emits_ontos_entity_id(self, db_session):
        mgr = _contract_manager()
        created = mgr.create_from_upload(db=db_session, parsed_odcs=_odcs("C Entity"),
                                         current_user="a@b.com")
        export = mgr.build_odcs_from_db(created, db_session)
        assert _cp(export, ONTOS_ENTITY_ID_PROPERTY) == created.id

    def test_batch_duplicate_skipped_then_new_copy(self, db_session):
        mgr = _contract_manager()
        fid = str(uuid.uuid4())
        import json
        files = [("c.json", json.dumps(_odcs("C Dup", id=fid)), "application/json")]
        first = mgr.create_contracts_from_files(db=db_session, files=files, current_user="a@b.com")
        assert first.created == 1 and first.created_ids == [fid]
        # Second import of the same id → skipped by default (idempotent re-import).
        skip = mgr.create_contracts_from_files(db=db_session, files=files, current_user="a@b.com")
        assert skip.created == 0 and skip.skipped == 1
        # As a new copy → created with a fresh UUID.
        new = mgr.create_contracts_from_files(db=db_session, files=files, current_user="a@b.com", on_duplicate="new")
        assert new.created == 1 and new.created_ids[0] != fid
