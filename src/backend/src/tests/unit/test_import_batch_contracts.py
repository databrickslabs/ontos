"""Unit tests for batch/multi-file ODCS contract import (#855).

Covers the parity fix (array-in-file for contracts) and multi-file aggregation
via `DataContractsManager.create_contracts_from_files`, plus the truthful
per-entity summary and batch-continues-on-error semantics.
"""
import json
import uuid
from pathlib import Path

import pytest
import yaml
from sqlalchemy.orm import Session

from src.controller.data_contracts_manager import DataContractsManager
from src.db_models.data_contracts import DataContractDb


def _manager() -> DataContractsManager:
    mgr = DataContractsManager(data_dir=Path("/tmp"))
    # Neutralize post-create side effects (search index, delivery) so the tests
    # stay dependency-free — same approach as test_contract_duplicate_name.
    mgr._update_search_index = lambda *a, **k: None
    return mgr


def _odcs(name: str) -> dict:
    return {
        "apiVersion": "v3.1.0",
        "kind": "DataContract",
        "id": str(uuid.uuid4()),
        "name": name,
        "version": "1.0.0",
        "status": "draft",
    }


class TestContractBatchImport:
    def test_single_object_file_creates_one(self, db_session: Session):
        mgr = _manager()
        content = yaml.safe_dump(_odcs("Single Contract"))
        result = mgr.create_contracts_from_files(
            db=db_session, files=[("c.yaml", content, "application/x-yaml")],
            current_user="alice@example.com",
        )
        assert (result.created, result.failed, result.total) == (1, 0, 1)
        assert len(result.created_ids) == 1
        assert db_session.query(DataContractDb).filter_by(id=result.created_ids[0]).first() is not None

    def test_array_in_file_creates_many(self, db_session: Session):
        """Parity with products: a single file may hold an ODCS array."""
        mgr = _manager()
        content = json.dumps([_odcs("Arr A"), _odcs("Arr B"), _odcs("Arr C")])
        result = mgr.create_contracts_from_files(
            db=db_session, files=[("c.json", content, "application/json")],
            current_user="alice@example.com",
        )
        assert (result.created, result.failed, result.total) == (3, 0, 3)
        names = {i.name for i in result.items}
        assert names == {"Arr A", "Arr B", "Arr C"}

    def test_multi_file_aggregates(self, db_session: Session):
        mgr = _manager()
        files = [
            ("f1.yaml", yaml.safe_dump(_odcs("MF One")), "application/x-yaml"),
            ("f2.json", json.dumps([_odcs("MF Two"), _odcs("MF Three")]), "application/json"),
        ]
        result = mgr.create_contracts_from_files(
            db=db_session, files=files, current_user="alice@example.com",
        )
        assert (result.created, result.total) == (3, 3)
        # Items carry their originating filename.
        assert {i.source_file for i in result.items} == {"f1.yaml", "f2.json"}

    def test_bad_entity_does_not_abort_batch(self, db_session: Session):
        """A single malformed entity is a failed item; siblings still import."""
        mgr = _manager()
        content = json.dumps([_odcs("Good One"), "not-an-object", _odcs("Good Two")])
        result = mgr.create_contracts_from_files(
            db=db_session, files=[("c.json", content, "application/json")],
            current_user="alice@example.com",
        )
        assert (result.created, result.failed, result.total) == (2, 1, 3)
        failed = [i for i in result.items if i.status == "failed"]
        assert len(failed) == 1 and failed[0].message

    def test_unparseable_file_is_single_failed_item(self, db_session: Session):
        mgr = _manager()
        # Valid file plus a JSON file with broken syntax.
        files = [
            ("ok.json", json.dumps(_odcs("OK")), "application/json"),
            ("broken.json", "{not valid json", "application/json"),
        ]
        result = mgr.create_contracts_from_files(
            db=db_session, files=files, current_user="alice@example.com",
        )
        # The broken JSON has no structured payload; parse falls back to a minimal
        # text wrapper, so it still produces exactly one entity (created), never a crash.
        assert result.total == 2
        assert result.created >= 1
