"""Release-note fragments: validation, merge, assemble, and the docs viewer."""
import importlib.util
import os
import sys
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
        ("upgrade-notes", "ok.md", "- **a**: text", "What to check:"),
        ("upgrade-notes", "ok.md", "- **a**: text\n  What to check: the setting", None),
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
    _write(tmp_path, "upgrade-notes", "u.md", "- **u**: new upgrade note. What to check: x")
    _write(tmp_path, "features", "f.md", "- **f**: new feature")
    _write(tmp_path, "other", "o.md", "- **o**: other")
    fragments, _ = load_fragments(tmp_path)
    merged = merge_into_unreleased(NOTES, fragments)
    block = merged.split("# Release Notes - v1.0.0")[0]
    assert "- **a**: old upgrade note\n- **u**: new upgrade note. What to check: x" in block
    headings = [line for line in block.splitlines() if line.startswith("## ")]
    assert headings == ["## ⚠️ Upgrade Notes", "## ✨ Features", "## 🔄 Other"]
    # The released block below is untouched.
    assert merged.endswith("# Release Notes - v1.0.0 (2026-06-22)" + NOTES.split("(2026-06-22)")[1])


MIXED = """# Release Notes - Unreleased

## ✨ Features

- old f

## 🐛 Bug Fixes

- old b

# Release Notes - v1.0.0 (2026-06-22)
"""


def test_merge_appends_before_the_next_section(tmp_path):
    _write(tmp_path, "features", "f.md", "- **f**: new")
    fragments, _ = load_fragments(tmp_path)
    merged = merge_into_unreleased(MIXED, fragments)
    assert "- old f\n- **f**: new\n\n## 🐛 Bug Fixes\n\n- old b\n" in merged


def test_merge_inserts_a_new_section_before_a_later_existing_one(tmp_path):
    _write(tmp_path, "upgrade-notes", "u.md", "- **u**: note. What to check: x")
    _write(tmp_path, "documentation", "d.md", "- **d**: docs")
    fragments, _ = load_fragments(tmp_path)
    merged = merge_into_unreleased(MIXED, fragments)
    block = merged.split("# Release Notes - v1")[0]
    headings = [ln for ln in block.splitlines() if ln.startswith("## ")]
    assert headings == [
        "## ⚠️ Upgrade Notes",
        "## ✨ Features",
        "## 🐛 Bug Fixes",
        "## 📚 Documentation",
    ]
    assert (
        "## ⚠️ Upgrade Notes\n\n- **u**: note. What to check: x\n\n## ✨ Features\n\n- old f"
        in merged
    )
    assert "- old b\n\n## 📚 Documentation\n\n- **d**: docs\n\n# Release Notes - v1" in merged


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


def test_assemble_twice_refuses_the_second_run(tmp_path):
    _write(tmp_path, "features", "f.md", "- **f**: new feature")
    fragments, _ = load_fragments(tmp_path)
    released = assemble(NOTES, fragments, "1.2.0", "2026-12-01")
    with pytest.raises(ValueError, match="nothing to release"):
        assemble(released, [], "1.2.1", "2026-12-02")


def test_assemble_without_fragments_releases_entries_already_in_the_block():
    result = assemble(NOTES, [], "1.2.0", "2026-12-01")
    assert "# Release Notes - v1.2.0 (2026-12-01)\n\n\n## ⚠️ Upgrade Notes" in result


@pytest.mark.parametrize("given", ["1.2.0", "v1.2.0"])
def test_assemble_accepts_a_version_with_or_without_v(given):
    result = assemble(NOTES, [], given, "2026-12-01")
    assert "# Release Notes - v1.2.0 (2026-12-01)" in result
    assert "vv1.2.0" not in result


@pytest.mark.parametrize("bad", ["1.2", "1.2.0-rc1", "vv1.2.0", "", "V1.2.0", "1.2.x"])
def test_assemble_rejects_a_malformed_version(bad):
    with pytest.raises(ValueError, match="invalid version"):
        assemble(NOTES, [], bad, "2026-12-01")


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


@pytest.mark.parametrize("absolute", [False, True])
def test_docs_viewer_ignores_a_fragment_folder_outside_the_docs_directory(
    tmp_path, monkeypatch, absolute
):
    manager = _manager(tmp_path, monkeypatch)
    docs = tmp_path / "docs"
    outside = tmp_path / "outside"
    _write(outside, "features", "f.md", "- **f**: from outside")
    folder = str(outside) if absolute else "../outside"
    yaml_path = docs / "docs.yaml"
    yaml_path.write_text(
        yaml_path.read_text(encoding="utf-8").replace("release-notes/unreleased", folder),
        encoding="utf-8",
    )
    content = manager.get_documentation_content("release-notes")["content"]
    assert content == NOTES


def test_docs_viewer_without_fragments_serves_the_file_as_is(tmp_path, monkeypatch):
    manager = _manager(tmp_path, monkeypatch)
    assert manager.get_documentation_content("release-notes")["content"] == NOTES


SCRIPT = Path(__file__).resolve().parents[4] / "scripts" / "assemble_release_notes.py"


