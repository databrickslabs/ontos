"""Regression tests for the ``scripts/bump_version.py`` pyproject.toml scoping fix.

The version bumper edits ``pyproject.toml`` with a regex substitution. A prior
bug used an unanchored pattern with a global ``re.sub``, so bumping the project
version also clobbered ``[tool.ruff]``'s ``target-version`` (and would clobber a
``version`` key under any other table). The fix scopes the pattern to the
``[project]`` table and passes ``count=1``.

These tests pin that behavioral guarantee: bumping rewrites ONLY the
``[project]`` table's ``version`` key and leaves ``target-version`` and a decoy
table's ``version`` untouched. They are hermetic — the module is loaded straight
from its file path and all edits happen against ``tmp_path``, never the real
repo ``pyproject.toml``.
"""
from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

# Load scripts/bump_version.py directly by path so the test does not depend on
# ``scripts`` being importable as a package from the pytest rootdir.
_SRC_ROOT = Path(__file__).resolve().parents[2]  # .../src
_BUMP_PATH = _SRC_ROOT / "scripts" / "bump_version.py"
_spec = importlib.util.spec_from_file_location("bump_version_under_test", _BUMP_PATH)
bump_version = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(bump_version)


# TOML content exercising every case the scoped pattern must distinguish:
#   - the real [project].version         -> MUST be bumped
#   - a decoy [tool.decoy].version        -> MUST be left alone
#   - [tool.ruff].target-version          -> MUST be left alone
_SAMPLE_TOML = """\
[build-system]
requires = ["hatchling>=1.21.0"]
build-backend = "hatchling.build"

[project]
name = "ontos"
version = "1.0.1"
requires-python = ">=3.11,<3.13"

[tool.decoy]
version = "9.9.9"

[tool.ruff]
target-version = "py311"
line-length = 100
"""


def _pyproject_entry():
    """Return the VERSION_FILES entry (pattern, replacement) for pyproject.toml."""
    for rel_path, is_json, pattern, replacement in bump_version.VERSION_FILES:
        if rel_path == "pyproject.toml":
            return pattern, replacement
    raise AssertionError("pyproject.toml entry missing from VERSION_FILES")


def test_bump_rewrites_only_project_version(tmp_path: Path):
    """Bumping rewrites ONLY [project].version; decoy + target-version survive."""
    pyproject = tmp_path / "pyproject.toml"
    pyproject.write_text(_SAMPLE_TOML, encoding="utf-8")

    pattern, replacement = _pyproject_entry()
    old_version = bump_version.update_text_version(
        pyproject, pattern, replacement, "2.3.4"
    )

    assert old_version == "1.0.1"

    result = pyproject.read_text(encoding="utf-8")

    # The [project] version was bumped, exactly once.
    assert 'version = "2.3.4"' in result
    assert result.count('version = "2.3.4"') == 1

    # The decoy table's version and ruff's target-version are untouched.
    assert 'version = "9.9.9"' in result
    assert 'target-version = "py311"' in result

    # And no residue of the old project version remains.
    assert '"1.0.1"' not in result


def test_get_current_version_reads_project_version(tmp_path: Path):
    """The read path returns the [project] version, not the decoy value."""
    pyproject = tmp_path / "pyproject.toml"
    pyproject.write_text(_SAMPLE_TOML, encoding="utf-8")

    assert bump_version.get_current_version(tmp_path) == "1.0.1"


def test_pattern_matches_project_version_exactly_once():
    """The pyproject pattern matches the [project] version and nothing else."""
    import re

    pattern, _ = _pyproject_entry()
    matches = re.findall(pattern, _SAMPLE_TOML)
    assert len(matches) == 1
