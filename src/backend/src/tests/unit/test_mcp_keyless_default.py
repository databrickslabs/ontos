"""Unit tests for keyless-default MCP token resolution.

Covers the security-relevant branches of ``MCPTokensManager.resolve_keyless_default``
and the single-active-default invariant enforced by the repository.
"""
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy.orm import Session

from src.controller.mcp_tokens_manager import MCPTokensManager
from src.repositories.mcp_tokens_repository import mcp_tokens_repo


EMAIL = "genie-user@example.com"


def _make_default(db: Session, scopes=None, expires_days=90):
    """Create a token and designate it the keyless default. Returns the db row."""
    mgr = MCPTokensManager(db=db)
    generated = mgr.generate_token(
        name="keyless-default",
        scopes=scopes if scopes is not None else ["semantic:read", "search:read"],
        created_by="admin@example.com",
        expires_days=expires_days,
        is_keyless_default=True,
    )
    db.flush()
    return mcp_tokens_repo.get_by_id(db, generated.id)


class TestResolveKeylessDefault:
    def test_no_default_returns_none(self, db_session: Session):
        mgr = MCPTokensManager(db=db_session)
        assert mgr.resolve_keyless_default(EMAIL) is None

    def test_active_default_with_email_stamps_caller_and_carries_scopes(self, db_session: Session):
        _make_default(db_session, scopes=["semantic:read", "search:read"])
        mgr = MCPTokensManager(db=db_session)

        principal = mgr.resolve_keyless_default(EMAIL)

        assert principal is not None
        # Audit attribution is the forwarded caller, not the shared token creator.
        assert principal.created_by == EMAIL
        # Scopes come verbatim from the default token — they bound the blast radius.
        assert principal.scopes == ["semantic:read", "search:read"]

    def test_missing_email_returns_none_even_with_active_default(self, db_session: Session):
        _make_default(db_session)
        mgr = MCPTokensManager(db=db_session)

        assert mgr.resolve_keyless_default("") is None
        assert mgr.resolve_keyless_default(None) is None

    def test_inactive_default_returns_none(self, db_session: Session):
        token = _make_default(db_session)
        mcp_tokens_repo.revoke(db_session, token.id)
        db_session.flush()

        mgr = MCPTokensManager(db=db_session)
        assert mgr.resolve_keyless_default(EMAIL) is None

    def test_expired_default_returns_none(self, db_session: Session):
        token = _make_default(db_session)
        token.expires_at = datetime.now(timezone.utc) - timedelta(days=1)
        db_session.flush()

        mgr = MCPTokensManager(db=db_session)
        assert mgr.resolve_keyless_default(EMAIL) is None

    def test_resolution_updates_last_used(self, db_session: Session):
        token = _make_default(db_session)
        assert token.last_used_at is None

        MCPTokensManager(db=db_session).resolve_keyless_default(EMAIL)
        db_session.refresh(token)
        assert token.last_used_at is not None


class TestSingleDefaultInvariant:
    def test_set_keyless_default_clears_previous(self, db_session: Session):
        mgr = MCPTokensManager(db=db_session)
        a = mgr.generate_token(name="a", scopes=["semantic:read"], expires_days=None)
        b = mgr.generate_token(name="b", scopes=["semantic:read"], expires_days=None)
        db_session.flush()

        assert mgr.set_keyless_default(a.id) is True
        assert mgr.set_keyless_default(b.id) is True
        db_session.flush()

        defaults = [t for t in mcp_tokens_repo.list_all(db_session) if t.is_keyless_default]
        assert len(defaults) == 1
        assert defaults[0].id == b.id

    def test_generate_default_supersedes_existing(self, db_session: Session):
        mgr = MCPTokensManager(db=db_session)
        first = _make_default(db_session)
        second = mgr.generate_token(
            name="second-default",
            scopes=["semantic:read"],
            expires_days=None,
            is_keyless_default=True,
        )
        db_session.flush()

        defaults = [t for t in mcp_tokens_repo.list_all(db_session) if t.is_keyless_default]
        assert [t.id for t in defaults] == [second.id]
        db_session.refresh(first)
        assert first.is_keyless_default is False

    def test_set_keyless_default_missing_token_returns_false(self, db_session: Session):
        import uuid
        assert MCPTokensManager(db=db_session).set_keyless_default(uuid.uuid4()) is False

    def test_clear_keyless_default(self, db_session: Session):
        _make_default(db_session)
        mgr = MCPTokensManager(db=db_session)

        assert mgr.clear_keyless_default() is True
        db_session.flush()
        assert not any(t.is_keyless_default for t in mcp_tokens_repo.list_all(db_session))
        # Clearing again reports nothing to clear.
        assert mgr.clear_keyless_default() is False
