"""Unit tests for ``SearchOntosConceptsTool``.

Exercises:

- Empty query => failure.
- Real corpus queries (the tool resolves ``docs/concepts/`` relative to
  the repo root; that directory ships with the branch under test).
- Known-concept lookups land in the right file.
- No-match queries return ``success=True`` with an empty match list and
  a friendly ``message`` field.
- Anchor extraction handles the ``{#kebab-case}`` syntax used across
  the corpus, with a slugified fallback when a section omits an anchor.
- Graceful degrade when ``docs/concepts/`` is absent (deployed-app case).

We don't mock the corpus contents — the docs are read-only inputs to
this branch and exercising them directly is the most realistic test we
can write without bringing in fixtures that drift from the real files.
"""

# Set test environment variables BEFORE any app imports
import os
os.environ['TESTING'] = 'true'
os.environ['SKIP_STARTUP_TASKS'] = 'true'

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from src.tools.base import ToolContext
from src.tools.concepts import (
    SearchOntosConceptsTool,
    _parse_sections,
    _slugify_fallback_anchor,
    _resolve_concepts_dir,
)


def _make_ctx() -> ToolContext:
    """Concept search ignores ``ctx`` entirely — it reads the filesystem
    directly. A skeletal mock is enough."""
    return ToolContext(db=MagicMock(), settings=MagicMock())


@pytest.fixture
def tool() -> SearchOntosConceptsTool:
    return SearchOntosConceptsTool()


# ---------------------------------------------------------------------------
# Smoke / preconditions
# ---------------------------------------------------------------------------


def test_corpus_is_resolvable_in_this_test_run():
    """Sanity check: the test environment can locate the corpus. If
    this fails, every other test in this module is meaningless — flag
    it loudly rather than hide behind silent skips."""
    concepts_dir = _resolve_concepts_dir()
    assert concepts_dir is not None, (
        "docs/concepts/ not found at the expected location. The path "
        "resolution math in src/backend/src/tools/concepts.py may have "
        "drifted relative to the repo layout."
    )
    assert concepts_dir.is_dir()


def test_tool_metadata(tool: SearchOntosConceptsTool):
    """The registered tool name and category are load-bearing — the
    query classifier dispatches on the category and the registry
    surfaces the tool by name. Lock both down."""
    assert tool.name == "search_ontos_concepts"
    assert tool.category == "concepts"
    assert "query" in tool.required_params
    # No scope gate — concept docs are public grounding material.
    assert tool.required_scope is None


# ---------------------------------------------------------------------------
# Empty / invalid input
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_empty_query_returns_error(tool: SearchOntosConceptsTool):
    result = await tool.execute(_make_ctx(), query="")
    assert result.success is False
    assert "non-empty" in (result.error or "").lower()


@pytest.mark.asyncio
async def test_whitespace_only_query_returns_error(tool: SearchOntosConceptsTool):
    result = await tool.execute(_make_ctx(), query="   \t  \n")
    assert result.success is False


# ---------------------------------------------------------------------------
# Known-concept queries (corpus-backed)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_data_steward_query_hits_roles_doc(tool: SearchOntosConceptsTool):
    """'data steward' is a built-in role; it must land in roles-and-rbac.md."""
    result = await tool.execute(_make_ctx(), query="data steward")
    assert result.success is True
    matches = result.data["matches"]
    assert matches, "expected at least one match for 'data steward'"

    files_returned = {m["file"] for m in matches}
    assert "roles-and-rbac.md" in files_returned, (
        f"'data steward' did not match anything in roles-and-rbac.md "
        f"(got files: {files_returned})"
    )

    # Every match must carry a citable source_uri of the form file.md#anchor
    for m in matches:
        assert m["source_uri"].endswith(
            f"#{m['anchor']}"
        ), f"source_uri shape wrong: {m['source_uri']}"
        assert m["source_uri"].startswith(m["file"])


@pytest.mark.asyncio
async def test_delivery_mode_query_hits_delivery_doc(tool: SearchOntosConceptsTool):
    """'delivery mode' is the topic of delivery-and-propagation.md."""
    result = await tool.execute(_make_ctx(), query="delivery mode")
    assert result.success is True
    matches = result.data["matches"]
    assert matches, "expected matches for 'delivery mode'"

    # Top-scored result should come from delivery-and-propagation.md.
    top_file = matches[0]["file"]
    assert top_file == "delivery-and-propagation.md", (
        f"expected delivery-and-propagation.md as top match, got {top_file}"
    )


