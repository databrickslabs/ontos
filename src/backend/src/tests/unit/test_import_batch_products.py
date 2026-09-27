"""Unit tests for batch/multi-file ODPS product import (#855).

Covers multi-file aggregation via `DataProductsManager.create_products_from_files`
and the unified truthful summary. Array-in-file already worked for products; here
we assert it flows through the new multi-file orchestrator with per-entity results.
"""
import json
import uuid

import pytest
import yaml
from unittest.mock import MagicMock
from sqlalchemy.orm import Session

from src.controller.data_products_manager import DataProductsManager


@pytest.fixture
def manager(db_session: Session) -> DataProductsManager:
    return DataProductsManager(
        db=db_session,
        ws_client=MagicMock(),
        notifications_manager=MagicMock(),
        tags_manager=MagicMock(),
    )


def _odps(name: str) -> dict:
    return {
        "apiVersion": "v1.0.0",
        "kind": "DataProduct",
        "name": name,
        "version": "1.0.0",
        "status": "draft",
        "productType": "sourceAligned",
        "owner": "test@example.com",
    }


class TestProductBatchImport:
    def test_array_in_file_creates_many(self, manager: DataProductsManager):
        content = yaml.safe_dump([_odps("P A"), _odps("P B")]).encode("utf-8")
        result = manager.create_products_from_files(
            [("p.yaml", content)], user="alice@example.com",
        )
        assert (result.created, result.failed, result.total) == (2, 0, 2)
        assert len(result.created_ids) == 2

    def test_multi_file_aggregates(self, manager: DataProductsManager):
        files = [
            ("f1.json", json.dumps(_odps("MF One")).encode("utf-8")),
            ("f2.yaml", yaml.safe_dump([_odps("MF Two"), _odps("MF Three")]).encode("utf-8")),
        ]
        result = manager.create_products_from_files(files, user="alice@example.com")
        assert (result.created, result.total) == (3, 3)
        assert {i.source_file for i in result.items} == {"f1.json", "f2.yaml"}

    def test_bad_entity_does_not_abort_batch(self, manager: DataProductsManager):
        content = json.dumps([_odps("Good"), "not-an-object"]).encode("utf-8")
        result = manager.create_products_from_files(
            [("p.json", content)], user="alice@example.com",
        )
        assert (result.created, result.failed, result.total) == (1, 1, 2)

    def test_unsupported_extension_is_single_failed_item(self, manager: DataProductsManager):
        files = [
            ("ok.json", json.dumps(_odps("OK")).encode("utf-8")),
            ("bad.txt", b"whatever"),
        ]
        result = manager.create_products_from_files(files, user="alice@example.com")
        assert result.created == 1
        assert result.failed == 1
        bad = [i for i in result.items if i.source_file == "bad.txt"]
        assert len(bad) == 1 and bad[0].status == "failed"

    def test_source_id_preserved_for_non_uuid_id(self, manager: DataProductsManager):
        prod = _odps("Urn Product")
        prod["id"] = "urn:acme:product:orders"
        content = json.dumps(prod).encode("utf-8")
        result = manager.create_products_from_files([("p.json", content)], user="a@b.com")
        assert result.created == 1
        item = result.items[0]
        # New Ontos UUID assigned; original id captured in the item summary.
        assert item.source_id == "urn:acme:product:orders"
        assert item.entity_id and item.entity_id != "urn:acme:product:orders"
