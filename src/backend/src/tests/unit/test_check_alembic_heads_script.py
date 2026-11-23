"""Tests for scripts/check-alembic-heads.py on the PR's merge result.

The CI checkout of a pull_request run is a snapshot of the merge taken when the PR
was last updated. A revision merged into the base afterwards is missing from it, so
two PRs on the same parent each pass alone. MERGE_BASE=1 merges the base's current
tip first.
"""

import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[5] / "scripts" / "check-alembic-heads.py"

REVISION = (
    "revision = '{rev}'\n"
    "down_revision = {down}\n"
    "branch_labels = None\n"
    "depends_on = None\n\n"
    "def upgrade():\n    pass\n\n"
    "def downgrade():\n    pass\n"
)


def _git(repo: Path, *args: str) -> str:
    cmd = ["git", "-c", "user.name=t", "-c", "user.email=t@example.com",
           "-c", "commit.gpgsign=false", *args]
    # Isolated from the user's git config: the repo is synthetic
    env = {**os.environ, "GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_NOSYSTEM": "1"}
    return subprocess.run(cmd, cwd=repo, check=True, text=True, env=env,
                          capture_output=True).stdout


def _revision(repo: Path, rev: str, down: str | None) -> None:
    versions = repo / "src" / "backend" / "alembic" / "versions"
    versions.mkdir(parents=True, exist_ok=True)
    (versions / f"{rev}.py").write_text(
        REVISION.format(rev=rev, down=repr(down) if down else "None"))
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", f"add {rev}")


def _check(repo: Path, merge: bool) -> subprocess.CompletedProcess:
    env = {"PATH": "/usr/bin:/bin", "BASE_REF": "main", "HOME": str(repo)}
    if merge:
        env["MERGE_BASE"] = "1"
    return subprocess.run([sys.executable, "scripts/check-alembic-heads.py"], cwd=repo,
                          env=env, text=True, capture_output=True)


@pytest.fixture
def repo(tmp_path):
    """main carries revision a; the pr branch is cut from it."""
    root = tmp_path / "repo"
    (root / "scripts").mkdir(parents=True)
    shutil.copy(SCRIPT, root / "scripts" / "check-alembic-heads.py")
    ini = root / "src" / "backend" / "alembic.ini"
    ini.parent.mkdir(parents=True)
    ini.write_text("[alembic]\nscript_location = alembic\n")
    _git(root, "init", "-q", "-b", "main")
    _revision(root, "a", None)
    _git(root, "checkout", "-q", "-b", "pr")
    return root


def test_sibling_added_to_the_base_after_the_pr_is_caught_on_the_merge_result(repo):
    _revision(repo, "b", "a")  # the PR's revision
    _git(repo, "checkout", "-q", "main")
    _revision(repo, "c", "a")  # merged into the base after the PR's last update
    _git(repo, "checkout", "-q", "pr")

    stale = _check(repo, merge=False)  # what the PR's own tree shows
    assert stale.returncode == 0, stale.stderr
    merged = _check(repo, merge=True)
    assert merged.returncode == 1
    assert "Multiple Alembic heads" in merged.stderr


def test_pr_chained_on_the_current_base_head_passes_on_the_merge_result(repo):
    _git(repo, "checkout", "-q", "main")
    _revision(repo, "c", "a")
    _git(repo, "checkout", "-q", "pr")
    _git(repo, "merge", "-q", "--no-edit", "main")
    _revision(repo, "b", "c")
    result = _check(repo, merge=True)
    assert result.returncode == 0, result.stderr


def test_pr_without_migrations_passes_when_the_base_moved(repo):
    _git(repo, "checkout", "-q", "main")
    _revision(repo, "c", "a")
    _git(repo, "checkout", "-q", "pr")
    result = _check(repo, merge=True)
    assert result.returncode == 0, result.stderr


def test_conflict_with_the_base_fails_the_merge_check(repo):
    _revision(repo, "b", "a")
    (repo / "same.txt").write_text("pr\n")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "pr file")
    _git(repo, "checkout", "-q", "main")
    (repo / "same.txt").write_text("main\n")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "main file")
    _git(repo, "checkout", "-q", "pr")
    result = _check(repo, merge=True)
    assert result.returncode == 1
    assert "Could not merge main" in result.stderr
