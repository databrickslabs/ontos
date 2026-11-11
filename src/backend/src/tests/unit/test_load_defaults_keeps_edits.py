"""Load Defaults with ``update_existing`` keeps default workflows a user edited.

"Reload all" reset every default workflow to its YAML definition, including the
ones an admin had changed in the designer, without asking. Edits then looked
lost ("saved, but the old version is back"). Edited defaults are now kept unless
the caller asks for them to be reset too.
"""
import textwrap

import pytest

from src.controller.workflows_manager import WorkflowsManager
from src.models.process_workflows import ProcessWorkflowUpdate
from src.repositories.process_workflows_repository import process_workflow_repo

YAML = textwrap.dedent("""
    workflows:
      - name: Default Gate
        description: shipped description
        trigger:
          type: manual
        steps:
          - id: done
            type: pass
      - name: Other Default
        description: shipped other
        trigger:
          type: manual
        steps:
          - id: done
            type: pass
""")


@pytest.fixture
def yaml_path(tmp_path):
    p = tmp_path / "workflows.yaml"
    p.write_text(YAML)
    return str(p)


@pytest.fixture
def manager(db_session):
    return WorkflowsManager(db_session)


def _edit(db, name, description, user="admin@example.com"):
    wf = process_workflow_repo.get_by_name(db, name)
    process_workflow_repo.update(
        db, wf.id, ProcessWorkflowUpdate(description=description), updated_by=user,
    )


def _description(db, name):
    db.expire_all()
    return process_workflow_repo.get_by_name(db, name).description


def test_reload_keeps_a_default_a_user_edited(db_session, manager, yaml_path):
    manager.load_from_yaml(yaml_path)
    _edit(db_session, "Default Gate", "my edit")

    result = manager.load_from_yaml(yaml_path, update_existing=True)

    assert _description(db_session, "Default Gate") == "my edit"
    assert result["kept_edited"] == 1
    assert result["kept_edited_names"] == ["Default Gate"]
    # The default nobody edited is still reset.
    assert result["updated"] == 1


def test_reload_can_reset_edited_defaults_when_asked(db_session, manager, yaml_path):
    manager.load_from_yaml(yaml_path)
    _edit(db_session, "Default Gate", "my edit")

    result = manager.load_from_yaml(yaml_path, update_existing=True, include_edited=True)

    assert _description(db_session, "Default Gate") == "shipped description"
    assert result["updated"] == 2
    assert result["kept_edited"] == 0


def test_a_default_reset_by_the_loader_counts_as_unedited_again(db_session, manager, yaml_path):
    manager.load_from_yaml(yaml_path)
    _edit(db_session, "Default Gate", "my edit")
    manager.load_from_yaml(yaml_path, update_existing=True, include_edited=True)

    result = manager.load_from_yaml(yaml_path, update_existing=True)

    assert result["kept_edited"] == 0
    assert result["updated"] == 2


def test_without_update_existing_nothing_changes(db_session, manager, yaml_path):
    manager.load_from_yaml(yaml_path)
    _edit(db_session, "Default Gate", "my edit")

    result = manager.load_from_yaml(yaml_path)

    assert _description(db_session, "Default Gate") == "my edit"
    assert result["skipped"] == 2
    assert result["updated"] == 0