@pytest.fixture
def cli(tmp_path, monkeypatch):
    """The assembler CLI module, pointed at a temporary notes file and fragment folder."""
    spec = importlib.util.spec_from_file_location("assemble_release_notes_cli", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    notes = tmp_path / "RELEASE_NOTES.md"
    notes.write_text(NOTES, encoding="utf-8")
    unreleased = tmp_path / "unreleased"
    unreleased.mkdir()
    monkeypatch.setattr(module, "NOTES_PATH", notes)
    monkeypatch.setattr(module, "UNRELEASED_DIR", unreleased)

    def run(*args: str) -> int:
        monkeypatch.setattr(sys, "argv", ["assemble_release_notes.py", *args])
        return module.main()

    run.notes = notes
    run.unreleased = unreleased
    return run


@pytest.mark.parametrize("bad", ["1.2", "1.2.0-rc1", "vv1.2.0"])
def test_cli_rejects_a_malformed_version(cli, bad, capsys):
    with pytest.raises(SystemExit) as exit_info:
        cli("--version", bad)
    assert exit_info.value.code == 2
    assert "invalid version" in capsys.readouterr().err
    assert cli.notes.read_text(encoding="utf-8") == NOTES


def test_cli_strips_a_leading_v(cli):
    _write(cli.unreleased, "features", "f.md", "- **f**: new")
    assert cli("--version", "v1.2.0", "--date", "2026-12-01") == 0
    text = cli.notes.read_text(encoding="utf-8")
    assert "# Release Notes - v1.2.0 (2026-12-01)" in text and "vv1.2.0" not in text


def test_cli_writes_the_notes_and_deletes_the_fragments(cli, capsys):
    _write(cli.unreleased, "features", "f.md", "- **f**: new")
    _write(cli.unreleased, "bug-fixes", "b.md", "- **b**: fixed")
    assert cli("--version", "1.2.0", "--date", "2026-12-01") == 0
    text = cli.notes.read_text(encoding="utf-8")
    assert "- **f**: new" in text and "- **b**: fixed" in text
    assert not (cli.unreleased / "features" / "f.md").exists()
    assert not (cli.unreleased / "bug-fixes" / "b.md").exists()
    assert not cli.notes.with_name(cli.notes.name + ".tmp").exists()
    assert "Released 2 fragment(s)" in capsys.readouterr().out


def test_cli_second_run_does_not_write_an_empty_release(cli, capsys):
    _write(cli.unreleased, "features", "f.md", "- **f**: new")
    assert cli("--version", "1.2.0", "--date", "2026-12-01") == 0
    after_first = cli.notes.read_text(encoding="utf-8")
    assert cli("--version", "1.2.1", "--date", "2026-12-02") == 1
    assert cli.notes.read_text(encoding="utf-8") == after_first
    assert "nothing to release" in capsys.readouterr().out


def test_cli_keeps_the_notes_and_fragments_when_the_swap_fails(cli, monkeypatch):
    _write(cli.unreleased, "features", "f.md", "- **f**: new")

    def broken_replace(src, dst):
        raise OSError("disk full")

    monkeypatch.setattr(os, "replace", broken_replace)
    with pytest.raises(OSError):
        cli("--version", "1.2.0", "--date", "2026-12-01")
    assert cli.notes.read_text(encoding="utf-8") == NOTES
    assert (cli.unreleased / "features" / "f.md").exists()
    assert not cli.notes.with_name(cli.notes.name + ".tmp").exists()


def test_cli_reports_fragments_it_could_not_delete(cli, monkeypatch, capsys):
    _write(cli.unreleased, "features", "f.md", "- **f**: new")
    original_unlink = Path.unlink

    def failing_unlink(self, *args, **kwargs):
        if self.name == "f.md":
            raise PermissionError("denied")
        return original_unlink(self, *args, **kwargs)

    monkeypatch.setattr(Path, "unlink", failing_unlink)
    assert cli("--version", "1.2.0", "--date", "2026-12-01") == 1
    out = capsys.readouterr().out
    assert "could not delete 1 fragment(s)" in out and "features/f.md" in out
    assert "# Release Notes - v1.2.0 (2026-12-01)" in cli.notes.read_text(encoding="utf-8")


def test_cli_check_reports_one_line_per_problem_and_fails(cli, capsys):
    _write(cli.unreleased, "features", "ok.md", "- **f**: fine")
    _write(cli.unreleased, "features", "bad.md", "no bullet")
    ok = cli.unreleased / "features" / "ok.md"
    bad = cli.unreleased / "features" / "bad.md"
    assert cli("--check", str(ok), str(bad)) == 1
    lines = capsys.readouterr().out.splitlines()
    assert len(lines) == 1 and lines[0].startswith(str(bad))


def test_cli_check_reports_a_missing_file(cli, capsys):
    assert cli("--check", str(cli.unreleased / "missing.md")) == 1
    assert "file not found" in capsys.readouterr().out


def test_cli_check_without_files_validates_the_whole_folder(cli, capsys):
    _write(cli.unreleased, "features", "ok.md", "- **f**: fine")
    assert cli("--check") == 0
    assert capsys.readouterr().out == ""
    _write(cli.unreleased, "features", "bad.md", "no bullet")
    assert cli("--check") == 1
    assert "features/bad.md" in capsys.readouterr().out


def test_cli_refuses_to_release_with_invalid_fragments(cli, capsys):
    _write(cli.unreleased, "features", "ok.md", "- **f**: fine")
    _write(cli.unreleased, "features", "bad.md", "no bullet")
    assert cli("--version", "1.2.0", "--date", "2026-12-01") == 1
    assert "features/bad.md" in capsys.readouterr().out
    assert cli.notes.read_text(encoding="utf-8") == NOTES
    assert (cli.unreleased / "features" / "ok.md").exists()
    assert (cli.unreleased / "features" / "bad.md").exists()