@pytest.mark.asyncio
async def test_what_is_agreement_query_hits_agreement_workflow(
    tool: SearchOntosConceptsTool,
):
    """A common conceptual question — exercise the title-match path."""
    result = await tool.execute(_make_ctx(), query="agreement workflow")
    assert result.success is True
    matches = result.data["matches"]
    assert matches
    files_returned = {m["file"] for m in matches}
    assert "agreement-workflow.md" in files_returned


@pytest.mark.asyncio
async def test_max_results_caps_returned_matches(tool: SearchOntosConceptsTool):
    """A broad query against the corpus must respect max_results."""
    result = await tool.execute(_make_ctx(), query="role", max_results=3)
    assert result.success is True
    assert len(result.data["matches"]) <= 3


@pytest.mark.asyncio
async def test_max_results_is_clamped(tool: SearchOntosConceptsTool):
    """Excessive max_results values are clamped (not rejected)."""
    result = await tool.execute(_make_ctx(), query="role", max_results=999)
    assert result.success is True
    assert len(result.data["matches"]) <= 10  # implementation cap


# ---------------------------------------------------------------------------
# No-match queries
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_no_match_query_returns_success_with_empty_list(
    tool: SearchOntosConceptsTool,
):
    """A query that can't possibly match the corpus (a wholly unrelated
    SRE topic) must return success=True with an empty match list and a
    friendly message — NOT an error. The LLM uses this signal to fall
    back to its refusal template."""
    # Truly off-topic tokens — picked to avoid words that appear in the
    # corpus (the docs do mention "deployment", "chart", "step", etc.,
    # which would yield spurious low-score matches).
    result = await tool.execute(
        _make_ctx(),
        query="zygomorphic platypus rutabaga marshmallow",
    )
    assert result.success is True
    assert result.data["matches"] == []
    assert "No matching concept docs found" in result.data.get("message", "")
    assert result.data["total_files_searched"] > 0


# ---------------------------------------------------------------------------
# Anchor extraction
# ---------------------------------------------------------------------------


def test_kebab_anchor_extracted_from_explicit_syntax(tmp_path: Path):
    """Sections with ``## Title {#anchor-id}`` headings must surface
    'anchor-id' as the anchor."""
    md = tmp_path / "sample.md"
    md.write_text(
        "# Doc\n\n"
        "Intro paragraph.\n\n"
        "## The permission model {#permission-model}\n\n"
        "Body of the permission-model section.\n\n"
        "### Access levels {#access-levels}\n\n"
        "Body of the access-levels section.\n",
        encoding="utf-8",
    )
    sections = _parse_sections(md)
    anchors = {s.title: s.anchor for s in sections}
    assert anchors["The permission model"] == "permission-model"
    assert anchors["Access levels"] == "access-levels"


def test_section_without_explicit_anchor_falls_back_to_slug(tmp_path: Path):
    md = tmp_path / "noanchor.md"
    md.write_text(
        "# Doc\n\n"
        "Intro.\n\n"
        "## A Section Without An Anchor\n\n"
        "Some body text here.\n",
        encoding="utf-8",
    )
    sections = _parse_sections(md)
    bare = next(s for s in sections if s.title == "A Section Without An Anchor")
    # Anchor is empty in the parsed Section dataclass...
    assert bare.anchor == ""
    # ...but the tool slugifies it for source_uri rendering.
    assert _slugify_fallback_anchor(bare.title) == "a-section-without-an-anchor"


# ---------------------------------------------------------------------------
# Graceful degrade when corpus is missing
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_missing_corpus_returns_empty_matches_not_an_error(
    tool: SearchOntosConceptsTool,
):
    """Deployed Apps may not package docs/concepts/. The tool must
    still return ``success=True`` so the LLM can fall back to its
    refusal template gracefully."""
    with patch(
        "src.tools.concepts._resolve_concepts_dir",
        return_value=None,
    ):
        result = await tool.execute(_make_ctx(), query="data steward")
    assert result.success is True
    assert result.data["matches"] == []
    assert result.data["total_files_searched"] == 0
    assert "not available" in result.data.get("message", "").lower()
