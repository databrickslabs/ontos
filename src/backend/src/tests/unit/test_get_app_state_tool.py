"""Unit tests for ``GetAppStateTool`` and the shared adoption snapshot.

Two layers under test:

1. ``get_adoption_snapshot`` — the pure-function helper that reads
   counts via SQLAlchemy and derives a binary ``adoption_mode``. Same
   function powers the tool result and the system-prompt preamble, so
   we test it directly to make sure both paths agree.
2. ``GetAppStateTool.execute`` — the LLM-callable wrapper. Covers
   metadata, the no-param call shape, and graceful degrade on a DB
   error so the model still gets a usable refusal rather than a 500.

The tests use the in-memory SQLite fixture wired by ``conftest.py``
(``db_session``) so counts are real, not mocked. ``adoption_mode``
hinges on *published* products (``publication_scope`` non-null AND
not the literal string 'none'), so the "active" fixture sets that
column explicitly.
"""

# Set test environment variables BEFORE any app imports
import os
os.environ['TESTING'] = 'true'
os.environ['SKIP_STARTUP_TASKS'] = 'true'

import uuid
from unittest.mock import MagicMock, patch

import pytest
from sqlalchemy.orm import Session

from src.db_models.data_contracts import DataContractDb
from src.db_models.data_domains import DataDomain
from src.db_models.data_products import DataProductDb
from src.tools.app_state import (
    ADOPTION_MODE_ACTIVE,
    ADOPTION_MODE_BLANK,
    GetAppStateTool,
    get_adoption_snapshot,
)
from src.tools.base import ToolContext


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_product(
    *,
    name: str = "Test Product",
    publication_scope=None,
) -> DataProductDb:
    """Build a minimal DataProductDb row. Only the fields exercised by
    the snapshot helper are populated; everything else relies on
    column defaults. ``DataProductDb.description`` is a relationship,
    not a column — don't set it here."""
    kwargs = dict(
        id=str(uuid.uuid4()),
        name=name,
        version="1.0.0",
        status="draft",
    )
    if publication_scope is not None:
        kwargs["publication_scope"] = publication_scope
    return DataProductDb(**kwargs)


def _make_ctx(db: Session) -> ToolContext:
    return ToolContext(db=db, settings=MagicMock())


# ---------------------------------------------------------------------------
# Tool metadata
# ---------------------------------------------------------------------------


def test_tool_metadata():
    """Lock down the name / category / no-scope-gate contract. The
    registry dispatches on name and the query classifier dispatches on
    category, so both are load-bearing."""
    tool = GetAppStateTool()
    assert tool.name == "get_app_state"
    assert tool.category == "app_state"
    # Counts aren't sensitive, so we deliberately drop the default
    # admin-only scope inherited from BaseTool.
    assert tool.required_scope is None
    assert tool.required_params == []
    # The tool takes no parameters; an empty parameters dict is what
    # surfaces in the OpenAI function schema.
    assert tool.parameters == {}


# ---------------------------------------------------------------------------
# get_adoption_snapshot — blank workspace
# ---------------------------------------------------------------------------


def test_blank_workspace_yields_blank_mode(db_session: Session):
    """A workspace with zero rows in every entity table is the
    archetypal 'blank' state. ``adoption_mode`` must be 'blank' and
    every count must be a non-negative int."""
    snapshot = get_adoption_snapshot(db_session)
    assert snapshot["adoption_mode"] == ADOPTION_MODE_BLANK

    counts = snapshot["counts"]
    for key in (
        "data_products_total",
        "data_products_published",
        "data_contracts_total",
        "domains_total",
        "teams_total",
        "projects_total",
        "roles_total",
    ):
        assert key in counts
        assert isinstance(counts[key], int)
        assert counts[key] >= 0

    # ISO-8601 string with timezone offset (the function uses UTC).
    assert "T" in snapshot["computed_at"]


def test_draft_only_workspace_still_blank(db_session: Session):
    """A workspace with DRAFT products only is still 'blank' — the
    distinction is about *published* assets, not whether anyone has
    started any work."""
    db_session.add(_make_product(name="Draft A"))
    db_session.add(_make_product(name="Draft B", publication_scope="none"))
    db_session.commit()

    snapshot = get_adoption_snapshot(db_session)
    assert snapshot["adoption_mode"] == ADOPTION_MODE_BLANK
    assert snapshot["counts"]["data_products_total"] == 2
    assert snapshot["counts"]["data_products_published"] == 0


