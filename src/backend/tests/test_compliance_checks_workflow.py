"""Smoke tests for the compliance-checks workflow entry script.

Regression coverage for issue #685: the entry script is submitted as a
Databricks ``spark_python_task`` that runs on *serverless* compute, where the
runtime executes the source via ``exec(compile(...))`` in a namespace with no
``__file__`` bound. The module-level ``sys.path`` bootstrap must therefore not
depend on ``__file__`` being present, or it raises ``NameError`` before
``main()`` ever runs.

These tests faithfully simulate the serverless case by executing the module's
source in a globals dict that has NO ``__file__`` key, and assert that no
``NameError`` (or any other exception) escapes module load. ``__name__`` is set
to something other than ``"__main__"`` so the ``main()`` entry point does not
run. A companion test proves the normal case (with ``__file__`` present) still
imports cleanly.

Third-party top-level imports (``sqlalchemy``, ``databricks.sdk``) are stubbed
when absent so the test isolates the ``__file__`` path bootstrap rather than the
availability of runtime dependencies.
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


def _read_source() -> str:
    return _MODULE_PATH.read_text(encoding="utf-8")


@pytest.fixture
def stub_third_party(monkeypatch):
    """Ensure the module's top-level third-party imports resolve.

    ``sqlalchemy`` and ``databricks.sdk`` are the only top-level third-party
    imports. If they are importable in the test env we leave them alone;
    otherwise we install lightweight stubs so the test exercises the
    ``__file__`` path bootstrap rather than dependency availability.
    """

    def ensure_module(name: str, attrs: dict) -> None:
        if name in sys.modules:
            return
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
    ensure_module(
        "sqlalchemy.orm",
        {"Session": object, "sessionmaker": object},
    )
    ensure_module("databricks.sdk", {"WorkspaceClient": object})


def test_module_loads_without_file_global(stub_third_party):
    """Serverless simulation: exec the source with NO ``__file__`` in globals.

    This is the exact failure mode from issue #685. Before the fix, evaluating
    ``Path(__file__)`` at module load raised ``NameError``. The globals dict
    below intentionally omits ``__file__`` and sets ``__name__`` to a non-main
    value so ``main()`` does not execute.
    """
    source = _read_source()
    code = compile(source, "<string>", "exec")
    module_globals = {"__name__": "not_main"}

    assert "__file__" not in module_globals

    try:
        exec(code, module_globals)  # noqa: S102 - deliberately executing module source
    except NameError as exc:  # pragma: no cover - only on regression
        pytest.fail(
            f"module load raised NameError with __file__ absent (issue #685): {exc}"
        )

    # The bootstrap must not have leaked a bound __file__ into the namespace.
    assert "__file__" not in module_globals
    # main() must not have run.
    assert "main" in module_globals


def test_module_loads_with_file_global(stub_third_party):
    """Normal case: with ``__file__`` present the module still imports cleanly."""
    source = _read_source()
    code = compile(source, str(_MODULE_PATH), "exec")
    module_globals = {
        "__name__": "not_main",
        "__file__": str(_MODULE_PATH),
    }

    exec(code, module_globals)  # noqa: S102 - deliberately executing module source

    assert "main" in module_globals
    # The __file__-derived source root should be on sys.path.
    expected_root = str(_MODULE_PATH.parent.parent.parent)
    assert expected_root in sys.path
