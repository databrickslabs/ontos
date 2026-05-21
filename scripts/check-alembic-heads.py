#!/usr/bin/env python3
"""Enforce single-head Alembic migration history on PRs.

Two checks, both fatal:

  1. ``alembic heads`` against the PR's ``versions/`` tree must return exactly
     one head.
  2. For each newly added revision file in the PR (vs. ``$BASE_REF``), its
     ``down_revision`` must be reachable from the base branch's tip — i.e. the
     PR was rebased onto current main before the migration was authored.
     Multi-parent down_revisions (intentional merge revisions) are also
     accepted as long as every parent is reachable.

Bypass: this script is short-circuited at the workflow level when the PR has
the ``alembic-branch`` label. There is no in-script escape hatch.

Environment:
  BASE_REF   git ref of the PR base (default: ``origin/main``).

Exit codes:
  0 — pass.
  1 — one or both invariants violated.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from alembic.config import Config
from alembic.script import ScriptDirectory

REPO_ROOT = Path(__file__).resolve().parent.parent
INI_PATH = REPO_ROOT / "src" / "backend" / "alembic.ini"
VERSIONS_REL = "src/backend/alembic/versions"


def info(msg: str) -> None:
    print(msg, flush=True)


def fail(msg: str) -> None:
    # Emit a GitHub Actions error annotation as well as a human-readable trace.
    first_line, _, rest = msg.partition("\n")
    print(f"::error::{first_line}", file=sys.stderr, flush=True)
    if rest:
        print(rest, file=sys.stderr, flush=True)
    sys.exit(1)


def load_script_dir(ini_path: Path) -> ScriptDirectory:
    # ``script_location`` in alembic.ini is resolved relative to CWD and is
    # re-read on each operation. Force it to an absolute path so subsequent
    # calls (e.g. get_heads, walk_revisions) don't depend on CWD.
    cfg = Config(str(ini_path))
    rel = cfg.get_main_option("script_location") or "alembic"
    cfg.set_main_option("script_location", str((ini_path.parent / rel).resolve()))
    return ScriptDirectory.from_config(cfg)


def list_new_revision_files(base_ref: str) -> list[str]:
    """Repo-relative paths of revision .py files added in the PR."""
    out = subprocess.check_output(
        [
            "git",
            "diff",
            "--name-only",
            "--diff-filter=A",
            f"{base_ref}...HEAD",
            "--",
            f"{VERSIONS_REL}/*.py",
        ],
        cwd=REPO_ROOT,
        text=True,
    )
    return [
        line.strip()
        for line in out.splitlines()
        if line.strip().endswith(".py") and not line.strip().endswith("__init__.py")
    ]


def materialize_base_versions(base_ref: str, dest_dir: Path) -> Path:
    """Reconstruct a minimal alembic tree from ``base_ref`` under ``dest_dir``.

    Returns the path to the staged ``alembic.ini``.
    """
    versions_out = dest_dir / "alembic" / "versions"
    versions_out.mkdir(parents=True, exist_ok=True)

    # Minimal ini — only ``script_location`` matters for ScriptDirectory.
    ini_out = dest_dir / "alembic.ini"
    ini_out.write_text("[alembic]\nscript_location = alembic\n")

    listing = subprocess.check_output(
        ["git", "ls-tree", "-r", "--name-only", base_ref, VERSIONS_REL],
        cwd=REPO_ROOT,
        text=True,
    )
    for path in listing.splitlines():
        if not path.endswith(".py"):
            continue
        content = subprocess.check_output(
            ["git", "show", f"{base_ref}:{path}"],
            cwd=REPO_ROOT,
            text=True,
        )
        (versions_out / Path(path).name).write_text(content)

    return ini_out


def base_revision_ids(base_ref: str) -> set[str]:
    with tempfile.TemporaryDirectory(prefix="alembic-base-") as tmp:
        ini = materialize_base_versions(base_ref, Path(tmp))
        sd = load_script_dir(ini)
        return {r.revision for r in sd.walk_revisions()}


def _as_tuple(down) -> tuple[str, ...]:
    if down is None:
        return ()
    if isinstance(down, str):
        return (down,)
    return tuple(down)


def main() -> int:
    base_ref = os.environ.get("BASE_REF", "origin/main")

    # --- Check 1: single head on the PR tree -------------------------------
    info(f"[1/2] Loading alembic script directory from {INI_PATH}…")
    sd = load_script_dir(INI_PATH)
    heads = sd.get_heads()
    if len(heads) > 1:
        merge_cmd = "alembic merge -m 'merge heads' " + " ".join(heads)
        fail(
            "Multiple Alembic heads detected on PR branch: "
            + ", ".join(heads)
            + "\n\n"
            "This happens when two PRs branched off the same alembic tip and each\n"
            "added a sibling revision. App startup will fail with\n"
            '  "script directory has multiple heads"\n'
            "until they are reconciled.\n\n"
            "Remediate by either:\n"
            f"  (a) rebasing onto current {base_ref} and re-authoring your revision so it\n"
            "      descends from the new tip, OR\n"
            f"  (b) running `{merge_cmd}` and committing the resulting merge revision.\n\n"
            "If the divergence is intentional and a merge revision is planned in this PR,\n"
            "apply the `alembic-branch` label to bypass this check."
        )
    info(f"      ok — single head: {heads[0] if heads else '(none)'}")

    # --- Check 2: new revisions descend from base tip ----------------------
    info(f"[2/2] Diffing new revisions vs {base_ref}…")
    new_files = list_new_revision_files(base_ref)
    if not new_files:
        info("      no new revision files in this PR.")
        return 0
    info(f"      found {len(new_files)} new revision file(s): "
         + ", ".join(Path(p).name for p in new_files))

    base_revs = base_revision_ids(base_ref)
    info(f"      base ({base_ref}) carries {len(base_revs)} revision(s).")

    new_file_basenames = {Path(p).name for p in new_files}
    new_revs_in_pr: dict[str, tuple[str, ...]] = {}
    for rev in sd.walk_revisions():
        rev_file = Path(rev.path).name if getattr(rev, "path", None) else None
        if rev_file in new_file_basenames:
            new_revs_in_pr[rev.revision] = _as_tuple(rev.down_revision)

    if not new_revs_in_pr:
        fail(
            "Diff reports new revision files but ScriptDirectory found no matching\n"
            "revisions. Are the files importable? Files: "
            + ", ".join(new_file_basenames)
        )

    new_ids = set(new_revs_in_pr)
    unreachable: list[tuple[str, str]] = []
    for rev_id, downs in new_revs_in_pr.items():
        if not downs:
            # initial migration is only valid against an empty base
            if base_revs:
                unreachable.append(
                    (rev_id, "down_revision is None but base already has migrations")
                )
            continue
        for parent in downs:
            if parent not in base_revs and parent not in new_ids:
                unreachable.append(
                    (rev_id, f"down_revision {parent!r} not present in {base_ref}")
                )

    if unreachable:
        lines = ["Newly added Alembic revision(s) do not descend from the base tip:"]
        for rev_id, reason in unreachable:
            lines.append(f"  - {rev_id}: {reason}")
        lines += [
            "",
            f"Rebase your branch onto current {base_ref}, drop your revision file(s),",
            "and re-run `alembic revision -m '<your message>'` so the new revision",
            "descends from the live head. Then re-commit.",
            "",
            "Apply the `alembic-branch` PR label to bypass if the divergence is intentional.",
        ]
        fail("\n".join(lines))

    info("      ok — all new revisions descend from the base tip.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
