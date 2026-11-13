"""New product versions keep the tag assignments of their source, with values (#1489).

Both new-version paths are covered: ``create_new_version`` (the "Create New
Version" button, ``POST /versions``) and ``clone_product_for_new_version``
(the personal draft from "Clone for Editing").
"""
import uuid

import pytest
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from src.controller.data_products_manager import DataProductsManager
from src.db_models.data_products import DataProductDb
from src.db_models.tags import EntityTagAssociationDb, TagDb, TagNamespaceDb
from src.models.data_products import NewVersionRequest
from src.repositories.tags_repository import entity_tag_repo


def _suffix() -> str:
    return uuid.uuid4().hex[:8]


@pytest.fixture
def tags(db_session: Session) -> dict:
    namespace = TagNamespaceDb(name=f"versiontags-{_suffix()}")
    db_session.add(namespace)
    db_session.flush()
    made = {}
    for name in ("tier", "owner-group"):
        tag = TagDb(name=f"{name}-{_suffix()}", namespace_id=namespace.id, status="active")
        db_session.add(tag)
        made[name] = tag
    db_session.flush()
    return made


def _product(db: Session) -> DataProductDb:
    product = DataProductDb(
        id=str(uuid.uuid4()),
        api_version="v1.0.0",
        kind="DataProduct",
        status="active",
        name=f"tagged-product-{_suffix()}",
        version="1.0.0",
        tenant=None,
        owner_team_id=None,
        max_level_inheritance=99,
    )
    db.add(product)
    db.flush()
    return product


def _assign(db: Session, product_id: str, tag: TagDb, value=None) -> None:
    db.add(EntityTagAssociationDb(
        tag_id=tag.id, entity_id=product_id, entity_type="data_product", assigned_value=value,
    ))
    db.flush()


def _assignments(db: Session, product_id: str) -> list:
    # Sessions don't autoflush; get_db commits at the end of a request, so
    # flush here to see the rows the manager has written but not committed.
    db.flush()
    rows = db.query(EntityTagAssociationDb).filter_by(
        entity_id=str(product_id), entity_type="data_product",
    ).all()
    return sorted((str(r.tag_id), r.assigned_value) for r in rows)


def _versions_of(db: Session, source_id: str) -> list:
    """Products that are versions of ``source_id``, pending or committed (a failed copy leaves none)."""
    db.flush()
    return db.query(DataProductDb).filter_by(parent_product_id=str(source_id)).all()


class TestCloneForNewVersion:
    def test_new_version_keeps_every_tag_with_its_value(self, db_session: Session, tags: dict):
        src = _product(db_session)
        _assign(db_session, src.id, tags["tier"], "gold")
        _assign(db_session, src.id, tags["owner-group"], None)

        cloned = DataProductsManager(db=db_session).clone_product_for_new_version(
            db=db_session, product_id=src.id, new_version="2.0.0", current_user="owner@example.com",
        )

        expected = _assignments(db_session, src.id)
        assert len(expected) == 2
        assert _assignments(db_session, cloned.id) == expected

    def test_source_without_tags_clones_without_tags(self, db_session: Session):
        src = _product(db_session)

        cloned = DataProductsManager(db=db_session).clone_product_for_new_version(
            db=db_session, product_id=src.id, new_version="2.0.0",
        )

        assert _assignments(db_session, cloned.id) == []

    def test_failed_tag_copy_fails_the_clone(self, db_session: Session, tags: dict, monkeypatch):
        src = _product(db_session)
        _assign(db_session, src.id, tags["tier"], "gold")

        def broken(*args, **kwargs):
            raise SQLAlchemyError("tag copy broke")

        monkeypatch.setattr(entity_tag_repo, "add_tag_to_entity", broken)

        with pytest.raises(SQLAlchemyError):
            DataProductsManager(db=db_session).clone_product_for_new_version(
                db=db_session, product_id=src.id, new_version="2.0.0",
            )
        assert _versions_of(db_session, src.id) == []


class TestCreateNewVersion:
    """The "Create New Version" button goes through ``create_new_version``."""

    def test_new_version_keeps_every_tag_with_its_value(self, db_session: Session, tags: dict):
        src = _product(db_session)
        _assign(db_session, src.id, tags["tier"], "gold")
        _assign(db_session, src.id, tags["owner-group"], None)

        created = DataProductsManager(db=db_session).create_new_version(
            src.id, NewVersionRequest(new_version="2.0.0"),
        )

        # The manager's session is the startup singleton, not the request's:
        # nothing commits it after the call, so the manager must commit itself.
        assert not db_session.new, "create_new_version left writes uncommitted"
        expected = _assignments(db_session, src.id)
        assert len(expected) == 2
        assert _assignments(db_session, created.id) == expected

    def test_failed_tag_copy_fails_the_new_version(self, db_session: Session, tags: dict, monkeypatch):
        src = _product(db_session)
        _assign(db_session, src.id, tags["tier"], "gold")

        def broken(*args, **kwargs):
            raise SQLAlchemyError("tag copy broke")

        monkeypatch.setattr(entity_tag_repo, "add_tag_to_entity", broken)

        with pytest.raises(SQLAlchemyError):
            DataProductsManager(db=db_session).create_new_version(
                src.id, NewVersionRequest(new_version="2.0.0"),
            )
        assert _versions_of(db_session, src.id) == []

    def test_failed_domain_copy_leaves_no_version(self, db_session: Session, monkeypatch):
        """A failure after the product row is flushed rolls the version back too."""
        from src.repositories import entity_domain_association_repository as domain_mod

        src = _product(db_session)
        mgr = DataProductsManager(db=db_session)
        monkeypatch.setattr(mgr, "_resolve_product_domain_assignment", lambda data, **kw: (["d-1"], "d-1"))

        def broken(*args, **kwargs):
            raise SQLAlchemyError("domain write broke")

        monkeypatch.setattr(domain_mod.entity_domain_repo, "set_domains_for_entity", broken)

        with pytest.raises(SQLAlchemyError):
            mgr.create_new_version(src.id, NewVersionRequest(new_version="2.0.0"))

        assert _versions_of(db_session, src.id) == []

    def test_source_without_tags_gets_no_tags(self, db_session: Session):
        src = _product(db_session)

        created = DataProductsManager(db=db_session).create_new_version(
            src.id, NewVersionRequest(new_version="2.0.0"),
        )

        assert _assignments(db_session, created.id) == []
