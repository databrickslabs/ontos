"""Unit tests for the direct-read gate on data products (ONT-NEG-011).

A consumer could read an unpublished (draft) product by id via
GET /api/data-products/{id}. The gate must allow published products to
everyone but restrict unpublished ones to admins and owners.
"""
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from src.routes.data_product_routes import _caller_can_read_product


def _request(*, is_admin: bool):
    auth_manager = MagicMock()
    auth_manager.get_user_effective_permissions.return_value = {}
    auth_manager.has_permission.return_value = is_admin
    request = MagicMock()
    request.app.state.authorization_manager = auth_manager
    request.app.state.settings_manager = None
    return request


def _user(email="consumer@example.com"):
    return SimpleNamespace(email=email, groups=[])


class TestProductReadGate:
    def test_published_product_readable_by_anyone(self):
        manager = MagicMock()
        # Even if the accessible set is empty, a published product is readable.
        manager.list_products.return_value = []
        product = SimpleNamespace(id="p1", status="active")

        assert _caller_can_read_product(
            _request(is_admin=False), MagicMock(), _user(), manager, product
        ) is True
        # Published short-circuit: we never needed to scope the listing.
        manager.list_products.assert_not_called()

    def test_draft_denied_for_non_owner_non_admin(self):
        manager = MagicMock()
        product = SimpleNamespace(
            id="p1", status="draft", draft_owner_id="someone-else@example.com",
            owner_team_id=None, project_id=None,
        )

        assert _caller_can_read_product(
            _request(is_admin=False), MagicMock(), _user(), manager, product
        ) is False

    def test_draft_allowed_for_feature_admin(self):
        manager = MagicMock()
        product = SimpleNamespace(
            id="p1", status="draft", draft_owner_id="someone-else@example.com",
            owner_team_id=None, project_id=None,
        )

        assert _caller_can_read_product(
            _request(is_admin=True), MagicMock(), _user(), manager, product
        ) is True

    def test_draft_allowed_for_draft_owner(self):
        # Creator ownership: draft_owner_id matches the caller (case-insensitive).
        manager = MagicMock()
        product = SimpleNamespace(
            id="p1", status="draft", draft_owner_id="Consumer@Example.com",
            owner_team_id=None, project_id=None,
        )

        assert _caller_can_read_product(
            _request(is_admin=False), MagicMock(), _user(), manager, product
        ) is True
        # The gate must decide from the product's own ownership facts, never
        # by trusting the broad listing scope (ONT-NEG-011 follow-up).
        manager.list_products.assert_not_called()


class TestProductReadGateSubstringAdminLeak:
    """Regression for the gap that made PR #535 ineffective (ONT-NEG-011).

    The prior gate resolved the caller's project scope via
    ``projects_manager.get_user_projects``, whose admin check treats *any*
    group whose name merely CONTAINS the substring "admin" as a global admin
    and returns EVERY project. A Data Consumer in a group like
    ``account-admins`` (which is NOT a configured app-admin group) therefore
    got every project in scope, matched the draft's ``project_id`` in
    ``list_products``, and read the draft — exactly the leak NEG-011 reports.

    These tests exercise the REAL gate against a real DB + real managers.
    """

    def _make_product(self, db, *, status, draft_owner_id=None, owner_team_id=None, project_id=None):
        import uuid
        from src.db_models.data_products import DataProductDb

        p = DataProductDb(
            id=str(uuid.uuid4()), api_version="v1.0.0", kind="DataProduct",
            status=status, name="p", version="1.0.0",
            draft_owner_id=draft_owner_id, owner_team_id=owner_team_id, project_id=project_id,
        )
        db.add(p); db.commit(); db.refresh(p)
        return p

    def _gate(self, db, product_id, *, email, groups, is_admin=False):
        from src.controller.data_products_manager import DataProductsManager

        manager = DataProductsManager(db=db)
        product = manager.get_product(product_id)
        auth_manager = MagicMock()
        auth_manager.get_user_effective_permissions.return_value = {}
        auth_manager.has_permission.return_value = is_admin
        request = MagicMock()
        request.app.state.authorization_manager = auth_manager
        request.app.state.settings_manager = None
        user = SimpleNamespace(email=email, groups=groups)
        return _caller_can_read_product(request, db, user, manager, product)

    def test_consumer_in_admin_substring_group_denied_draft_in_unowned_project(self, db_session):
        """The exact NEG-011 leak: consumer in an 'admin'-named (but not
        app-admin) group must NOT read a draft living in a project they are
        not a member of."""
        from src.db_models.projects import ProjectDb

        db_session.add(ProjectDb(
            id="proj-secret", name="secret-proj", project_type="TEAM",
            created_by="owner@example.com", updated_by="owner@example.com",
        ))
        db_session.commit()
        draft = self._make_product(
            db_session, status="draft",
            draft_owner_id="owner@example.com", project_id="proj-secret",
        )

        assert self._gate(
            db_session, draft.id,
            email="consumer@example.com", groups=["account-admins"],
        ) is False

    def test_published_in_unowned_project_still_readable(self, db_session):
        """Published products remain readable by anyone (catalog contract)."""
        from src.db_models.projects import ProjectDb

        db_session.add(ProjectDb(
            id="proj-pub", name="pub-proj", project_type="TEAM",
            created_by="owner@example.com", updated_by="owner@example.com",
        ))
        db_session.commit()
        active = self._make_product(
            db_session, status="active",
            draft_owner_id="owner@example.com", project_id="proj-pub",
        )

        assert self._gate(
            db_session, active.id,
            email="consumer@example.com", groups=["account-admins"],
        ) is True

    def test_draft_owner_can_read_own_draft(self, db_session):
        draft = self._make_product(
            db_session, status="draft", draft_owner_id="creator@example.com",
        )
        assert self._gate(
            db_session, draft.id, email="creator@example.com", groups=[],
        ) is True
