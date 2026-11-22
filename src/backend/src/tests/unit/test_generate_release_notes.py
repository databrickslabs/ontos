"""Release notes from commit subjects and trailers (src/scripts/generate_release_notes.py)."""
import importlib.util
import subprocess
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[4] / "scripts" / "generate_release_notes.py"
_spec = importlib.util.spec_from_file_location("generate_release_notes", SCRIPT)
rn = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(rn)

CO_AUTHOR = "Co-authored-by: Isaac <no-reply@databricks.com>"

# A squash commit body as GitHub writes it with COMMIT_MESSAGES (see #1347 on development):
# every original commit message, each as "* <subject>", its body and its trailer block.
SQUASH_BODY = f"""* feat(assets): filter the asset list to the caller's owned assets

GET /api/assets takes owned_by_me=true to keep only the assets with an
active business-owner assignment for the current user.

Part of #1325

Upgrade-Note: GET /api/assets ignores unknown query parameters no more;
  clients that send owned_by_me must send a boolean.
{CO_AUTHOR}

* test(ui): cover the journey home for a group-matched role

The journey tests applied the role directly.

{CO_AUTHOR}

* fix(ui): count the journey's pending requests on the server

- My pending requests now asks the server for the total; before, it
  filtered the newest 100 requests in the browser.

Docs-Note: the user guide's home page section should name the journey home.
{CO_AUTHOR}
"""


def commit(subject: str, body: str = "", sha: str = "0" * 40):
    return rn.Commit(sha=sha, subject=subject, body=body)


UNRELEASED = """# Release Notes - Unreleased


## ⚠️ Upgrade Notes

- **teams**: hand-written note (#1245). What to check: the overrides.

- **assets**: second hand-written note, after a blank line.

# Release Notes - v1.1.0 (2026-10-01)


## ✨ Features

- **old**: shipped feature
"""


# --- trailers ---------------------------------------------------------------------------------


def test_trailers_spread_over_the_commits_of_a_squash_body():
    assert rn.parse_trailers(SQUASH_BODY) == [
        (
            rn.UPGRADE,
            "GET /api/assets ignores unknown query parameters no more; "
            "clients that send owned_by_me must send a boolean.",
        ),
        (rn.DOCS, "the user guide's home page section should name the journey home."),
    ]


def test_trailer_continues_on_indented_lines_only():
    body = (
        "Upgrade-Note: first line\n"
        "  second line\n"
        "\tthird line\n"
        "not a continuation\n"
        "  indented, but after a line that ended the trailer\n"
    )
    assert rn.parse_trailers(body) == [(rn.UPGRADE, "first line second line third line")]


def test_trailer_in_the_final_block_with_co_authored_by_is_a_git_trailer():
    """The documented place: the same last paragraph as Co-authored-by, so git sees it."""
    message = (
        "fix(api): reject unknown fields\n\nBody text.\n\n"
        f"Upgrade-Note: the API answers 422 to unknown fields\n{CO_AUTHOR}\n"
    )
    parsed = subprocess.run(
        ["git", "interpret-trailers", "--parse"],
        input=message, capture_output=True, text=True, check=True,
    ).stdout
    assert "Upgrade-Note: the API answers 422 to unknown fields" in parsed
    body = message.split("\n", 2)[2]
    assert rn.parse_trailers(body) == [(rn.UPGRADE, "the API answers 422 to unknown fields")]


def test_trailer_in_its_own_paragraph_before_the_trailer_block_is_found_too():
    body = f"Body text.\n\nUpgrade-Note: own paragraph\n\n{CO_AUTHOR}\n"
    assert rn.parse_trailers(body) == [(rn.UPGRADE, "own paragraph")]


def test_trailer_keys_match_without_case_and_need_the_start_of_the_line():
    body = (
        "BREAKING CHANGE: a\nBREAKING-CHANGE: b\nupgrade-note: c\nDOCS-NOTE: d\n"
        "- Upgrade-Note: inside a list item\n  Upgrade-Note: indented\n"
    )
    assert rn.parse_trailers(body) == [
        (rn.BREAKING, "a"), (rn.BREAKING, "b"), (rn.UPGRADE, "c"), (rn.DOCS, "d"),
    ]


