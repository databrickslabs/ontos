"""
Unit tests for data-product ownership scope (PR D).

Closes two related authz gaps:
  1. ``DataProductsRepository.get_multi`` returned every product to every
     non-admin caller when no project_id was supplied.
  2. ``DataProductsManager.update_product_with_auth`` only enforced project
     membership when ``existing.project_id`` was set; otherwise no check.

The fix applies an ownership cascade to BOTH list and update paths:
  admin → project_id ∈ caller_projects → owner_team_id ∈ caller_teams
        → draft_owner_id == caller_email → deny.

These tests exercise the cascade end-to-end at the repository + manager
layers, and cover the regression-guard cases (admin still sees all, legacy
orphans fail-closed for non-admins).
"""
import uuid
from unittest.mock import MagicMock, patch

import pytest
from sqlalchemy.orm import Session

from src.controller.data_products_manager import DataProductsManager
from src.db_models.data_products import DataProductDb
from src.repositories.data_products_repository import data_product_repo


# ----------------------------------------------------------------------------
# Helpers
# ----------------------------------------------------------------------------


def _make_product(
    db: Session,
    *,
    name: str,
    status: str = "active",
    project_id=None,
    owner_team_id=None,
    draft_owner_id=None,
) -> DataProductDb:
    """Insert a DataProductDb row directly with chosen ownership columns.

    Bypasses the API model so we can populate ``owner_team_id`` /
    ``draft_owner_id`` without driving full ODPS validation. SQLite FK
    enforcement is off in the test harness, so arbitrary string IDs are
    fine.
    """
    product = DataProductDb(
        id=str(uuid.uuid4()),
        api_version="v1.0.0",
        kind="DataProduct",
        status=status,
        name=name,
        version="1.0.0",
        project_id=project_id,
        owner_team_id=owner_team_id,
        draft_owner_id=draft_owner_id,
    )
    db.add(product)
    db.commit()
    db.refresh(product)
    return product


# ----------------------------------------------------------------------------
# Repository: get_multi ownership scope
# ----------------------------------------------------------------------------


class TestGetMultiOwnershipScope:
    """Cover the SQL-level filter in
    :py:meth:`DataProductsRepository.get_multi`."""

    def test_admin_sees_all(self, db_session: Session):
        _make_product(db_session, name="A", project_id="proj-A")
        _make_product(db_session, name="B", owner_team_id="team-B")
        _make_product(db_session, name="C", draft_owner_id="someone@example.com")
        _make_product(db_session, name="D")  # orphan

        result = data_product_repo.get_multi(db=db_session, is_admin=True)
        assert {p.name for p in result} == {"A", "B", "C", "D"}

    def test_admin_with_no_scope_inputs_still_sees_all(self, db_session: Session):
        """Regression guard: admin path must NOT require scope inputs."""
        _make_product(db_session, name="A")
        _make_product(db_session, name="B", owner_team_id="team-B")

        result = data_product_repo.get_multi(db=db_session, is_admin=True)
        assert len(result) == 2

    def test_non_admin_with_no_scope_fails_closed(self, db_session: Session):
        """Back-compat call sites without scope must NOT leak products."""
        _make_product(db_session, name="A", owner_team_id="team-B")
        _make_product(db_session, name="B", project_id="proj-X")

        result = data_product_repo.get_multi(db=db_session, is_admin=False)
        assert result == []

    def test_non_admin_sees_only_owned_via_project(self, db_session: Session):
        _make_product(db_session, name="mine", project_id="proj-A")
        _make_product(db_session, name="theirs", project_id="proj-B")

        result = data_product_repo.get_multi(
            db=db_session,
            is_admin=False,
            caller_email="alice@example.com",
            caller_project_ids=["proj-A"],
        )
        assert {p.name for p in result} == {"mine"}

    def test_non_admin_sees_only_owned_via_team(self, db_session: Session):
        _make_product(db_session, name="mine", owner_team_id="team-A")
        _make_product(db_session, name="theirs", owner_team_id="team-B")

        result = data_product_repo.get_multi(
            db=db_session,
            is_admin=False,
            caller_email="alice@example.com",
            caller_team_ids=["team-A"],
        )
        assert {p.name for p in result} == {"mine"}

    def test_non_admin_sees_only_owned_via_draft_owner(self, db_session: Session):
        """Creator ownership covers BOTH drafts and non-drafts."""
        _make_product(
            db_session,
            name="my-draft",
            status="draft",
            draft_owner_id="alice@example.com",
        )
        _make_product(
            db_session,
            name="my-published",
            status="active",
            draft_owner_id="alice@example.com",
        )
        _make_product(
            db_session,
            name="others",
            draft_owner_id="bob@example.com",
        )

        result = data_product_repo.get_multi(
            db=db_session,
            is_admin=False,
            caller_email="alice@example.com",
        )
        assert {p.name for p in result} == {"my-draft", "my-published"}

    def test_non_admin_cascade_union(self, db_session: Session):
        """All three branches OR together (not AND)."""
        _make_product(db_session, name="via-project", project_id="proj-A")
        _make_product(db_session, name="via-team", owner_team_id="team-A")
        _make_product(
            db_session, name="via-email", draft_owner_id="alice@example.com"
        )
        _make_product(db_session, name="not-mine", owner_team_id="team-B")
        _make_product(db_session, name="orphan")  # no ownership at all

        result = data_product_repo.get_multi(
            db=db_session,
            is_admin=False,
            caller_email="alice@example.com",
            caller_team_ids=["team-A"],
            caller_project_ids=["proj-A"],
        )
        assert {p.name for p in result} == {"via-project", "via-team", "via-email"}

    def test_non_admin_legacy_orphan_fails_closed(self, db_session: Session):
        """Legacy product with no project_id / owner_team_id / draft_owner_id
        is invisible to non-admins (fail-closed)."""
        _make_product(db_session, name="orphan")
        result = data_product_repo.get_multi(
            db=db_session,
            is_admin=False,
            caller_email="alice@example.com",
            caller_team_ids=["team-A"],
            caller_project_ids=["proj-A"],
        )
        assert result == []

    def test_non_admin_email_case_insensitive_via_lowercase_storage(
        self, db_session: Session
    ):
        """draft_owner_id is stored as set; our manager check lowers both
        sides. The repository SQL filter is case-sensitive (matches what's
        in the column). This test documents that contract: callers must
        pass a properly-cased email matching how Ontos persists owners
        (lowercase via ``current_user.email``).
        """
        _make_product(
            db_session, name="mine", draft_owner_id="alice@example.com"
        )
        result = data_product_repo.get_multi(
            db=db_session,
            is_admin=False,
            caller_email="alice@example.com",
        )
        assert len(result) == 1


