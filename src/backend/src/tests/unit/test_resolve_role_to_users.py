"""Unit tests for ``_resolve_role_to_users``.

Pins the existing single-token behaviour and locks down the new
comma-split / recurse path the Workflow Designer's "Custom principals"
toggle relies on.
"""

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from src.common.workflow_executor import _resolve_role_to_users


def _ctx(*, user_email="alice@example.com", entity=None, entity_type=None, entity_id=None):
    return SimpleNamespace(
        user_email=user_email,
        entity=entity or {},
        entity_type=entity_type,
        entity_id=entity_id,
        entity_name=None,
    )


@pytest.fixture
def db_with_no_roles():
    """A DB session whose AppRole queries return nothing.

    Sufficient for tests that only exercise the single-token
    requester/owner/email/literal branches plus the new comma-split.
    """

    db = MagicMock()
    db.query.return_value.filter.return_value.first.return_value = None
    db.query.return_value.all.return_value = []
    return db


class TestSingleTokenBehaviour:
    def test_requester_returns_user_email(self, db_with_no_roles):
        out = _resolve_role_to_users(db_with_no_roles, "requester", _ctx(user_email="r@x"))
        assert out == [("r@x", None)]

    def test_requester_returns_empty_when_no_email(self, db_with_no_roles):
        out = _resolve_role_to_users(db_with_no_roles, "requester", _ctx(user_email=None))
        assert out == []

    def test_owner_pulls_from_entity(self, db_with_no_roles):
        out = _resolve_role_to_users(
            db_with_no_roles, "owner", _ctx(entity={"owner": "o@x"}),
        )
        assert out == [("o@x", None)]

    def test_single_email_returns_as_literal(self, db_with_no_roles):
        out = _resolve_role_to_users(db_with_no_roles, "alice@x.com", _ctx())
        assert out == [("alice@x.com", None)]

    def test_unknown_role_token_falls_back_to_literal(self, db_with_no_roles):
        out = _resolve_role_to_users(db_with_no_roles, "Producers", _ctx())
        # Unrecognised non-email token -- returned as literal so the
        # downstream notification fan-out can still address it (e.g.
        # group name).
        assert out == [("Producers", None)]


class TestCommaSplit:
    def test_mixed_role_email_group(self, db_with_no_roles):
        # The Workflow Designer's "Custom principals" toggle emits
        # something like this: a role-literal first, then any picked
        # emails / group names.
        out = _resolve_role_to_users(
            db_with_no_roles,
            "owner,alice@example.com,Producers",
            _ctx(entity={"owner": "o@x"}),
        )
        ids = [identifier for identifier, _ in out]
        assert ids == ["o@x", "alice@example.com", "Producers"]

    def test_dedupes_repeats(self, db_with_no_roles):
        out = _resolve_role_to_users(
            db_with_no_roles,
            "alice@x,alice@x,Producers,Producers",
            _ctx(),
        )
        ids = [identifier for identifier, _ in out]
        assert ids == ["alice@x", "Producers"]

    def test_strips_whitespace_and_skips_blanks(self, db_with_no_roles):
        out = _resolve_role_to_users(
            db_with_no_roles,
            "  alice@x  , ,  Producers ,",
            _ctx(),
        )
        ids = [identifier for identifier, _ in out]
        assert ids == ["alice@x", "Producers"]

    def test_requester_token_inside_list_expands(self, db_with_no_roles):
        # The role select can still drop ``requester`` in the string;
        # the comma-split path must let it expand to the user email.
        out = _resolve_role_to_users(
            db_with_no_roles,
            "requester,Producers",
            _ctx(user_email="r@x"),
        )
        ids = [identifier for identifier, _ in out]
        assert ids == ["r@x", "Producers"]

    def test_owner_token_inside_list_expands(self, db_with_no_roles):
        out = _resolve_role_to_users(
            db_with_no_roles,
            "owner,Producers",
            _ctx(entity={"owner": "o@x"}),
        )
        ids = [identifier for identifier, _ in out]
        assert ids == ["o@x", "Producers"]

    def test_single_email_no_longer_splits_on_absence_of_comma(self, db_with_no_roles):
        # The legacy comma-split-only-when-'@'-present path is gone;
        # confirm a lone email still returns one tuple, not zero.
        out = _resolve_role_to_users(db_with_no_roles, "alice@example.com", _ctx())
        assert out == [("alice@example.com", None)]

    def test_empty_list_returns_empty(self, db_with_no_roles):
        assert _resolve_role_to_users(db_with_no_roles, ",,,", _ctx()) == []
