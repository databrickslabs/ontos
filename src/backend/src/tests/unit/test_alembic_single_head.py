"""The migration history must have exactly one head.

The "Alembic Single-Head Check" job only runs on pull_request events and is not
a required check, so two PRs that each add a migration on the same parent can
pass on their own and still land together through the merge queue. With two
heads, ``ScriptDirectory.get_current_head()`` raises ``MultipleHeads`` and the
app can't start (``common/database.py``). This test runs in "Backend Tests",
which is required and also runs on the merge queue, so the queue refuses such
a batch.
"""

from pathlib import Path

from alembic.config import Config
from alembic.script import ScriptDirectory

BACKEND_ROOT = Path(__file__).resolve().parents[3]


def _script_directory(backend_root: Path = BACKEND_ROOT) -> ScriptDirectory:
    config = Config(str(backend_root / "alembic.ini"))
    config.set_main_option("script_location", str(backend_root / "alembic"))
    return ScriptDirectory.from_config(config)


def test_the_migration_history_has_a_single_head():
    heads = _script_directory().get_heads()
    assert len(heads) == 1, (
        f"Alembic has {len(heads)} heads: {', '.join(sorted(heads))}. "
        "Two migrations descend from the same parent. Rebase onto the current base "
        "branch and set the newer migration's down_revision to the live head "
        "(`hatch -e dev run alembic heads`), or, if the branch is deliberate, add "
        "`alembic merge -m 'merge heads' <head_a> <head_b>` and the `alembic-branch` "
        "label (see .cursor/rules/11-database-migrations.mdc)."
    )


# alembic_version.version_num is VARCHAR(32). A longer revision id passes on
# SQLite (which ignores the length) but fails on Postgres when the database is
# stamped or upgraded, and the app can't start.
ALEMBIC_VERSION_NUM_LENGTH = 32


def test_every_revision_id_fits_alembic_version():
    too_long = sorted(
        rev.revision
        for rev in _script_directory().walk_revisions()
        if len(rev.revision) > ALEMBIC_VERSION_NUM_LENGTH
    )
    assert too_long == [], (
        f"Revision ids longer than {ALEMBIC_VERSION_NUM_LENGTH} characters don't fit "
        f"alembic_version.version_num on Postgres: {', '.join(too_long)}. Shorten the "
        "`revision` (and the file name / docstring to match)."
    )