# ----------------------------------------------------------------------------
# Manager: list_products threading
# ----------------------------------------------------------------------------


class TestListProductsScopeThreading:
    """Verify :py:meth:`DataProductsManager.list_products` forwards scope
    args to the repo unchanged."""

    @pytest.fixture
    def mock_ws_client(self):
        return MagicMock()

    @pytest.fixture
    def manager(self, db_session, mock_ws_client):
        return DataProductsManager(
            db=db_session,
            ws_client=mock_ws_client,
            notifications_manager=MagicMock(),
            tags_manager=MagicMock(),
        )

    def test_admin_list_returns_all(self, manager, db_session):
        _make_product(db_session, name="A", project_id="proj-A")
        _make_product(db_session, name="B")  # orphan
        result = manager.list_products(is_admin=True)
        assert len(result) == 2

    def test_non_admin_list_filters_by_scope(self, manager, db_session):
        _make_product(db_session, name="mine", owner_team_id="team-A")
        _make_product(db_session, name="theirs", owner_team_id="team-B")
        result = manager.list_products(
            is_admin=False,
            caller_email="alice@example.com",
            caller_team_ids=["team-A"],
        )
        assert len(result) == 1
        assert result[0].name == "mine"

    def test_non_admin_list_no_scope_fails_closed(self, manager, db_session):
        _make_product(db_session, name="A", owner_team_id="team-A")
        # Old-style call site (no scope) — must yield empty for non-admin.
        result = manager.list_products(is_admin=False)
        assert result == []


# ----------------------------------------------------------------------------
# Manager: update_product_with_auth cascade
# ----------------------------------------------------------------------------


