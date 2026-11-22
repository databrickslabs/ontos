"""A scheduled workflow loaded from YAML keeps its schedule and timezone."""
from src.controller.workflows_manager import WorkflowsManager

YAML = """\
workflows:
  - name: "Nightly digest"
    trigger:
      type: "scheduled"
      schedule: "0 0 6 * * ?"
      timezone: "America/Sao_Paulo"
    scope:
      type: "all"
    is_active: false
    steps:
      - id: "done"
        name: "Done"
        type: "pass"
"""


def test_yaml_import_keeps_the_trigger_timezone(db_session, tmp_path):
    path = tmp_path / "workflows.yaml"
    path.write_text(YAML)
    manager = WorkflowsManager(db_session)

    result = manager.load_from_yaml(str(path))

    assert result['created'] == 1
    workflow = next(w for w in manager.list_workflows() if w.name == "Nightly digest")
    assert workflow.trigger.schedule == "0 0 6 * * ?"
    assert workflow.trigger.timezone == "America/Sao_Paulo"
