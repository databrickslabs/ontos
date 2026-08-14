"""Smoke tests for the compliance-checks workflow entry script.

Regression coverage for issue #685: the entry script is submitted as a
Databricks ``spark_python_task`` that runs on *serverless* compute, where the
runtime executes the source via ``exec(compile(...))`` in a namespace with no
``__file__`` bound. The module-level ``sys.path`` bootstrap must therefore not
depend on ``__file__`` being present, or it raises ``NameError`` before
``main()`` ever runs.

These tests faithfully simulate the serverless case by executing the module's
source in a globals dict that has NO ``__file__`` key. They assert two things:

  * no ``NameError`` escapes module load (the original crash), and
  * the bootstrap does NOT prepend a fabricated / unrelated directory to
    ``sys.path`` -- the serverless branch must insert *nothing*, because there is
    no reliable signal to derive the real source root and a wrong entry could
    mask similarly named packages.

A companion test proves the normal case (with ``__file__`` present) still puts
the correct source root -- ``Path(module).parent.parent.parent`` -- on
``sys.path``.

Third-party top-level imports (``sqlalchemy``, ``databricks.sdk``) are stubbed
when absent so the test isolates the ``__file__`` path bootstrap. Because the
correctness assertions inspect ``sys.path`` directly, stubbing cannot mask an
incorrect ``sys.path`` entry.
"""

import sys
import types
from pathlib import Path

import pytest


# Absolute path to the workflow entry script under test.
_MODULE_PATH = (
    Path(__file__).resolve().parent.parent
    / "src"
    / "workflows"
    / "compliance_checks"
    / "compliance_checks.py"
)

# The source root the __file__ branch is expected to add to sys.path.
_EXPECTED_SRC_ROOT = str(_MODULE_PATH.parent.parent.parent)


def _read_source() -> str:
    return _MODULE_PATH.read_text(encoding="utf-8")


@pytest.fixture(autouse=True)
def restore_sys_path():
    """Snapshot and restore ``sys.path`` around each test.

    The module bootstrap mutates the real interpreter ``sys.path`` via
    ``sys.path.insert``; restoring afterwards keeps tests independent.
    """
    original = list(sys.path)
    try:
        yield
    finally:
        sys.path[:] = original


@pytest.fixture
def stub_third_party(monkeypatch):
    """Ensure the module's top-level third-party imports resolve.

    ``sqlalchemy`` and ``databricks.sdk`` are the only top-level third-party
    imports. If they are importable in the test env we leave them alone;
    otherwise we install lightweight stubs so the test exercises the
    ``__file__`` path bootstrap rather than dependency availability.
    """

    def ensure_module(name: str, attrs: dict) -> None:
        try:  # already importable in this env -> use the real one
            __import__(name)
            return
        except Exception:
            pass
        # Create parent packages as needed (e.g. "databricks" for "databricks.sdk").
        parts = name.split(".")
        for i in range(1, len(parts)):
            parent = ".".join(parts[:i])
            if parent not in sys.modules:
                pkg = types.ModuleType(parent)
                pkg.__path__ = []  # mark as package
                monkeypatch.setitem(sys.modules, parent, pkg)
        module = types.ModuleType(name)
        for attr, value in attrs.items():
            setattr(module, attr, value)
        monkeypatch.setitem(sys.modules, name, module)

    ensure_module("sqlalchemy", {"text": object, "create_engine": object})
    ensure_module("sqlalchemy.engine", {"Engine": object})
    ensure_module("sqlalchemy.orm", {"Session": object, "sessionmaker": object})
    ensure_module("databricks.sdk", {"WorkspaceClient": object})


def test_serverless_load_without_file_inserts_no_fabricated_path(
    stub_third_party, monkeypatch, tmp_path
):
    """Serverless simulation: exec the source with NO ``__file__`` in globals.

    This is the exact failure mode from issue #685. We also simulate a plausible
    serverless working directory (a deployed-workflow-shaped temp folder) so that
    if the code fell back to a cwd-derived path it would be caught: we assert
    ``sys.path`` is unchanged, i.e. the bootstrap prepended nothing.
    """
    source = _read_source()
    code = compile(source, "<string>", "exec")

    # Simulate a deployed workflow folder as cwd. A cwd-based guess would insert
    # tmp_path.parent.parent -- we assert that (and everything else) is NOT added.
    workflow_dir = tmp_path / "workflows" / "compliance_checks"
    workflow_dir.mkdir(parents=True)
    monkeypatch.chdir(workflow_dir)
    cwd_grandparent = str(Path.cwd().parent.parent)

    module_globals = {"__name__": "not_main"}
    assert "__file__" not in module_globals

    sys_path_before = list(sys.path)
    try:
        exec(code, module_globals)  # noqa: S102 - deliberately executing module source
    except NameError as exc:  # pragma: no cover - only on regression
        pytest.fail(
            f"module load raised NameError with __file__ absent (issue #685): {exc}"
        )

    # main() must exist but must not have run (non-main __name__).
    assert "main" in module_globals

    # Correctness: nothing was prepended to sys.path in the serverless branch...
    assert sys.path == sys_path_before, (
        "serverless bootstrap must not mutate sys.path; "
        f"added: {[p for p in sys.path if p not in sys_path_before]}"
    )
    # ...and specifically not a cwd-derived, unrelated directory.
    assert cwd_grandparent not in sys.path
    # No bound __file__ leaked into the namespace.
    assert "__file__" not in module_globals


def test_normal_load_with_file_inserts_correct_src_root(stub_third_party):
    """Normal case: with ``__file__`` present the correct source root is added."""
    source = _read_source()
    code = compile(source, str(_MODULE_PATH), "exec")
    module_globals = {
        "__name__": "not_main",
        "__file__": str(_MODULE_PATH),
    }

    # Start from a sys.path that does not already contain the expected root, so
    # the assertion proves the bootstrap added it rather than it being present.
    sys.path[:] = [p for p in sys.path if p != _EXPECTED_SRC_ROOT]

    exec(code, module_globals)  # noqa: S102 - deliberately executing module source

    assert "main" in module_globals
    assert _EXPECTED_SRC_ROOT in sys.path
    # It should be prepended (inserted at position 0).
    assert sys.path[0] == _EXPECTED_SRC_ROOT