class TestUpdateProductWithAuthCascade:
    """Cover the in-code ownership cascade in
    :py:meth:`DataProductsManager.update_product_with_auth`."""

    @pytest.fixture
    def mock_ws_client(self):
        return MagicMock()

    @pytest.fixture
    def manager(self, db_session, mock_ws_client):
        return DataProductsManager(
            db=db_session,
            ws_client=mock_ws_client,
            notifications_manager=MagicMock(),
            tags_manager=MagicMock(),
        )

    @pytest.fixture(autouse=True)
    def _stub_update_product(self, manager):
        """Stub the inner ``update_product`` so tests focus on the auth
        cascade. Returning a sentinel lets us assert "auth passed → update
        was invoked"."""
        manager.update_product = MagicMock(return_value="UPDATED_OK")
        return manager

    @pytest.fixture(autouse=True)
    def _stub_admin_check(self):
        """Force ``is_user_admin`` to be controllable per-test."""
        with patch(
            "src.common.authorization.is_user_admin"
        ) as mock_is_admin:
            mock_is_admin.return_value = False
            yield mock_is_admin

    @pytest.fixture(autouse=True)
    def _stub_project_member(self):
        """Force ``is_user_project_member`` to be controllable per-test.

        ``update_product_with_auth`` imports ``projects_manager`` lazily, then
        calls the method as ``projects_manager.is_user_project_member(...)``.
        Patching the module-level singleton's bound method covers both call
        styles.
        """
        from src.controller import projects_manager as projects_manager_module

        with patch.object(
            projects_manager_module.projects_manager,
            "is_user_project_member",
            return_value=False,
        ) as mock_member:
            yield mock_member

    # ---- admin path ----

    def test_admin_can_edit_orphan(
        self, manager, db_session, _stub_admin_check
    ):
        _stub_admin_check.return_value = True
        product = _make_product(db_session, name="orphan")

        result = manager.update_product_with_auth(
            product_id=product.id,
            product_data_dict={"name": "renamed"},
            user_email="admin@example.com",
            user_groups=["admins"],
            db=db_session,
        )
        assert result == "UPDATED_OK"
        manager.update_product.assert_called_once()

    def test_admin_can_edit_others_team_product(
        self, manager, db_session, _stub_admin_check
    ):
        _stub_admin_check.return_value = True
        product = _make_product(
            db_session, name="x", owner_team_id="team-OTHER"
        )

        result = manager.update_product_with_auth(
            product_id=product.id,
            product_data_dict={"name": "renamed"},
            user_email="admin@example.com",
            user_groups=["admins"],
            db=db_session,
            caller_team_ids=[],  # admin doesn't need teams
        )
        assert result == "UPDATED_OK"

    # ---- project membership branch ----

    def test_non_admin_with_project_membership_can_edit(
        self, manager, db_session, _stub_project_member
    ):
        _stub_project_member.return_value = True
        product = _make_product(
            db_session, name="x", project_id="proj-A"
        )

        result = manager.update_product_with_auth(
            product_id=product.id,
            product_data_dict={"name": "renamed"},
            user_email="alice@example.com",
            user_groups=[],
            db=db_session,
        )
        assert result == "UPDATED_OK"

    # ---- team-ownership branch ----

    def test_non_admin_with_team_ownership_can_edit(self, manager, db_session):
        product = _make_product(
            db_session, name="x", owner_team_id="team-A"
        )

        result = manager.update_product_with_auth(
            product_id=product.id,
            product_data_dict={"name": "renamed"},
            user_email="alice@example.com",
            user_groups=[],
            db=db_session,
            caller_team_ids=["team-A", "team-Z"],
        )
        assert result == "UPDATED_OK"

    def test_non_admin_not_in_owning_team_is_denied(
        self, manager, db_session
    ):
        product = _make_product(
            db_session, name="x", owner_team_id="team-A"
        )

        with pytest.raises(PermissionError) as excinfo:
            manager.update_product_with_auth(
                product_id=product.id,
                product_data_dict={"name": "renamed"},
                user_email="alice@example.com",
                user_groups=[],
                db=db_session,
                caller_team_ids=["team-Z"],
            )
        # Generic message — must not disclose which check failed.
        assert "Insufficient permissions" in str(excinfo.value)

    # ---- draft-owner / creator branch ----

    def test_non_admin_draft_owner_can_edit_their_own(
        self, manager, db_session
    ):
        product = _make_product(
            db_session,
            name="mine",
            status="draft",
            draft_owner_id="alice@example.com",
        )

        result = manager.update_product_with_auth(
            product_id=product.id,
            product_data_dict={"name": "renamed"},
            user_email="alice@example.com",
            user_groups=[],
            db=db_session,
        )
        assert result == "UPDATED_OK"

    def test_non_admin_draft_owner_works_for_published_too(
        self, manager, db_session
    ):
        """Single-user ownership works regardless of status."""
        product = _make_product(
            db_session,
            name="mine-published",
            status="active",
            draft_owner_id="alice@example.com",
        )

        result = manager.update_product_with_auth(
            product_id=product.id,
            product_data_dict={"name": "renamed"},
            user_email="alice@example.com",
            user_groups=[],
            db=db_session,
        )
        assert result == "UPDATED_OK"

    def test_non_admin_draft_owner_match_is_case_insensitive(
        self, manager, db_session
    ):
        product = _make_product(
            db_session,
            name="mine",
            status="draft",
            draft_owner_id="Alice@Example.com",
        )

        result = manager.update_product_with_auth(
            product_id=product.id,
            product_data_dict={"name": "renamed"},
            user_email="alice@example.com",
            user_groups=[],
            db=db_session,
        )
        assert result == "UPDATED_OK"

    # ---- deny paths ----

    def test_non_admin_not_owner_is_denied(self, manager, db_session):
        product = _make_product(
            db_session,
            name="theirs",
            status="draft",
            draft_owner_id="bob@example.com",
        )

        with pytest.raises(PermissionError):
            manager.update_product_with_auth(
                product_id=product.id,
                product_data_dict={"name": "renamed"},
                user_email="alice@example.com",
                user_groups=[],
                db=db_session,
                caller_team_ids=[],
            )

    def test_non_admin_orphan_product_denied(self, manager, db_session):
        """Legacy orphan: no project_id, no owner_team_id, no
        draft_owner_id → non-admin denied (fail-closed)."""
        product = _make_product(db_session, name="orphan")

        with pytest.raises(PermissionError):
            manager.update_product_with_auth(
                product_id=product.id,
                product_data_dict={"name": "renamed"},
                user_email="alice@example.com",
                user_groups=[],
                db=db_session,
                caller_team_ids=["team-A"],
            )

    def test_update_returns_none_when_product_missing(
        self, manager, db_session
    ):
        result = manager.update_product_with_auth(
            product_id="does-not-exist",
            product_data_dict={"name": "x"},
            user_email="alice@example.com",
            user_groups=[],
            db=db_session,
        )
        assert result is None