def test_publication_scope_literal_none_treated_as_unpublished(db_session: Session):
    """Belt-and-suspenders: ``publication_scope='none'`` (literal
    string, mirrors the marketplace filter) must NOT flip mode to
    active. Some legacy rows have the string form rather than NULL."""
    db_session.add(_make_product(name="Legacy", publication_scope="none"))
    db_session.add(_make_product(name="Legacy Upper", publication_scope="NONE"))
    db_session.commit()

    snapshot = get_adoption_snapshot(db_session)
    assert snapshot["adoption_mode"] == ADOPTION_MODE_BLANK
    assert snapshot["counts"]["data_products_published"] == 0


# ---------------------------------------------------------------------------
# get_adoption_snapshot — active workspace
# ---------------------------------------------------------------------------


def test_published_product_flips_mode_to_active(db_session: Session):
    """A single published product is enough to flip mode to 'active'."""
    db_session.add(_make_product(name="Published A", publication_scope="organization"))
    db_session.add(_make_product(name="Draft", publication_scope=None))
    db_session.commit()

    snapshot = get_adoption_snapshot(db_session)
    assert snapshot["adoption_mode"] == ADOPTION_MODE_ACTIVE
    assert snapshot["counts"]["data_products_total"] == 2
    assert snapshot["counts"]["data_products_published"] == 1


def test_counts_cover_multiple_entity_types(db_session: Session):
    """Spot-check that the snapshot picks up domain + contract counts
    in addition to products, so we don't silently lose entities if
    schema changes drop a relationship."""
    db_session.add(_make_product(publication_scope="organization"))
    db_session.add(
        DataDomain(
            id=str(uuid.uuid4()),
            name="Finance",
            description="finance domain",
            created_by="owner@example.com",
        )
    )
    db_session.add(
        DataContractDb(
            id=str(uuid.uuid4()),
            name="Test Contract",
            version="1.0.0",
            status="draft",
        )
    )
    db_session.commit()

    snapshot = get_adoption_snapshot(db_session)
    assert snapshot["adoption_mode"] == ADOPTION_MODE_ACTIVE
    assert snapshot["counts"]["domains_total"] >= 1
    assert snapshot["counts"]["data_contracts_total"] >= 1


# ---------------------------------------------------------------------------
# GetAppStateTool.execute
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_execute_returns_success_with_mode(db_session: Session):
    """End-to-end through the BaseTool surface — should return the
    snapshot under ``data`` with ``success=True``."""
    tool = GetAppStateTool()
    result = await tool.execute(_make_ctx(db_session))
    assert result.success is True
    assert result.data["adoption_mode"] in (ADOPTION_MODE_BLANK, ADOPTION_MODE_ACTIVE)
    assert "counts" in result.data
    assert "computed_at" in result.data


@pytest.mark.asyncio
async def test_execute_ignores_unexpected_kwargs(db_session: Session):
    """LLMs sometimes pass empty dicts or stray fields. The tool takes
    no params; it must not raise when handed extras."""
    tool = GetAppStateTool()
    result = await tool.execute(_make_ctx(db_session), random_field="ignored")
    assert result.success is True


@pytest.mark.asyncio
async def test_execute_handles_snapshot_failure_gracefully():
    """If the underlying snapshot raises, ``execute`` must convert to
    a structured tool error rather than letting the exception escape
    (the LLM loop would otherwise abort the whole chat)."""
    tool = GetAppStateTool()
    with patch(
        "src.tools.app_state.get_adoption_snapshot",
        side_effect=RuntimeError("db down"),
    ):
        ctx = ToolContext(db=MagicMock(), settings=MagicMock())
        result = await tool.execute(ctx)

    assert result.success is False
    assert "db down" in (result.error or "")


# ---------------------------------------------------------------------------
# Snapshot contract — used by LlmSearchManager pre-fetch
# ---------------------------------------------------------------------------


def test_snapshot_shape_is_stable(db_session: Session):
    """Lock the top-level keys returned by ``get_adoption_snapshot`` —
    the manager pre-fetch path destructures ``adoption_mode`` and
    ``counts`` directly, so a key rename would silently disable mode
    awareness."""
    snapshot = get_adoption_snapshot(db_session)
    assert set(snapshot.keys()) == {"adoption_mode", "counts", "computed_at"}
