"""Manager-level tests for read-path reference resolution (#854).

Mirrors the working output-port→contract resolution onto the two previously-raw
references: input-port contractId → contractName, and contract dataProduct → product
name + id. Both degrade gracefully (name stays None, raw value preserved) when the
referent doesn't exist.
"""
import uuid
from pathlib import Path

import pytest
from unittest.mock import MagicMock
from sqlalchemy.orm import Session

from src.controller.data_products_manager import DataProductsManager
from src.controller.data_contracts_manager import DataContractsManager
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


def _product_with_input(contract_id: str) -> dict:
    return {
        "name": "Consumer Product", "version": "1.0.0", "productType": "sourceAligned",
        "inputPorts": [{"name": "in1", "version": "1.0.0", "contractId": contract_id}],
    }


def _odcs(name: str, **extra) -> dict:
    return {"apiVersion": "v3.1.0", "kind": "DataContract", "name": name,
            "version": "1.0.0", "status": "draft", **extra}


class TestInputPortContractResolution:
    def test_input_port_contract_name_resolved(self, product_manager, db_session):
        cid = str(uuid.uuid4())
        db_session.add(DataContractDb(id=cid, name="Orders Contract", version="1.0.0", status="active"))
        db_session.commit()
        created = product_manager.create_product(
            _product_with_input(cid), db=db_session, user="a@b.com",
        )
        loaded = product_manager.get_product(created.id)
        assert loaded.inputPorts and loaded.inputPorts[0].contractId == cid
        assert loaded.inputPorts[0].contractName == "Orders Contract"

    def test_input_port_unknown_contract_is_graceful(self, product_manager, db_session):
        created = product_manager.create_product(
            _product_with_input(str(uuid.uuid4())), db=db_session, user="a@b.com",
        )
        loaded = product_manager.get_product(created.id)
        # Missing referent → name stays None; the raw id is preserved for fallback display.
        assert loaded.inputPorts[0].contractName is None
        assert loaded.inputPorts[0].contractId


class TestContractDataProductResolution:
    def test_data_product_resolved_by_id(self, product_manager, db_session):
        prod = product_manager.create_product(
            {"name": "My Product", "version": "1.0.0", "productType": "sourceAligned"},
            db=db_session, user="a@b.com",
        )
        mgr = _contract_manager()
        created = mgr.create_from_upload(
            db=db_session, parsed_odcs=_odcs("C linked", dataProduct=prod.id), current_user="a@b.com",
        )
        api = mgr._build_contract_api_model(db_session, created)
        assert api.dataProduct == prod.id
        assert api.dataProductName == "My Product"
        assert api.dataProductId == prod.id

    def test_data_product_resolved_by_name(self, product_manager, db_session):
        product_manager.create_product(
            {"name": "Named Product", "version": "1.0.0", "productType": "sourceAligned"},
            db=db_session, user="a@b.com",
        )
        mgr = _contract_manager()
        created = mgr.create_from_upload(
            db=db_session, parsed_odcs=_odcs("C byname", dataProduct="Named Product"), current_user="a@b.com",
        )
        api = mgr._build_contract_api_model(db_session, created)
        assert api.dataProductName == "Named Product" and api.dataProductId

    def test_unknown_data_product_is_graceful(self, db_session):
        mgr = _contract_manager()
        created = mgr.create_from_upload(
            db=db_session, parsed_odcs=_odcs("C ghost", dataProduct="Ghost Product"), current_user="a@b.com",
        )
        api = mgr._build_contract_api_model(db_session, created)
        assert api.dataProductName is None and api.dataProductId is None
        assert api.dataProduct == "Ghost Product"  # raw value preserved for fallback
