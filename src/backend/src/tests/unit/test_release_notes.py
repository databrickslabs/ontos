"""Release-note fragments: validation, merge, assemble, and the docs viewer."""
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from src.common.release_notes import (
    SECTIONS,
    assemble,
    load_fragments,
    merge_into_unreleased,
    validate_fragment,
)
from src.controller.settings_manager import SettingsManager

NOTES = """# Release Notes - Unreleased


## ⚠️ Upgrade Notes

- **a**: old upgrade note

# Release Notes - v1.0.0 (2026-06-22)


## ✨ Features

- **b**: old feature
"""


def _write(root: Path, section: str, name: str, text: str) -> None:
    folder = root / section
    folder.mkdir(parents=True, exist_ok=True)
    (folder / name).write_text(text, encoding="utf-8")


@pytest.mark.parametrize(
    "section,name,text,expected",
    [
        ("features", "ok.md", "- **a**: text\n  more text\n", None),
        ("nope", "ok.md", "- x", "unknown section"),
        ("features", "123.txt", "- x", "file name"),
        ("features", "Bad_Name.md", "- x", "file name"),
        ("features", "ok.md", "  \n", "empty"),
        ("features", "ok.md", "text without bullet", "start with '- '"),
        ("features", "ok.md", "- a\n- b", "second top-level bullet"),
        ("features", "ok.md", "- a\n## Heading", "headings"),
        ("features", "ok.md", "# Title\n- a", "headings"),
        ("features", "ok.md", "- a\n\n  b", "blank lines"),
    ],
)
def test_validate_fragment(section, name, text, expected):
    problems = validate_fragment(section, name, text)
    if expected is None:
        assert problems == []
    else:
        assert any(expected in p for p in problems), problems


def test_load_fragments_orders_by_section_then_name_and_reports_problems(tmp_path):
    _write(tmp_path, "bug-fixes", "b.md", "- fix b")
    _write(tmp_path, "features", "z.md", "- feat z")
    _write(tmp_path, "features", "a.md", "- feat a")
    _write(tmp_path, "features", "bad name.md", "- x")
    (tmp_path / "features" / ".gitkeep").touch()
    fragments, errors = load_fragments(tmp_path)
    assert [(f.section, f.name) for f in fragments] == [
        ("features", "a.md"),
        ("features", "z.md"),
        ("bug-fixes", "b.md"),
    ]
    assert len(errors) == 1 and errors[0].startswith("features/bad name.md:")


def test_load_fragments_missing_dir_is_empty(tmp_path):
    assert load_fragments(tmp_path / "missing") == ([], [])


def test_empty_fragment_set_changes_nothing():
    assert merge_into_unreleased(NOTES, []) == NOTES


def test_merge_appends_to_existing_section_and_inserts_new_in_order(tmp_path):
    _write(tmp_path, "upgrade-notes", "u.md", "- **u**: new upgrade note")
    _write(tmp_path, "features", "f.md", "- **f**: new feature")
    _write(tmp_path, "other", "o.md", "- **o**: other")
    fragments, _ = load_fragments(tmp_path)
    merged = merge_into_unreleased(NOTES, fragments)
    block = merged.split("# Release Notes - v1.0.0")[0]
    assert "- **a**: old upgrade note\n- **u**: new upgrade note" in block
    headings = [line for line in block.splitlines() if line.startswith("## ")]
    assert headings == ["## ⚠️ Upgrade Notes", "## ✨ Features", "## 🔄 Other"]
    # The released block below is untouched.
    assert merged.endswith("# Release Notes - v1.0.0 (2026-06-22)" + NOTES.split("(2026-06-22)")[1])


def test_merge_creates_the_block_when_missing(tmp_path):
    _write(tmp_path, "bug-fixes", "x.md", "- **x**: fixed")
    fragments, _ = load_fragments(tmp_path)
    merged = merge_into_unreleased("# Release Notes - v1.0.0 (2026-06-22)\n\nbody\n", fragments)
    assert merged.startswith("# Release Notes - Unreleased\n")
    assert "## 🐛 Bug Fixes\n\n- **x**: fixed" in merged
    assert merged.index("Unreleased") < merged.index("v1.0.0")


def test_merge_into_empty_block_keeps_next_release_separate(tmp_path):
    _write(tmp_path, "features", "f.md", "- **f**: new")
    fragments, _ = load_fragments(tmp_path)
    merged = merge_into_unreleased(
        "# Release Notes - Unreleased\n\n# Release Notes - v1.0.0 (2026-06-22)\n", fragments
    )
    assert "## ✨ Features\n\n- **f**: new\n\n# Release Notes - v1.0.0" in merged


def test_assemble_names_the_release_and_adds_a_fresh_unreleased(tmp_path):
    _write(tmp_path, "features", "f.md", "- **f**: new feature")
    fragments, _ = load_fragments(tmp_path)
    result = assemble(NOTES, fragments, "1.2.0", "2026-12-01")
    lines = result.splitlines()
    assert lines[0] == "# Release Notes - Unreleased"
    assert result.count("# Release Notes - Unreleased") == 1
    assert "# Release Notes - v1.2.0 (2026-12-01)" in lines
    after_heading = result.split("# Release Notes - v1.2.0 (2026-12-01)")[1]
    released = after_heading.split("# Release Notes - v1.0.0")[0]
    assert "- **a**: old upgrade note" in released and "- **f**: new feature" in released


def test_assemble_without_block_or_fragments_fails():
    with pytest.raises(ValueError):
        assemble("# Release Notes - v1.0.0 (2026-06-22)\n", [], "1.2.0", "2026-12-01")


def test_sections_match_the_headings_in_the_release_notes_file():
    notes = (Path(__file__).resolve().parents[4] / "docs" / "RELEASE_NOTES.md").read_text(
        encoding="utf-8"
    )
    for _, heading in SECTIONS:
        assert f"\n{heading}\n" in notes


def _manager(tmp_path, monkeypatch) -> SettingsManager:
    docs = tmp_path / "docs"
    docs.mkdir()
    (docs / "docs.yaml").write_text(
        "documents:\n"
        "  release-notes:\n"
        "    file: RELEASE_NOTES.md\n"
        "    title: Release Notes\n"
        "    description: d\n"
        "    release_note_fragments: release-notes/unreleased\n"
        "  plain:\n"
        "    file: PLAIN.md\n"
        "    title: Plain\n"
        "    description: d\n",
        encoding="utf-8",
    )
    (docs / "RELEASE_NOTES.md").write_text(NOTES, encoding="utf-8")
    (docs / "PLAIN.md").write_text("plain", encoding="utf-8")
    manager = SettingsManager(db=MagicMock(), settings=MagicMock())
    monkeypatch.setattr(manager, "_get_docs_directory", lambda: docs)
    return manager


def test_docs_viewer_merges_fragments_without_touching_the_file(tmp_path, monkeypatch):
    manager = _manager(tmp_path, monkeypatch)
    docs = tmp_path / "docs"
    _write(docs / "release-notes" / "unreleased", "features", "f.md", "- **f**: from fragment")
    content = manager.get_documentation_content("release-notes")["content"]
    assert "- **f**: from fragment" in content
    assert (docs / "RELEASE_NOTES.md").read_text(encoding="utf-8") == NOTES
    assert manager.get_documentation_content("plain")["content"] == "plain"


def test_docs_viewer_without_fragments_serves_the_file_as_is(tmp_path, monkeypatch):
    manager = _manager(tmp_path, monkeypatch)
    assert manager.get_documentation_content("release-notes")["content"] == NOTES
