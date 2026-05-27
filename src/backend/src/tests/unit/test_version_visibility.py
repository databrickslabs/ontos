"""Unit tests for src.common.version_visibility (PRD #442, Phase 3).

These cover the role-aware rank table in isolation — every other test
that exercises the collapse end-to-end relies on this module being
correct, so it gets its own tight focused suite.
"""
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from src.common.version_visibility import (
    collapse_by_family,
    compute_rank,
    family_counts,
    is_admin_only_status,
    is_visible_consumer,
)


def make_row(
    *,
    id: str = "row",
    family_id: str = "fam",
    status: str = "active",
    draft_owner_id: str | None = None,
    owner_team_id: str | None = None,
    created_at: datetime | None = None,
):
    """A lightweight row that quacks like a ``DataContractDb`` / ``DataProductDb``
    for the purposes of visibility ranking. The functions under test only
    look at attributes, so we don't need a real ORM row."""
    return SimpleNamespace(
        id=id,
        version_family_id=family_id,
        status=status,
        draft_owner_id=draft_owner_id,
        owner_team_id=owner_team_id,
        created_at=created_at or datetime(2026, 1, 1, tzinfo=timezone.utc),
    )


class TestStatusVisibility:
    def test_consumer_sees_active_and_deprecated_only(self):
        assert is_visible_consumer(make_row(status="active"))
        assert is_visible_consumer(make_row(status="deprecated"))
        assert not is_visible_consumer(make_row(status="draft"))
        assert not is_visible_consumer(make_row(status="proposed"))
        assert not is_visible_consumer(make_row(status="retired"))

    def test_admin_only_statuses(self):
        # ``retired`` is the only admin-only status today. Adding more
        # should be a deliberate, explicit policy change — this test
        # documents the current set.
        assert is_admin_only_status(make_row(status="retired"))
        assert not is_admin_only_status(make_row(status="deprecated"))
        assert not is_admin_only_status(make_row(status="draft"))


class TestRankOrdering:
    """Lower rank wins. We assert relative orderings rather than absolute
    numbers so the test survives status-table reshuffles."""

    def test_elevated_prefers_draft_over_active(self):
        draft = make_row(status="draft")
        active = make_row(status="active")
        assert compute_rank(draft, has_elevated_access=True) < compute_rank(
            active, has_elevated_access=True
        )

    def test_consumer_prefers_active_over_deprecated(self):
        active = make_row(status="active")
        deprecated = make_row(status="deprecated")
        assert compute_rank(active, has_elevated_access=False) < compute_rank(
            deprecated, has_elevated_access=False
        )

    def test_ties_break_by_created_at_desc(self):
        older = make_row(
            id="old",
            status="active",
            created_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
        )
        newer = make_row(
            id="new",
            status="active",
            created_at=datetime(2026, 2, 1, tzinfo=timezone.utc),
        )
        # Newer should win the tie → smaller key.
        assert compute_rank(newer, has_elevated_access=False) < compute_rank(
            older, has_elevated_access=False
        )


class TestCollapseByFamily:
    def _three_status_family(self):
        base = datetime(2026, 1, 1, tzinfo=timezone.utc)
        return [
            make_row(
                id="v1",
                status="active",
                created_at=base,
            ),
            make_row(
                id="v2",
                status="deprecated",
                created_at=base + timedelta(days=1),
            ),
            make_row(
                id="v3",
                status="draft",
                created_at=base + timedelta(days=2),
            ),
        ]

    def test_consumer_picks_active_even_when_newer_draft_exists(self):
        rows = self._three_status_family()
        reps = collapse_by_family(rows, elevated_family_ids=set(), is_admin=False)
        # Draft is filtered out for consumers; active wins over deprecated.
        assert {r.id for r in reps} == {"v1"}

    def test_elevated_picks_newest_draft_over_active(self):
        rows = self._three_status_family()
        reps = collapse_by_family(
            rows, elevated_family_ids={"fam"}, is_admin=False
        )
        assert {r.id for r in reps} == {"v3"}

    def test_admin_picks_newest_draft_without_elevation_set(self):
        # Admins bypass the elevation set entirely.
        rows = self._three_status_family()
        reps = collapse_by_family(rows, elevated_family_ids=set(), is_admin=True)
        assert {r.id for r in reps} == {"v3"}

    def test_retired_hidden_from_non_admin(self):
        rows = [
            make_row(id="v1", family_id="fam", status="active"),
            make_row(id="v2", family_id="fam", status="retired"),
        ]
        reps = collapse_by_family(rows, elevated_family_ids={"fam"}, is_admin=False)
        # Retired filtered out even for elevated callers; active survives.
        assert {r.id for r in reps} == {"v1"}

    def test_retired_visible_to_admin(self):
        rows = [
            make_row(id="v1", family_id="fam", status="retired"),
        ]
        reps = collapse_by_family(rows, elevated_family_ids=set(), is_admin=True)
        # No other row, so the retired one wins by default.
        assert {r.id for r in reps} == {"v1"}

    def test_consumer_family_with_only_drafts_disappears(self):
        # A family with no published row is invisible to consumers — they
        # should not see it at all in the list.
        rows = [
            make_row(id="d1", family_id="fam-draft", status="draft"),
            make_row(id="d2", family_id="fam-draft", status="proposed"),
        ]
        reps = collapse_by_family(rows, elevated_family_ids=set(), is_admin=False)
        assert reps == []

    def test_two_families_collapse_independently(self):
        base = datetime(2026, 1, 1, tzinfo=timezone.utc)
        rows = [
            make_row(id="a1", family_id="A", status="active", created_at=base),
            make_row(
                id="a2",
                family_id="A",
                status="active",
                created_at=base + timedelta(days=1),
            ),
            make_row(id="b1", family_id="B", status="active", created_at=base),
        ]
        reps = collapse_by_family(rows, elevated_family_ids=set(), is_admin=True)
        # Newest within each family wins; families don't bleed into each other.
        assert {r.id for r in reps} == {"a2", "b1"}


class TestFamilyCounts:
    def test_counts_match_input(self):
        rows = [
            make_row(id="a1", family_id="A"),
            make_row(id="a2", family_id="A"),
            make_row(id="b1", family_id="B"),
        ]
        counts = family_counts(rows)
        assert counts == {"A": 2, "B": 1}

    def test_orphan_rows_ignored(self):
        orphan = SimpleNamespace(
            id=None, version_family_id=None, status="active", created_at=None,
            draft_owner_id=None, owner_team_id=None,
        )
        counts = family_counts([orphan])
        assert counts == {}