def test_trailers_inside_fenced_code_blocks_are_not_read():
    body = (
        "Upgrade-Note: before the fence\n"
        "```text\nUpgrade-Note: in a backtick fence\n```\n"
        "~~~~\nDocs-Note: in a tilde fence\n~~~\nDocs-Note: a shorter fence does not close\n"
        "```\nDocs-Note: nor one of the other character\n~~~~~\n"
        "Docs-Note: after the fence\n"
        "  ```\n  Upgrade-Note: fence indented by up to 3 spaces\n  ```\n"
        "````\nBREAKING CHANGE: an unclosed fence runs to the end\n"
    )
    assert rn.parse_trailers(body) == [
        (rn.UPGRADE, "before the fence"), (rn.DOCS, "after the fence"),
    ]


# --- collect ----------------------------------------------------------------------------------


def test_bullets_come_from_the_squash_subject_not_from_the_body():
    notes = rn.collect([commit("feat(ui): add the journey home (#1347)", SQUASH_BODY)])
    assert notes.bullets == {"## ✨ Features": ["- **ui**: add the journey home (#1347)"]}
    assert notes.upgrade == [
        "- **ui**: GET /api/assets ignores unknown query parameters no more; "
        "clients that send owned_by_me must send a boolean. (#1347)"
    ]
    assert notes.docs == [
        "- **ui**: the user guide's home page section should name the journey home. (#1347)"
    ]


def test_a_repeated_note_is_kept_once_on_the_oldest_commit():
    child_body = f"* parent commit\n\nUpgrade-Note: same   text\n{CO_AUTHOR}\n\n* child\n"
    commits = [  # newest first, as git log
        commit("feat(b): child (#2)", child_body),
        commit("feat(a): parent (#1)", f"Upgrade-Note: same text\n{CO_AUTHOR}"),
    ]
    notes = rn.collect(commits)
    assert notes.upgrade == ["- **a**: same text (#1)"]
    assert notes.bullets["## ✨ Features"] == ["- **b**: child (#2)", "- **a**: parent (#1)"]


def test_breaking_and_upgrade_note_with_the_same_text_are_one_breaking_note():
    notes = rn.collect([
        commit("feat(api)!: drop v1 (#3)", "BREAKING CHANGE: v1 is gone"),
        commit("feat(api): warn about v1 (#2)", "Upgrade-Note: v1 is gone"),
    ])
    assert notes.upgrade == ["- **BREAKING** **api**: v1 is gone (#2)"]


def test_bang_without_a_trailer_makes_a_breaking_note_from_the_subject():
    notes = rn.collect([commit("feat(api)!: change the product response format (#9)")])
    assert notes.bullets == {
        "## ✨ Features": ["- **api**: change the product response format (#9)"]
    }
    assert notes.upgrade == ["- **BREAKING** **api**: change the product response format (#9)"]


def test_bang_with_a_trailer_uses_the_trailer_text_only():
    notes = rn.collect([
        commit("feat(api)!: new response format (#9)", f"BREAKING CHANGE: keys are camelCase\n"
                                                       f"{CO_AUTHOR}"),
    ])
    assert notes.upgrade == ["- **BREAKING** **api**: keys are camelCase (#9)"]


def test_a_note_already_written_by_hand_is_not_repeated():
    existing = (
        "## ⚠️ Upgrade Notes\n\n- **x**: Clients must send a boolean\n  for owned_by_me (#5)\n"
    )
    notes = rn.collect(
        [commit("fix(x): y (#5)", "Upgrade-Note: clients must send a boolean for owned_by_me")],
        existing,
    )
    assert notes.upgrade == []


def test_a_short_note_is_skipped_only_on_an_exact_match():
    notes = rn.collect([commit("fix(x): y", "Docs-Note: none")], "- none of this applies\n")
    assert notes.docs == ["- **x**: none"]


