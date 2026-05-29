"""
Concept-search tool for the Ask Ontos copilot.

Grounds the LLM in the curated `docs/concepts/` corpus so it can answer
"what is X?" / "how does Y work?" / "what's the difference between A and B?"
questions from authoritative project documentation rather than training
knowledge. Each result is a section excerpt with a stable
`file.md#anchor` source URI the model can cite.

The corpus is treated as read-only at runtime; the tool walks the
directory on every call (it's small — 13 files, ~100KB) and tokenizes
the query for a simple title/anchor/body-frequency match. Intentionally
no embeddings, no index — keeps the deployment surface zero.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from src.common.logging import get_logger
from src.tools.base import BaseTool, ToolContext, ToolResult

logger = get_logger(__name__)


# ---------------------------------------------------------------------------
# Path resolution
# ---------------------------------------------------------------------------

# This file lives at: <ontos>/src/backend/src/tools/concepts.py
# The corpus lives at: <ontos>/docs/concepts/
# So we walk five parents up from __file__ to reach <ontos>.
_REPO_ROOT = Path(__file__).resolve().parent.parent.parent.parent.parent
_DEFAULT_CONCEPTS_DIR = _REPO_ROOT / "docs" / "concepts"


def _resolve_concepts_dir() -> Optional[Path]:
    """Return the concept-docs directory if present on disk, else None.

    Deployed Databricks Apps may not include `docs/concepts/` in the
    packaged artifact. In that case, the tool degrades gracefully
    (returns no matches) rather than crashing.
    """
    if _DEFAULT_CONCEPTS_DIR.is_dir():
        return _DEFAULT_CONCEPTS_DIR
    return None


# ---------------------------------------------------------------------------
# Section parsing
# ---------------------------------------------------------------------------

# Match a markdown heading line of level 2 or 3, optionally with an explicit
# {#anchor-id} suffix. Example matches:
#   "## The permission model {#permission-model}"
#   "### Access levels {#access-levels}"
#   "## Some heading without an anchor"
_HEADING_RE = re.compile(
    r"^(?P<hashes>#{2,3})\s+"
    r"(?P<title>.+?)"
    r"(?:\s+\{#(?P<anchor>[a-z0-9][a-z0-9\-]*)\})?\s*$"
)


@dataclass
class _Section:
    file: str          # relative filename, e.g. "roles-and-rbac.md"
    title: str         # heading text without the {#anchor} suffix
    anchor: str        # explicit anchor id, or "" if none was given
    body: str          # body text between this heading and the next h2/h3


def _slugify_fallback_anchor(title: str) -> str:
    """Build a kebab-case anchor from a title when none was declared.

    The corpus convention is to use explicit ``{#anchor}`` syntax, but a
    few sections may omit it. We fall back to a slug so the citation
    still resolves.
    """
    slug = re.sub(r"[^a-z0-9\s\-]", "", title.lower())
    slug = re.sub(r"\s+", "-", slug).strip("-")
    return slug or "section"


def _parse_sections(file_path: Path) -> List[_Section]:
    """Split a markdown file into h2/h3 sections.

    Each section starts at an h2/h3 heading and runs until the next
    h2/h3 (or EOF). Content before the first h2/h3 (typically the h1 +
    intro paragraph) is captured as a synthetic intro section using the
    filename stem as title and "" as anchor — this is what lets queries
    like "what is mcp" match doc-level intros even when there isn't an
    explicit h2 for it.
    """
    try:
        text = file_path.read_text(encoding="utf-8")
    except OSError as e:
        logger.warning(f"[search_ontos_concepts] Could not read {file_path}: {e}")
        return []

    sections: List[_Section] = []
    current_title: Optional[str] = None
    current_anchor: str = ""
    current_body: List[str] = []
    intro_body: List[str] = []
    intro_title: Optional[str] = None

    rel_name = file_path.name

    for line in text.splitlines():
        # Capture H1 as the intro section title (skip the "# " prefix).
        if intro_title is None and line.startswith("# ") and not line.startswith("## "):
            intro_title = line[2:].strip()
            continue

        m = _HEADING_RE.match(line)
        if m and m.group("hashes") in ("##", "###"):
            # Flush previous section
            if current_title is not None:
                sections.append(_Section(
                    file=rel_name,
                    title=current_title,
                    anchor=current_anchor,
                    body="\n".join(current_body).strip(),
                ))
            elif intro_title is not None and intro_body:
                # We're transitioning from the intro into the first h2 —
                # emit the intro as a synthetic section.
                sections.append(_Section(
                    file=rel_name,
                    title=intro_title,
                    anchor="",
                    body="\n".join(intro_body).strip(),
                ))
                intro_body = []

            current_title = m.group("title").strip()
            current_anchor = (m.group("anchor") or "").strip()
            current_body = []
            continue

        if current_title is None:
            intro_body.append(line)
        else:
            current_body.append(line)

    # Flush final section (or intro-only file)
    if current_title is not None:
        sections.append(_Section(
            file=rel_name,
            title=current_title,
            anchor=current_anchor,
            body="\n".join(current_body).strip(),
        ))
    elif intro_title is not None and intro_body:
        sections.append(_Section(
            file=rel_name,
            title=intro_title,
            anchor="",
            body="\n".join(intro_body).strip(),
        ))

    return sections


# ---------------------------------------------------------------------------
# Scoring
# ---------------------------------------------------------------------------

_TOKEN_RE = re.compile(r"[a-zA-Z0-9]+")
_STOPWORDS = frozenset({
    "a", "an", "and", "are", "as", "at", "be", "by", "for", "from",
    "how", "i", "in", "is", "it", "of", "on", "or", "that", "the",
    "to", "was", "what", "where", "which", "who", "why", "with",
    "do", "does", "did", "can", "could", "should", "would",
})


def _tokenize(text: str) -> List[str]:
    return [t.lower() for t in _TOKEN_RE.findall(text) if t.lower() not in _STOPWORDS]


def _score_section(section: _Section, query: str, tokens: List[str]) -> float:
    """Score a section against a query. Higher is better."""
    if not tokens:
        return 0.0

    title_lower = section.title.lower()
    anchor_lower = section.anchor.lower()
    body_lower = section.body.lower()
    query_lower = query.lower().strip()

    score = 0.0

    # Strongest signal: whole-query substring in title
    if query_lower and query_lower in title_lower:
        score += 20.0

    # Per-token title hits
    for tok in tokens:
        if tok in title_lower:
            score += 6.0

    # Anchor hits
    if query_lower and query_lower.replace(" ", "-") in anchor_lower:
        score += 8.0
    for tok in tokens:
        if tok in anchor_lower:
            score += 3.0

    # Body-keyword frequency (capped so a single mega-section can't dominate)
    for tok in tokens:
        body_hits = body_lower.count(tok)
        if body_hits:
            score += min(body_hits, 5) * 1.0

    return score


def _truncate_excerpt(body: str, max_chars: int = 400) -> str:
    """Truncate a section body to roughly ``max_chars`` characters on a
    word boundary."""
    if len(body) <= max_chars:
        return body
    # Cut on the nearest space before the limit, fall back to hard cut
    cut = body.rfind(" ", 0, max_chars)
    if cut < max_chars - 80:  # if the last space is too far back, just hard-cut
        cut = max_chars
    return body[:cut].rstrip() + "..."


# ---------------------------------------------------------------------------
# Tool
# ---------------------------------------------------------------------------


class SearchOntosConceptsTool(BaseTool):
    """Search Ontos concept documentation for definitions and explanations.

    Returns ranked excerpts from the `docs/concepts/` corpus — the curated
    grounding source for the Ask Ontos copilot. Use this for any
    conceptual question (definitions, lifecycle states, role
    responsibilities, the agreement workflow, the ontology + knowledge
    graph model, data quality, delivery modes, MCP vs Ask Ontos, etc.)
    BEFORE answering from training knowledge.
    """

    name = "search_ontos_concepts"
    # New category — see query_classifier.CATEGORY_KEYWORDS["concepts"].
    # Also added to DEFAULT_CATEGORIES so vague / generic questions still
    # see this tool.
    category = "concepts"
    description = (
        "Search the Ontos concept documentation for definitions, role "
        "responsibilities, lifecycle states (data product / data contract "
        "/ agreement / workflow execution), the approval workflow, the "
        "ontology + knowledge graph model, the data quality model, "
        "delivery modes (Direct / Indirect / Manual), the MCP server vs "
        "the Ask Ontos copilot, and other platform concepts. "
        "USE THIS TOOL FIRST for any 'what is X?' / 'how does Y work?' / "
        "'what's the difference between A and B?' question — do not "
        "answer conceptual questions from training knowledge before "
        "checking the corpus. Each result includes a `source_uri` "
        "(file.md#anchor) suitable for citation."
    )
    parameters = {
        "query": {
            "type": "string",
            "description": (
                "Natural-language question or keyword(s). Examples: "
                "'data steward', 'what is a delivery mode', "
                "'agreement workflow vs execution', 'ODCS quality items'."
            ),
        },
        "max_results": {
            "type": "integer",
            "description": (
                "Maximum number of section excerpts to return (default 5, "
                "max 10)."
            ),
        },
    }
    required_params = ["query"]
    # Concept docs are public grounding material; no scope gate.
    required_scope = None  # type: ignore[assignment]

    async def execute(
        self,
        ctx: ToolContext,
        query: str,
        max_results: int = 5,
    ) -> ToolResult:
        logger.info(f"[search_ontos_concepts] query='{query}' max_results={max_results}")

        if not query or not query.strip():
            return ToolResult(
                success=False,
                error="query must be non-empty",
            )

        max_results = max(1, min(int(max_results or 5), 10))

        concepts_dir = _resolve_concepts_dir()
        if concepts_dir is None:
            logger.warning(
                "[search_ontos_concepts] docs/concepts/ not found at "
                f"{_DEFAULT_CONCEPTS_DIR} — returning empty matches"
            )
            return ToolResult(
                success=True,
                data={
                    "matches": [],
                    "total_files_searched": 0,
                    "message": (
                        "Concept docs not available in this deployment."
                    ),
                },
            )

        # Walk the corpus
        md_files = sorted(p for p in concepts_dir.iterdir() if p.suffix == ".md")
        # Exclude README.md — it's a meta-index, not a concept doc.
        md_files = [p for p in md_files if p.name.lower() != "readme.md"]

        tokens = _tokenize(query)
        scored: List[Tuple[float, _Section]] = []

        for md_file in md_files:
            for section in _parse_sections(md_file):
                score = _score_section(section, query, tokens)
                if score > 0:
                    scored.append((score, section))

        if not scored:
            return ToolResult(
                success=True,
                data={
                    "matches": [],
                    "total_files_searched": len(md_files),
                    "message": "No matching concept docs found.",
                },
            )

        # Sort: score desc, then file alphabetical (stable tiebreak)
        scored.sort(key=lambda x: (-x[0], x[1].file, x[1].title))

        results: List[Dict[str, Any]] = []
        for score, section in scored[:max_results]:
            anchor = section.anchor or _slugify_fallback_anchor(section.title)
            source_uri = f"{section.file}#{anchor}"
            results.append({
                "file": section.file,
                "anchor": anchor,
                "title": section.title,
                "excerpt": _truncate_excerpt(section.body),
                "source_uri": source_uri,
                "score": round(score, 2),
            })

        logger.info(
            f"[search_ontos_concepts] SUCCESS: {len(results)} matches "
            f"(searched {len(md_files)} files, {len(scored)} candidates scored)"
        )
        return ToolResult(
            success=True,
            data={
                "matches": results,
                "total_files_searched": len(md_files),
            },
        )
