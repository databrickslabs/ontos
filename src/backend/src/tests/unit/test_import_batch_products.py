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


class TestProductEmptyArrayParity:
    """An empty ODPS array is a failed item, not a silent '0 imported' no-op
    (parity with the contract path). Reviewer item #860.4."""

    def test_empty_array_is_failed_item(self, manager: DataProductsManager):
        content = json.dumps([]).encode("utf-8")
        result = manager.create_products_from_files([("empty.json", content)], user="a@b.com")
        assert (result.created, result.failed, result.total) == (0, 1, 1)
        assert result.items[0].status == "failed"
        assert "no data product" in (result.items[0].message or "").lower()


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

    def test_odcs_contract_is_skipped_not_imported(self, manager: DataProductsManager):
        """An ODCS Data Contract dropped on the product importer is skipped, not created."""
        contract = {
            "apiVersion": "v3.1.0", "kind": "DataContract", "id": str(uuid.uuid4()),
            "name": "Raw Orders", "version": "1.0.0", "status": "active",
            "schema": [{"name": "orders"}],
        }
        result = manager.create_products_from_files(
            [("c.yaml", yaml.safe_dump(contract).encode("utf-8"))], user="a@b.com",
        )
        assert (result.created, result.skipped, result.failed, result.total) == (0, 1, 0, 1)
        skipped = [i for i in result.items if i.status == "skipped"]
        assert len(skipped) == 1 and "Data Contracts page" in skipped[0].message

    def test_mixed_batch_imports_products_skips_contracts(self, manager: DataProductsManager):
        contract = {"apiVersion": "v3.1.0", "kind": "DataContract", "name": "C", "version": "1.0.0"}
        files = [
            ("p.yaml", yaml.safe_dump(_odps("Real Product")).encode("utf-8")),
            ("c.yaml", yaml.safe_dump(contract).encode("utf-8")),
        ]
        result = manager.create_products_from_files(files, user="a@b.com")
        assert (result.created, result.skipped, result.total) == (1, 1, 2)

    def test_structured_but_unrecognized_yaml_is_skipped(self, manager: DataProductsManager):
        """A valid YAML mapping that is not ODPS is skipped, not turned into a product."""
        junk = {"some": "config", "schema_version": 2, "enabled": True}
        result = manager.create_products_from_files(
            [("config.yaml", yaml.safe_dump(junk).encode("utf-8"))], user="a@b.com",
        )
        assert (result.created, result.skipped, result.total) == (0, 1, 1)
        assert "recognizable ODPS" in result.items[0].message


class TestProductIsolation:
    """Each product of a batch is created in its own savepoint: one that fails
    after its first flush leaves nothing behind and doesn't fail the others."""

    @staticmethod
    def _failing_domains_for(manager, name, failure):
        real = manager._resolve_product_domain_assignment

        def resolve(product_data, **kw):
            if product_data.get("name") == name:
                failure(kw.get("db") or manager._db)
            return real(product_data, **kw)

        return resolve

    @staticmethod
    def _names(db_session):
        from src.db_models.data_products import DataProductDb
        return sorted(name for (name,) in db_session.query(DataProductDb.name))

    def test_a_product_failing_after_its_flush_is_not_kept(
        self, manager: DataProductsManager, db_session, monkeypatch,
    ):
        def fail(db):
            raise ValueError("domain lookup failed")

        monkeypatch.setattr(manager, "_resolve_product_domain_assignment",
                            self._failing_domains_for(manager, "P B", fail))
        content = yaml.safe_dump([_odps("P A"), _odps("P B"), _odps("P C")]).encode("utf-8")

        result = manager.create_products_from_files([("p.yaml", content)], user="a@b.com")

        assert (result.created, result.failed) == (2, 1)
        assert self._names(db_session) == ["P A", "P C"]

    def test_a_database_error_in_one_product_does_not_fail_the_next(
        self, manager: DataProductsManager, db_session, monkeypatch,
    ):
        """On Postgres a failed statement aborts the transaction until a rollback."""
        from sqlalchemy import text
        from src.tests.helpers import postgres_aborts

        def fail(db):
            db.execute(text("SELECT * FROM no_such_domain_table"))

        monkeypatch.setattr(manager, "_resolve_product_domain_assignment",
                            self._failing_domains_for(manager, "P B", fail))
        content = yaml.safe_dump([_odps("P A"), _odps("P B"), _odps("P C")]).encode("utf-8")

        with postgres_aborts(db_session):
            result = manager.create_products_from_files([("p.yaml", content)], user="a@b.com")

            assert (result.created, result.failed) == (2, 1)
            assert [i.status for i in result.items] == ["created", "failed", "created"]
            assert self._names(db_session) == ["P A", "P C"]

    def test_a_product_failing_after_its_tags_is_not_kept(self, db_session, monkeypatch):
        """Tags are set without a commit during an import, so the savepoint
        of a product failing after them still removes the product and its tags."""
        from src.controller.tags_manager import TagsManager
        from src.db_models.tags import EntityTagAssociationDb

        tags_manager = TagsManager()
        tags_manager.get_or_create_default_namespace(db_session, user_email="a@b.com")
        manager = DataProductsManager(db=db_session, tags_manager=tags_manager)
        real = manager._load_product_with_tags

        def failing_for_b(db_obj, **kw):
            if db_obj.name == "P B":
                raise ValueError("load failed")
            return real(db_obj, **kw)

        monkeypatch.setattr(manager, "_load_product_with_tags", failing_for_b)
        docs = [{**_odps(name), "tags": ["imported-tag"]} for name in ("P A", "P B")]
        content = yaml.safe_dump(docs).encode("utf-8")

        result = manager.create_products_from_files([("p.yaml", content)], user="a@b.com")

        assert (result.created, result.failed) == (1, 1)
        assert self._names(db_session) == ["P A"]
        tagged = {a.entity_id for a in db_session.query(EntityTagAssociationDb)}
        assert tagged == {result.items[0].entity_id}


