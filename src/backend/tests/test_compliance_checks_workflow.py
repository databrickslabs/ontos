"""Serverless deployment tests for the compliance-checks workflow."""

import base64
import sys
import types
from pathlib import Path
from types import SimpleNamespace
from zipfile import ZipFile

import pytest
from databricks.sdk.service import workspace

from src.controller.jobs_manager import JobsManager
from src.utils.workspace_deployer import WorkspaceDeployer

_MODULE_PATH = (
    Path(__file__).resolve().parent.parent
    / "src"
    / "workflows"
    / "compliance_checks"
    / "compliance_checks.py"
)
_BACKEND_PACKAGE_DIR = _MODULE_PATH.parent.parent.parent
_EXPECTED_SRC_ROOT = str(_BACKEND_PACKAGE_DIR.parent)


def _read_source() -> str:
    return _MODULE_PATH.read_text(encoding="utf-8")


@pytest.fixture(autouse=True)
def restore_import_state():
    original_path = list(sys.path)
    original_src_modules = {
        name: module
        for name, module in sys.modules.items()
        if name == "src" or name.startswith("src.")
    }
    try:
        yield
    finally:
        sys.path[:] = original_path
        for name in list(sys.modules):
            if name == "src" or name.startswith("src."):
                sys.modules.pop(name, None)
        sys.modules.update(original_src_modules)


@pytest.fixture
def stub_third_party(monkeypatch):
    def ensure_module(name: str, attrs: dict) -> None:
        try:
            __import__(name)
            return
        except Exception:
            pass
        parts = name.split(".")
        for index in range(1, len(parts)):
            parent = ".".join(parts[:index])
            if parent not in sys.modules:
                package = types.ModuleType(parent)
                package.__path__ = []
                monkeypatch.setitem(sys.modules, parent, package)
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
    code = compile(_read_source(), "<string>", "exec")
    workflow_dir = tmp_path / "workflows" / "compliance_checks"
    workflow_dir.mkdir(parents=True)
    monkeypatch.chdir(workflow_dir)
    cwd_grandparent = str(Path.cwd().parent.parent)

    module_globals = {"__name__": "not_main"}
    sys_path_before = list(sys.path)
    exec(code, module_globals)  # noqa: S102 - intentionally simulates serverless execution

    added_paths = [path for path in sys.path if path not in sys_path_before]
    assert "main" in module_globals
    assert not added_paths
    assert cwd_grandparent not in sys.path
    assert "__file__" not in module_globals


def test_normal_load_with_file_inserts_backend_package_parent(stub_third_party):
    code = compile(_read_source(), str(_MODULE_PATH), "exec")
    module_globals = {"__name__": "not_main", "__file__": str(_MODULE_PATH)}
    sys.path[:] = [path for path in sys.path if path != _EXPECTED_SRC_ROOT]

    exec(code, module_globals)  # noqa: S102 - intentionally executes the entry source

    assert "main" in module_globals
    assert sys.path[0] == _EXPECTED_SRC_ROOT


def test_serverless_main_imports_backend_modules_from_deployed_archive(
    monkeypatch, tmp_path
):
    archive_path = tmp_path / "backend_src.zip"
    archive_path.write_bytes(
        WorkspaceDeployer._build_python_package_archive(_BACKEND_PACKAGE_DIR)
    )

    for name in list(sys.modules):
        if name == "src" or name.startswith("src."):
            sys.modules.pop(name, None)
    blocked_roots = {_EXPECTED_SRC_ROOT, str(_BACKEND_PACKAGE_DIR)}
    sys.path[:] = [path for path in sys.path if path not in blocked_roots]

    module_globals = {"__name__": "not_main"}
    exec(  # noqa: S102 - intentionally simulates serverless execution
        compile(_read_source(), "<string>", "exec"),
        module_globals,
    )

    class FakeSession:
        def get(self, model, policy_id):
            return None

        def close(self):
            pass

    fake_session = FakeSession()
    module_globals["WorkspaceClient"] = lambda **kwargs: object()
    module_globals["create_engine_from_params"] = lambda **kwargs: object()
    module_globals["sessionmaker"] = lambda **kwargs: lambda: fake_session
    module_globals["load_policies"] = lambda *args, **kwargs: [
        {
            "id": "policy-1",
            "name": "Hermetic policy",
            "category": "Governance",
            "severity": "low",
        }
    ]
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "compliance_checks.py",
            "--backend_source_path",
            str(archive_path),
            "--lakebase_instance_name",
            "instance",
            "--postgres_host",
            "host",
            "--postgres_db",
            "database",
        ],
    )

    module_globals["main"]()

    assert sys.path[0] == str(archive_path)
    assert _EXPECTED_SRC_ROOT not in sys.path
    assert str(_BACKEND_PACKAGE_DIR) not in sys.path
    assert str(archive_path) in str(sys.modules["src.controller.compliance_manager"].__file__)
    assert str(archive_path) in str(sys.modules["src.db_models.compliance"].__file__)


