"""Tags given when a contract is created are assigned (#1484).

`DataContractCreate` accepts `tags` and the Create Contract dialog sends them, but
`create_contract_with_relations` never read them, so a new contract had no tags.
ODCS uploads wrote the file's tags only to the legacy ODCS tag table, which the
contract page doesn't show, and new versions didn't copy the tags the page shows.
"""
import uuid
from pathlib import Path
from unittest.mock import patch

import pytest
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from src.controller.data_contracts_manager import DataContractsManager
from src.controller.tags_manager import TagsManager
from src.db_models.data_contracts import DataContractDb, DataContractTagDb
from src.db_models.tags import EntityTagAssociationDb, TagDb
from src.models.data_contracts_api import DataContractCreate
from src.models.tags import DEFAULT_NAMESPACE_NAME
from src.repositories.tags_repository import tag_namespace_repo


def _manager(tags_manager=None):
    mgr = DataContractsManager(data_dir=Path("/tmp"), tags_manager=tags_manager or TagsManager())
    mgr._queue_delivery = lambda *a, **k: None
    mgr._update_search_index = lambda *a, **k: None
    return mgr


@pytest.fixture
def tags(db_session: Session):
    namespace = tag_namespace_repo.get_or_create_default_namespace(db_session, user_email="admin@example.com")
    made = []
    for prefix in ("classification", "region"):
        tag = TagDb(name=f"{prefix}_{uuid.uuid4().hex[:8]}", namespace_id=namespace.id, status="active")
        db_session.add(tag)
        made.append(tag)
    db_session.commit()
    return made


def _fqn(tag: TagDb) -> str:
    return f"{tag.namespace.name}/{tag.name}"


def _assigned(db_session: Session, contract_id: str) -> dict:
    rows = (
        db_session.query(TagDb.name, EntityTagAssociationDb.assigned_value)
        .join(EntityTagAssociationDb, EntityTagAssociationDb.tag_id == TagDb.id)
        .filter(
            EntityTagAssociationDb.entity_type == "data_contract",
            EntityTagAssociationDb.entity_id == str(contract_id),
        )
        .all()
    )
    return {name: value for name, value in rows}


def _name() -> str:
    return f"Contract {uuid.uuid4().hex[:8]}"


