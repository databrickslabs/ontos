"""Release-note fragments: parse, validate and render.

Each PR adds one file ``<section>/<slug>.md`` under ``unreleased/`` instead of
editing ``RELEASE_NOTES.md``, so two PRs never touch the same path. The file
holds exactly one bullet entry. At release time the fragments are written into
the ``# Release Notes - Unreleased`` block (see ``assemble_release_notes.py``),
and the docs viewer shows them in that block without changing the file.

This module uses only the standard library: the assembler CLI and the CI check
load it by path, without installing the backend dependencies.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Tuple

UNRELEASED_HEADING = "# Release Notes - Unreleased"
_VERSION_HEADING_PREFIX = "# Release Notes - "

# (folder key, heading in RELEASE_NOTES.md), in the order the sections are rendered.
SECTIONS: List[Tuple[str, str]] = [
    ("upgrade-notes", "## ⚠️ Upgrade Notes"),
    ("features", "## ✨ Features"),
    ("bug-fixes", "## 🐛 Bug Fixes"),
    ("documentation", "## 📚 Documentation"),
    ("performance", "## ⚡ Performance"),
    ("refactoring", "## ♻️ Refactoring"),
    ("testing", "## 🧪 Testing"),
    ("maintenance", "## 🔧 Maintenance"),
    ("other", "## 🔄 Other"),
]
SECTION_HEADINGS: Dict[str, str] = dict(SECTIONS)

FILE_NAME_RE = re.compile(r"^[a-z0-9][a-z0-9-]*\.md$")
_TOP_LEVEL_BULLET_RE = re.compile(r"^[-*+]\s")
_HEADING_RE = re.compile(r"^#{1,6}\s")


@dataclass(frozen=True)
class Fragment:
    section: str
    name: str
    entry: str
    path: Path


def validate_fragment(section: str, name: str, text: str) -> List[str]:
    """Return the problems of one fragment (empty list when it is valid)."""
    problems: List[str] = []
    if section not in SECTION_HEADINGS:
        problems.append(
            f"unknown section '{section}' (expected one of: {', '.join(SECTION_HEADINGS)})"
        )
    if not FILE_NAME_RE.match(name):
        problems.append(
            f"file name '{name}' must match [a-z0-9][a-z0-9-]*.md (a unique slug, not a PR number)"
        )
    lines = text.strip().splitlines()
    if not lines:
        problems.append("the fragment is empty")
        return problems
    if not lines[0].startswith("- "):
        problems.append("the entry must start with '- ' (one bullet, e.g. '- **area**: text')")
    for number, line in enumerate(lines[1:], start=2):
        if not line.strip():
            problems.append(f"line {number}: blank lines are not allowed inside the entry")
        elif _HEADING_RE.match(line):
            problems.append(f"line {number}: headings are not allowed in a fragment")
        elif _TOP_LEVEL_BULLET_RE.match(line):
            problems.append(f"line {number}: only one entry per fragment (second top-level bullet)")
    if _HEADING_RE.match(lines[0]):
        problems.append("line 1: headings are not allowed in a fragment")
    return problems


def validate_file(path: Path) -> List[str]:
    """Validate one fragment file; the section is the name of its parent folder."""
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return ["cannot be read as UTF-8 text"]
    return validate_fragment(path.parent.name, path.name, text)


def load_fragments(unreleased_dir: Path) -> Tuple[List[Fragment], List[str]]:
    """Read every fragment under ``unreleased_dir``.

    Returns the valid fragments (section order, then file name) and one
    ``<path>: <problem>`` line per problem found. ``.gitkeep`` files are ignored.
    """
    fragments: List[Fragment] = []
    errors: List[str] = []
    if not unreleased_dir.is_dir():
        return fragments, errors
    for section_dir in sorted(unreleased_dir.iterdir()):
        if section_dir.name == ".gitkeep":
            continue
        if not section_dir.is_dir():
            errors.append(f"{section_dir.name}: only section folders are allowed here")
            continue
        for path in sorted(section_dir.iterdir()):
            if path.name == ".gitkeep":
                continue
            label = f"{section_dir.name}/{path.name}"
            if not path.is_file():
                errors.append(f"{label}: only fragment files are allowed here")
                continue
            problems = validate_file(path)
            if problems:
                errors.extend(f"{label}: {problem}" for problem in problems)
                continue
            fragments.append(
                Fragment(
                    section=section_dir.name,
                    name=path.name,
                    entry=path.read_text(encoding="utf-8").strip(),
                    path=path,
                )
            )
    order = {key: index for index, (key, _) in enumerate(SECTIONS)}
    fragments.sort(key=lambda f: (order[f.section], f.name))
    return fragments, errors


def _group(fragments: List[Fragment]) -> Dict[str, List[str]]:
    grouped: Dict[str, List[str]] = {}
    for fragment in fragments:
        grouped.setdefault(fragment.section, []).append(fragment.entry)
    return grouped


def _is_release_heading(line: str) -> bool:
    return line.startswith(_VERSION_HEADING_PREFIX)


def merge_into_unreleased(notes: str, fragments: List[Fragment]) -> str:
    """Return ``notes`` with the fragments added to the Unreleased block.

    The block is created at the top when missing. Entries go at the end of the
    section of the same name when the block has one, else a new section is
    inserted in the standard order. No fragments: ``notes`` is returned as is.
    """
    if not fragments:
        return notes
    grouped = _group(fragments)
    lines = notes.split("\n")

    start = next((i for i, line in enumerate(lines) if line.strip() == UNRELEASED_HEADING), None)
    if start is None:
        lines = [UNRELEASED_HEADING, "", ""] + lines
        start = 0
    end = next(
        (i for i in range(start + 1, len(lines)) if _is_release_heading(lines[i])), len(lines)
    )

    block = lines[start + 1 : end]
    for key, heading in SECTIONS:
        entries = grouped.get(key)
        if not entries:
            continue
        heading_at = next((i for i, line in enumerate(block) if line.strip() == heading), None)
        if heading_at is not None:
            stop = next(
                (i for i in range(heading_at + 1, len(block)) if block[i].startswith("## ")),
                len(block),
            )
            last = stop
            while last > heading_at + 1 and not block[last - 1].strip():
                last -= 1
            block[last:last] = entries
            continue
        # New section: before the first existing section that comes later in the order.
        later = [h for k, h in SECTIONS[[k for k, _ in SECTIONS].index(key) + 1 :]]
        insert_at = next((i for i, line in enumerate(block) if line.strip() in later), None)
        new_section = [heading, ""] + entries + [""]
        if insert_at is None:
            while block and not block[-1].strip():
                block.pop()
            block += [""] + new_section if block else new_section
        else:
            block[insert_at:insert_at] = new_section
    # Keep the usual blank lines after the heading.
    if not block or block[0].strip():
        block.insert(0, "")
    return "\n".join(lines[: start + 1] + block + lines[end:])


def assemble(notes: str, fragments: List[Fragment], version: str, date: str) -> str:
    """Write the fragments into the Unreleased block, name it after the release
    and add a fresh empty Unreleased heading above it."""
    merged = merge_into_unreleased(notes, fragments)
    lines = merged.split("\n")
    start = next((i for i, line in enumerate(lines) if line.strip() == UNRELEASED_HEADING), None)
    released = f"{_VERSION_HEADING_PREFIX}v{version} ({date})"
    if start is None:
        raise ValueError("no Unreleased block and no fragments: nothing to release")
    lines[start] = released
    return "\n".join(lines[:start] + [UNRELEASED_HEADING, "", ""] + lines[start:])


def render_unreleased_view(notes: str, unreleased_dir: Optional[Path]) -> str:
    """Notes as shown in the docs viewer: valid fragments merged, invalid ones skipped."""
    if unreleased_dir is None:
        return notes
    fragments, _ = load_fragments(unreleased_dir)
    return merge_into_unreleased(notes, fragments)