def test_workspace_deployer_uploads_backend_source_archive(tmp_path):
    workflow_dir = tmp_path / "compliance_checks"
    workflow_dir.mkdir()
    (workflow_dir / "compliance_checks.py").write_text("print('ok')\n", encoding="utf-8")
    package_dir = tmp_path / "package"
    package_dir.mkdir()
    (package_dir / "__init__.py").write_text("", encoding="utf-8")
    (package_dir / "module.py").write_text("VALUE = 1\n", encoding="utf-8")

    uploads = {}

    class FakeWorkspaceApi:
        def get_status(self, path):
            return object()

        def mkdirs(self, path):
            pass

        def import_(self, *, path, content, format, overwrite):
            uploads[path] = (base64.b64decode(content), format, overwrite)

    deployer = WorkspaceDeployer(
        SimpleNamespace(workspace=FakeWorkspaceApi()),
        "/Workspace/Shared/ontos-workflows",
    )
    target_path = deployer.deploy_workflow(
        "compliance_checks",
        workflow_dir,
        python_package_dir=package_dir,
    )

    archive_bytes, format_type, overwrite = uploads[f"{target_path}/backend_src.zip"]
    archive_path = tmp_path / "uploaded.zip"
    archive_path.write_bytes(archive_bytes)
    with ZipFile(archive_path) as archive:
        assert set(archive.namelist()) == {"src/__init__.py", "src/module.py"}
    assert format_type == workspace.ImportFormat.RAW
    assert overwrite is True


def test_workflow_definition_points_serverless_job_at_deployed_archive():
    settings = SimpleNamespace(
        WORKSPACE_DEPLOYMENT_PATH="/Workspace/Shared/ontos-workflows",
        WORKSPACE_APP_PATH=None,
    )
    manager = JobsManager(
        db=object(),
        ws_client=object(),
        settings=settings,
        workflows_root=_BACKEND_PACKAGE_DIR / "workflows",
    )

    definition = manager._get_workflow_definition(
        "compliance_checks",
        job_cluster_id=None,
    )

    assert definition["parameters"]["backend_source_path"] == (
        "/Workspace/Shared/ontos-workflows/compliance_checks/backend_src.zip"
    )
    task_parameters = definition["tasks"][0]["spark_python_task"]["parameters"]
    backend_path_index = task_parameters.index("--backend_source_path")
    assert task_parameters[backend_path_index + 1] == "{{job.parameters.backend_source_path}}"


@pytest.mark.parametrize(
    ("workspace_app_path", "expected_backend_source_path"),
    [
        (
            "/Workspace/Users/user@example.com/ontos/src/backend/src",
            "/Workspace/Users/user@example.com/ontos/src/backend",
        ),
        (None, str(_BACKEND_PACKAGE_DIR.parent)),
    ],
)
def test_workflow_definition_uses_backend_package_parent_without_deployer(
    workspace_app_path,
    expected_backend_source_path,
):
    settings = SimpleNamespace(
        WORKSPACE_DEPLOYMENT_PATH=None,
        WORKSPACE_APP_PATH=workspace_app_path,
    )
    manager = JobsManager(
        db=object(),
        ws_client=object(),
        settings=settings,
        workflows_root=_BACKEND_PACKAGE_DIR / "workflows",
    )

    definition = manager._get_workflow_definition(
        "compliance_checks",
        job_cluster_id=None,
    )

    assert definition["parameters"]["backend_source_path"] == expected_backend_source_path
    assert Path(expected_backend_source_path).name == "backend"