def test_subjects_that_are_not_conventional_go_to_other():
    notes = rn.collect([commit("Fix Standard (#764)"), commit("ci(e2e): retry (#1)")])
    assert notes.bullets == {"## 🔄 Other": ["- Fix Standard (#764)", "- **e2e**: retry (#1)"]}


# --- update_notes -----------------------------------------------------------------------------


def test_existing_unreleased_block_becomes_the_version_and_keeps_hand_written_notes():
    commits = [
        commit("feat(ui): add the journey home (#1347)", SQUASH_BODY),
        commit("fix(api)!: reject unknown fields (#1400)"),
    ]
    text, block = rn.update_notes(UNRELEASED, commits, "v1.2.0", "2026-11-22")
    assert "# Release Notes - Unreleased" not in text
    assert text.endswith("# Release Notes - v1.1.0 (2026-10-01)\n\n\n## ✨ Features\n\n"
                         "- **old**: shipped feature\n")
    assert block == (
        "# Release Notes - v1.2.0 (2026-11-22)\n\n\n"
        "## ⚠️ Upgrade Notes\n\n"
        "- **teams**: hand-written note (#1245). What to check: the overrides.\n\n"
        "- **assets**: second hand-written note, after a blank line.\n"
        "- **ui**: GET /api/assets ignores unknown query parameters no more; "
        "clients that send owned_by_me must send a boolean. (#1347)\n"
        "- **BREAKING** **api**: reject unknown fields (#1400)\n\n"
        "## 📝 Docs Notes\n\n"
        "- **ui**: the user guide's home page section should name the journey home. (#1347)\n\n"
        "## ✨ Features\n\n- **ui**: add the journey home (#1347)\n\n"
        "## 🐛 Bug Fixes\n\n- **api**: reject unknown fields (#1400)\n"
    )
    assert text.startswith(block + "\n# Release Notes - v1.1.0 (2026-10-01)")


def test_without_an_unreleased_block_the_version_goes_on_top():
    notes = UNRELEASED.split("# Release Notes - v1.1.0", 1)[1]
    text, _ = rn.update_notes("# Release Notes - v1.1.0" + notes,
                              [commit("fix: a (#1)")], "1.2.0", "2026-11-22")
    assert text.startswith(
        "# Release Notes - v1.2.0 (2026-11-22)\n\n\n## 🐛 Bug Fixes\n\n- a (#1)\n"
        "\n# Release Notes - v1.1.0"
    )


def test_hand_written_section_with_an_unknown_heading_is_kept_last():
    text = "# Release Notes - Unreleased\n\nIntro line.\n\n## Custom\n\n- kept\n"
    _, block = rn.update_notes(text, [commit("feat: f (#1)")], "1.2.0", "2026-11-22")
    assert block == ("# Release Notes - v1.2.0 (2026-11-22)\n\n\nIntro line.\n\n"
                     "## ✨ Features\n\n- f (#1)\n\n## Custom\n\n- kept\n")


def test_refuses_a_version_already_in_the_file():
    with pytest.raises(ValueError, match="already"):
        rn.update_notes(UNRELEASED, [commit("feat: f")], "1.1.0", "2026-11-22")


def test_refuses_when_there_is_nothing_to_release():
    with pytest.raises(ValueError, match="nothing to release"):
        rn.update_notes("# Release Notes - Unreleased\n\n", [], "1.2.0", "2026-11-22")


@pytest.mark.parametrize("bad", ["1.2", "1.2.0-rc1", "vv1.2.0"])
def test_refuses_a_malformed_version(bad):
    with pytest.raises(ValueError, match="invalid version"):
        rn.update_notes(UNRELEASED, [commit("feat: f")], bad, "2026-11-22")


# --- git and the CLI --------------------------------------------------------------------------


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(repo), *args], capture_output=True, text=True, check=True
    ).stdout.strip()