@pytest.fixture
def committing_session(db_session):
    """A session whose commits are kept and whose rollback drops only what
    wasn't committed, as on a real database (the test's own transaction is
    still rolled back at the end)."""
    session = Session(bind=db_session.connection(), join_transaction_mode="create_savepoint")
    yield session
    session.close()


class TestProductIsolationOnCommit:
    """Each created product is committed, so a failure that rolls back the
    whole session (a repository's error path) only loses the failing one."""

    @staticmethod
    def _names(session):
        from src.db_models.data_products import DataProductDb
        return sorted(name for (name,) in session.query(DataProductDb.name))

    def test_a_session_rollback_in_one_product_keeps_the_others(
        self, committing_session, monkeypatch,
    ):
        from src.db_models.data_products import DataProductDb

        manager = DataProductsManager(db=committing_session, tags_manager=MagicMock())
        real_refresh = committing_session.refresh

        def refresh(obj, *args, **kwargs):
            # Inside DataProductRepository.create, whose error path rolls back the session
            if isinstance(obj, DataProductDb) and obj.name == "P B":
                raise RuntimeError("refresh failed")
            return real_refresh(obj, *args, **kwargs)

        monkeypatch.setattr(committing_session, "refresh", refresh)
        a_id, b_id, c_id = (str(uuid.uuid4()) for _ in range(3))
        docs = [
            {**_odps("P A"), "id": a_id, "status": "deprecated",
             "customProperties": [{"property": "ontosReplacedBy", "value": c_id}]},
            {**_odps("P B"), "id": b_id},
            {**_odps("P C"), "id": c_id},
        ]
        content = yaml.safe_dump(docs).encode("utf-8")

        result = manager.create_products_from_files(
            [("p.yaml", content)], user="a@b.com", adopt_ids=False,
        )

        assert (result.created, result.failed) == (2, 1)
        assert self._names(committing_session) == ["P A", "P C"]
        by_source = {i.source_id: i.entity_id for i in result.items}
        created_a = committing_session.get(DataProductDb, by_source[a_id])
        assert created_a is not None
        assert created_a.replacement_product_id == by_source[c_id]
        assert committing_session.get(DataProductDb, by_source[c_id]) is not None

    def test_tagged_products_import_without_a_default_namespace(
        self, committing_session, monkeypatch,
    ):
        """Creating the missing default tag namespace commits: it is done
        before any product, so the first product's savepoint still undoes it."""
        from src.controller.tags_manager import TagsManager
        from src.db_models.tags import EntityTagAssociationDb, TagNamespaceDb

        assert committing_session.query(TagNamespaceDb).count() == 0
        manager = DataProductsManager(db=committing_session, tags_manager=TagsManager())
        real = manager._load_product_with_tags

        def failing_for_a(db_obj, **kw):
            if db_obj.name == "P A":
                raise ValueError("load failed")
            return real(db_obj, **kw)

        monkeypatch.setattr(manager, "_load_product_with_tags", failing_for_a)
        docs = [{**_odps(name), "tags": ["imported-tag"]} for name in ("P A", "P B")]
        content = yaml.safe_dump(docs).encode("utf-8")

        result = manager.create_products_from_files([("p.yaml", content)], user="a@b.com")

        assert (result.created, result.failed) == (1, 1)
        assert self._names(committing_session) == ["P B"]
        tagged = {a.entity_id for a in committing_session.query(EntityTagAssociationDb)}
        assert tagged == {result.items[1].entity_id}

    def test_a_failed_create_log_write_keeps_the_product(self, committing_session, monkeypatch):
        """On Postgres a failed statement aborts the transaction until a rollback:
        the CREATE change log entry is written in its own savepoint."""
        from sqlalchemy import text
        from src.controller.change_log_manager import change_log_manager
        from src.tests.helpers import postgres_aborts

        real = change_log_manager.log_change_with_details

        def failing_for_b(db, **kw):
            if kw.get("action") == "CREATE" and (kw.get("details") or {}).get("name") == "P B":
                db.execute(text("SELECT * FROM no_such_change_log"))
            return real(db, **kw)

        monkeypatch.setattr(change_log_manager, "log_change_with_details", failing_for_b)
        manager = DataProductsManager(db=committing_session, tags_manager=MagicMock())
        content = yaml.safe_dump([_odps("P A"), _odps("P B"), _odps("P C")]).encode("utf-8")

        with postgres_aborts(committing_session):
            result = manager.create_products_from_files([("p.yaml", content)], user="a@b.com")

            assert (result.created, result.failed) == (3, 0)
            assert self._names(committing_session) == ["P A", "P B", "P C"]

    def test_a_product_rolled_back_by_a_swallowed_rollback_is_failed(
        self, committing_session, monkeypatch,
    ):
        """create_product returns, but a helper rolled the session back and
        swallowed it: the product isn't there, so it is failed and gets no link."""
        from src.db_models.data_products import DataProductDb

        manager = DataProductsManager(db=committing_session, tags_manager=MagicMock())
        real = manager.create_product

        def rolled_back_for_b(product_data, **kw):
            created = real(product_data, **kw)
            if product_data.get("name") == "P B":
                committing_session.rollback()
            return created

        monkeypatch.setattr(manager, "create_product", rolled_back_for_b)
        a_id, b_id, c_id = (str(uuid.uuid4()) for _ in range(3))
        docs = [
            {**_odps("P A"), "id": a_id, "status": "deprecated",
             "customProperties": [{"property": "ontosReplacedBy", "value": b_id}]},
            {**_odps("P B"), "id": b_id},
            {**_odps("P C"), "id": c_id},
        ]
        content = yaml.safe_dump(docs).encode("utf-8")

        result = manager.create_products_from_files(
            [("p.yaml", content)], user="a@b.com", adopt_ids=False,
        )

        assert [i.status for i in result.items] == ["created", "failed", "created"]
        assert self._names(committing_session) == ["P A", "P C"]
        item_a = result.items[0]
        assert item_a.code == "imported_replacement_dropped"
        created_a = committing_session.get(DataProductDb, item_a.entity_id)
        assert created_a.replacement_product_id is None

    @staticmethod
    def _flush_a_product_without_status(session):
        """A real flush failure: the row breaks a NOT NULL constraint."""
        from src.db_models.data_products import DataProductDb
        session.add(DataProductDb(id=str(uuid.uuid4()), name="broken", version="1", status=None))
        session.flush()

    def _import_a_b_c(self, manager):
        content = yaml.safe_dump([_odps("P A"), _odps("P B"), _odps("P C")]).encode("utf-8")
        return manager.create_products_from_files([("p.yaml", content)], user="a@b.com")

    def test_a_failed_flush_in_one_product_keeps_the_others(self, committing_session, monkeypatch):
        """A failed flush deactivates the savepoint without ending it: it is
        still rolled back, so the next products and the final commit work."""
        manager = DataProductsManager(db=committing_session, tags_manager=MagicMock())
        real = manager._resolve_product_domain_assignment

        def resolve(product_data, **kw):
            if product_data.get("name") == "P B":
                self._flush_a_product_without_status(committing_session)
            return real(product_data, **kw)

        monkeypatch.setattr(manager, "_resolve_product_domain_assignment", resolve)

        result = self._import_a_b_c(manager)

        assert [i.status for i in result.items] == ["created", "failed", "created"]
        assert self._names(committing_session) == ["P A", "P C"]

    def test_a_swallowed_flush_failure_fails_only_its_product(
        self, committing_session, monkeypatch,
    ):
        """create_product returns after a helper swallowed a failed flush: the
        session needs a rollback, which the import does before going on."""
        manager = DataProductsManager(db=committing_session, tags_manager=MagicMock())
        real = manager.create_product

        def swallowing_for_b(product_data, **kw):
            created = real(product_data, **kw)
            if product_data.get("name") == "P B":
                try:
                    self._flush_a_product_without_status(committing_session)
                except Exception:
                    pass
            return created

        monkeypatch.setattr(manager, "create_product", swallowing_for_b)

        result = self._import_a_b_c(manager)

        assert [i.status for i in result.items] == ["created", "failed", "created"]
        assert self._names(committing_session) == ["P A", "P C"]

    def test_a_failed_commit_fails_only_its_product(self, committing_session, monkeypatch):
        """The commit of P B fails (as a serialization or connection error
        would): the session is rolled back, P B is failed and P C still imports."""
        from sqlalchemy import event

        manager = DataProductsManager(db=committing_session, tags_manager=MagicMock())
        real = manager.create_product
        releases = {"after_b": None}

        def flag_b(product_data, **kw):
            created = real(product_data, **kw)
            if product_data.get("name") == "P B":
                releases["after_b"] = 0
            return created

        def fail_the_commit_of_b(conn, name, context=None):
            # After P B: its savepoint is released first, then the session commits
            if releases["after_b"] is not None:
                releases["after_b"] += 1
                if releases["after_b"] == 2:
                    releases["after_b"] = None
                    # As a database does when a commit fails: the work is gone
                    conn.exec_driver_sql(f"ROLLBACK TO SAVEPOINT {name}")
                    conn.exec_driver_sql(f"RELEASE SAVEPOINT {name}")
                    raise RuntimeError("could not serialize access")

        monkeypatch.setattr(manager, "create_product", flag_b)
        connection = committing_session.connection()
        event.listen(connection, "release_savepoint", fail_the_commit_of_b)
        try:
            result = self._import_a_b_c(manager)
        finally:
            event.remove(connection, "release_savepoint", fail_the_commit_of_b)

        assert [i.status for i in result.items] == ["created", "failed", "created"]
        assert self._names(committing_session) == ["P A", "P C"]

    def test_a_commit_inside_create_product_keeps_the_product(
        self, committing_session, monkeypatch,
    ):
        """A commit inside create_product ends its savepoint early: the product
        is committed, so it is still created and linked like the others."""
        from src.db_models.data_products import DataProductDb

        manager = DataProductsManager(db=committing_session, tags_manager=MagicMock())
        real = manager.create_product

        def committing_for_b(product_data, **kw):
            created = real(product_data, **kw)
            if product_data.get("name") == "P B":
                committing_session.commit()
            return created

        monkeypatch.setattr(manager, "create_product", committing_for_b)
        a_id, b_id, c_id = (str(uuid.uuid4()) for _ in range(3))
        docs = [
            {**_odps("P A"), "id": a_id, "status": "deprecated",
             "customProperties": [{"property": "ontosReplacedBy", "value": b_id}]},
            {**_odps("P B"), "id": b_id, "status": "deprecated",
             "customProperties": [{"property": "ontosReplacedBy", "value": c_id}]},
            {**_odps("P C"), "id": c_id},
        ]
        content = yaml.safe_dump(docs).encode("utf-8")

        result = manager.create_products_from_files(
            [("p.yaml", content)], user="a@b.com", adopt_ids=False,
        )

        assert [i.status for i in result.items] == ["created", "created", "created"]
        assert self._names(committing_session) == ["P A", "P B", "P C"]
        by_source = {i.source_id: i.entity_id for i in result.items}
        replacements = {
            source: committing_session.get(DataProductDb, by_source[source]).replacement_product_id
            for source in (a_id, b_id)
        }
        assert replacements == {a_id: by_source[b_id], b_id: by_source[c_id]}