class TestCreateWithRelations:
    def test_tags_from_the_payload_are_assigned(self, db_session: Session, tags):
        classification, region = tags

        created = _manager().create_contract_with_relations(
            db=db_session,
            contract_data={
                "name": _name(),
                "tags": [_fqn(classification), {"tag_fqn": _fqn(region), "assigned_value": "eu"}],
            },
            current_user="alice@example.com",
        )

        assert _assigned(db_session, created.id) == {classification.name: None, region.name: "eu"}

    def test_the_dialog_payload_assigns_its_tags(self, db_session: Session, tags):
        # The dialog sends FQN strings; the route passes the validated model.
        classification, region = tags
        payload = DataContractCreate(name=_name(), tags=[_fqn(classification), _fqn(region)])

        created = _manager().create_contract_with_relations(
            db=db_session, contract_data=payload, current_user="alice@example.com",
        )

        assert set(_assigned(db_session, created.id)) == {classification.name, region.name}

    def test_an_unknown_tag_name_is_created_as_on_update(self, db_session: Session):
        name = f"new_{uuid.uuid4().hex[:8]}"

        created = _manager().create_contract_with_relations(
            db=db_session, contract_data={"name": _name(), "tags": [name]}, current_user="alice@example.com",
        )

        assert _assigned(db_session, created.id) == {name: None}

    def test_a_tag_in_an_unknown_namespace_is_skipped_alone(self, db_session: Session, tags):
        classification, region = tags

        created = _manager().create_contract_with_relations(
            db=db_session,
            contract_data={
                "name": _name(),
                "tags": [_fqn(classification), f"nowhere_{uuid.uuid4().hex[:6]}/x", _fqn(region)],
            },
            current_user="alice@example.com",
        )

        assert set(_assigned(db_session, created.id)) == {classification.name, region.name}

    def test_a_missing_default_namespace_is_created_in_the_create(self, db_session: Session):
        assert tag_namespace_repo.get_by_name(db_session, name=DEFAULT_NAMESPACE_NAME) is None
        name = f"brand_new_{uuid.uuid4().hex[:6]}"

        created = _manager().create_contract_with_relations(
            db=db_session, contract_data={"name": _name(), "tags": [name]}, current_user="alice@example.com",
        )

        assert db_session.get(DataContractDb, created.id) is not None
        assert tag_namespace_repo.get_by_name(db_session, name=DEFAULT_NAMESPACE_NAME) is not None
        assert _assigned(db_session, created.id) == {name: None}

    def test_an_unknown_tag_id_is_skipped(self, db_session: Session, tags):
        classification, _ = tags

        created = _manager().create_contract_with_relations(
            db=db_session,
            contract_data={"name": _name(), "tags": [{"tag_id": str(uuid.uuid4())}, _fqn(classification)]},
            current_user="alice@example.com",
        )

        assert _assigned(db_session, created.id) == {classification.name: None}

    @pytest.mark.parametrize("tags_value", [None, []])
    def test_no_tags_is_fine(self, db_session: Session, tags_value):
        data = {"name": _name()}
        if tags_value is not None:
            data["tags"] = tags_value

        created = _manager().create_contract_with_relations(
            db=db_session, contract_data=data, current_user="alice@example.com",
        )

        assert _assigned(db_session, created.id) == {}

    def test_a_tag_failure_does_not_fail_the_create(self, db_session: Session, tags):
        manager = _manager()
        with patch.object(manager._tags_manager, "set_tags_for_entity", side_effect=SQLAlchemyError("boom")):
            created = manager.create_contract_with_relations(
                db=db_session,
                contract_data={"name": _name(), "tags": [_fqn(tags[0])]},
                current_user="alice@example.com",
            )

        assert db_session.get(DataContractDb, created.id) is not None
        assert _assigned(db_session, created.id) == {}

    def test_without_a_tags_manager_the_create_still_works(self, db_session: Session, tags):
        manager = DataContractsManager(data_dir=Path("/tmp"))
        manager._queue_delivery = lambda *a, **k: None
        manager._update_search_index = lambda *a, **k: None

        created = manager.create_contract_with_relations(
            db=db_session, contract_data={"name": _name(), "tags": [_fqn(tags[0])]}, current_user="alice@example.com",
        )

        assert db_session.get(DataContractDb, created.id) is not None


class TestOdcsCreatePaths:
    def _doc(self, tag_names):
        return {
            "apiVersion": "v3.1.0", "kind": "DataContract", "id": str(uuid.uuid4()),
            "name": _name(), "version": "1.0.0", "status": "draft", "tags": tag_names,
        }

    def test_upload_assigns_the_files_tags(self, db_session: Session, tags):
        classification, _ = tags
        new_name = f"imported_{uuid.uuid4().hex[:8]}"

        created = _manager().create_from_upload(
            db_session, self._doc([classification.name, new_name]), current_user="alice",
        )
        db_session.commit()

        assert set(_assigned(db_session, created.id)) == {classification.name, new_name}
        # ODCS export still reads the file's tags from the ODCS tag table.
        legacy = {t.name for t in db_session.query(DataContractTagDb).filter_by(contract_id=created.id)}
        assert legacy == {classification.name, new_name}

    def test_create_from_odcs_dict_assigns_the_tags(self, db_session: Session, tags):
        classification, _ = tags

        created = _manager().create_from_odcs_dict(db_session, self._doc([classification.name]), "alice")
        db_session.commit()

        assert _assigned(db_session, created.id) == {classification.name: None}


    def test_a_batch_import_assigns_each_files_tags(self, db_session: Session, tags):
        import json

        classification, region = tags
        files = [
            ("a.json", json.dumps(self._doc([classification.name])), "application/json"),
            ("b.json", json.dumps(self._doc([region.name])), "application/json"),
        ]

        result = _manager().create_contracts_from_files(db=db_session, files=files, current_user="alice")

        assert (result.created, result.failed) == (2, 0)
        assigned = [_assigned(db_session, cid) for cid in result.created_ids]
        assert sorted(next(iter(a)) for a in assigned) == sorted([classification.name, region.name])