@pytest.fixture
def repo(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-q", "-b", "main")
    _git(repo, "config", "user.email", "test@example.com")
    _git(repo, "config", "user.name", "Test")
    _git(repo, "config", "commit.gpgsign", "false")
    _git(repo, "config", "tag.gpgsign", "false")

    def make(message: str) -> None:
        _git(repo, "commit", "-q", "--allow-empty", "-m", f"{message}\n\n{CO_AUTHOR}")

    make("chore: initial")
    _git(repo, "tag", "v1.1.0")
    make("feat(a): first (#1)\n\nUpgrade-Note: check a")
    _git(repo, "switch", "-q", "-c", "side")
    make("fix(b): on a side branch (#2)")
    _git(repo, "switch", "-q", "main")
    _git(repo, "merge", "-q", "--no-ff", "side", "-m", f"Merge side\n\nUpgrade-Note: merge\n"
                                                         f"{CO_AUTHOR}")
    return repo


def test_git_commits_reads_the_range_and_skips_merge_commits(repo):
    commits = rn.git_commits("v1.1.0", repo)
    assert [c.subject for c in commits] == ["fix(b): on a side branch (#2)", "feat(a): first (#1)"]
    assert rn.parse_trailers(commits[1].body) == [(rn.UPGRADE, "check a")]
    assert rn.last_tag(repo) == "v1.1.0"


def test_cli_writes_in_place_and_dry_run_writes_nothing(repo, tmp_path, monkeypatch, capsys):
    notes = tmp_path / "RELEASE_NOTES.md"
    notes.write_text(UNRELEASED, encoding="utf-8")
    monkeypatch.setattr(rn, "RELEASE_NOTES_PATH", notes)
    monkeypatch.chdir(repo)

    assert rn.main(["--version", "1.2.0", "--date", "2026-11-22", "--dry-run"]) == 0
    assert notes.read_text(encoding="utf-8") == UNRELEASED
    assert "- **a**: check a (#1)" in capsys.readouterr().out

    assert rn.main(["--version", "1.2.0", "--date", "2026-11-22"]) == 0
    written = notes.read_text(encoding="utf-8")
    assert written.startswith("# Release Notes - v1.2.0 (2026-11-22)")
    assert "- **a**: check a (#1)" in written and "merge" not in written
    assert "- **teams**: hand-written note (#1245)" in written
    assert not [p for p in tmp_path.iterdir() if p.name.startswith(".RELEASE_NOTES.md.")]

    assert rn.main(["--version", "1.2.0", "--date", "2026-11-22"]) == 2
    assert "already" in capsys.readouterr().err


def test_commits_of_a_past_release_squashed_on_main_are_not_listed_again(tmp_path):
    """Releases reach main as one squash commit, so their development commits are not
    ancestors of the tag and ``<tag>..HEAD`` alone would list them again."""
    repo = tmp_path / "flow"
    repo.mkdir()
    _git(repo, "init", "-q", "-b", "main")
    _git(repo, "config", "user.email", "test@example.com")
    _git(repo, "config", "user.name", "Test")
    _git(repo, "config", "commit.gpgsign", "false")
    _git(repo, "config", "tag.gpgsign", "false")

    def make(message: str) -> None:
        _git(repo, "commit", "-q", "--allow-empty", "-m", f"{message}\n\n{CO_AUTHOR}")

    make("chore: initial")
    _git(repo, "switch", "-q", "-c", "development")
    make("feat(a): released in v1.1.0 (#1)")
    _git(repo, "switch", "-q", "main")
    make("chore: release v1.1.0 (#10)\n\n* feat(a): released in v1.1.0 (#1)")
    _git(repo, "tag", "v1.1.0")
    _git(repo, "switch", "-q", "development")
    _git(repo, "merge", "-q", "--no-ff", "main", "-m", f"chore: back-merge main\n\n{CO_AUTHOR}")
    make("feat(b): new after the release (#2)")

    commits = rn.git_commits("v1.1.0", repo)
    assert [c.subject for c in commits] == [
        "feat(b): new after the release (#2)", "feat(a): released in v1.1.0 (#1)",
    ]
    kept = rn.drop_released(commits, rn.released_prs("v1.1.0", repo))
    assert [c.subject for c in kept] == ["feat(b): new after the release (#2)"]