class TestExportAndSearch:
    def test_export_lists_the_tags_of_a_dialog_created_contract(self, db_session: Session, tags):
        classification, _ = tags
        manager = _manager()
        created = manager.create_contract_with_relations(
            db=db_session, contract_data={"name": _name(), "tags": [_fqn(classification)]},
            current_user="alice@example.com",
        )

        odcs = manager.build_odcs_from_db(db_session.get(DataContractDb, created.id), db_session)

        assert odcs["tags"] == [classification.name]

    def test_export_writes_other_namespaces_with_their_name(self, db_session: Session):
        from src.db_models.tags import TagNamespaceDb

        ns = TagNamespaceDb(name=f"gov_{uuid.uuid4().hex[:6]}")
        db_session.add(ns)
        db_session.commit()
        manager = _manager()
        created = manager.create_contract_with_relations(
            db=db_session, contract_data={"name": _name(), "tags": [f"{ns.name}/restricted"]},
            current_user="alice@example.com",
        )

        odcs = manager.build_odcs_from_db(db_session.get(DataContractDb, created.id), db_session)

        assert odcs["tags"] == [f"{ns.name}/restricted"]

    def test_export_of_an_upload_keeps_the_file_tags(self, db_session: Session, tags):
        classification, _ = tags
        manager = _manager()
        doc = {
            "apiVersion": "v3.1.0", "kind": "DataContract", "id": str(uuid.uuid4()),
            "name": _name(), "version": "1.0.0", "status": "draft", "tags": [classification.name],
        }
        created = manager.create_from_upload(db_session, doc, current_user="alice")
        db_session.commit()

        odcs = manager.build_odcs_from_db(db_session.get(DataContractDb, created.id), db_session)

        assert odcs["tags"] == [classification.name]

    def test_search_lists_an_uploaded_tag_once(self, db_session: Session, tags):
        classification, _ = tags
        manager = DataContractsManager(data_dir=Path("/tmp"), tags_manager=TagsManager())
        manager._queue_delivery = lambda *a, **k: None
        doc = {
            "apiVersion": "v3.1.0", "kind": "DataContract", "id": str(uuid.uuid4()),
            "name": _name(), "version": "1.0.0", "status": "draft", "tags": [classification.name],
        }
        created = manager.create_from_upload(db_session, doc, current_user="alice")
        db_session.commit()

        item = manager._build_search_index_item(db_session.get(DataContractDb, created.id), db_session)

        assert item.tags == [_fqn(classification)]


class TestNewVersions:
    @pytest.fixture
    def tagged_contract(self, db_session: Session, tags):
        classification, region = tags
        manager = _manager()
        created = manager.create_contract_with_relations(
            db=db_session,
            contract_data={
                "name": _name(), "version": "1.0.0",
                "tags": [_fqn(classification), {"tag_fqn": _fqn(region), "assigned_value": "eu"}],
            },
            current_user="alice@example.com",
        )
        return manager, created.id, {classification.name: None, region.name: "eu"}

    def test_a_deep_clone_keeps_the_tags_and_values(self, db_session: Session, tagged_contract):
        manager, cid, expected = tagged_contract

        new = manager.clone_contract_for_new_version(db_session, cid, "2.0.0", current_user="bob")

        assert _assigned(db_session, new.id) == expected
        assert _assigned(db_session, cid) == expected

    def test_a_lightweight_new_version_keeps_the_tags_and_values(self, db_session: Session, tagged_contract):
        manager, cid, expected = tagged_contract

        new = manager.create_new_version(db_session, cid, "2.0.0", current_user="bob")

        assert _assigned(db_session, new.id) == expected

    def test_a_new_version_records_who_copied_the_tags(self, db_session: Session, tagged_contract):
        manager, cid, _ = tagged_contract

        new = manager.create_new_version(db_session, cid, "2.0.0", current_user="bob")

        assigned_by = {
            a.assigned_by
            for a in db_session.query(EntityTagAssociationDb).filter_by(
                entity_type="data_contract", entity_id=str(new.id)
            )
        }
        assert assigned_by == {"bob"}
