"""A uc_tag_sync configuration saved before the lifecycle mapping existed gets it (#998).

The YAML default marks the two ``ontos_lifecycle_status`` entries with
``mapping: lifecycle_status``. Reading a saved configuration adds the marked default
entries it has no entry for, so the dialog, manual runs and on-demand runs see them
without a manual edit, and nothing is written to the database on read.
"""

import importlib.util
import json
import sys
import types
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from src.controller.jobs_manager import JobsManager, add_missing_mapped_entries
from src.models.workflow_configurations import WorkflowParameterDefinition
from src.repositories.workflow_configurations_repository import workflow_configuration_repo

_JOB_DIR = Path(__file__).resolve().parents[2] / "workflows" / "uc_tag_sync"
WORKFLOW = "uc_tag_sync"
STATUS_KEY = "ontos_lifecycle_status"
LIFECYCLE = "lifecycle_status"

# The tag_sync_configs default before the lifecycle entries: what a deployment that
# saved its configuration has stored.
OLD_SAVED = [
    {"entity_type": "semantic_assignment", "enabled": True,
     "tag_key_format": "ontos_semantic_{LINK.SLUG}", "tag_value_format": "{LINK.IRI}"},
    {"entity_type": "data_domain", "enabled": True,
     "tag_key_format": "ontos_data_domain_name", "tag_value_format": "{DOMAIN.NAME}"},
    {"entity_type": "data_contract", "enabled": True,
     "tag_key_format": "ontos_contract_name", "tag_value_format": "{CONTRACT.NAME}"},
    {"entity_type": "data_product", "enabled": True,
     "tag_key_format": "ontos_product_name", "tag_value_format": "{PRODUCT.NAME}"},
    {"entity_type": "asset", "enabled": True,
     "tag_key_format": "ontos_asset_type", "tag_value_format": "{ASSET.TYPE}"},
]
CONTRACT_LIFECYCLE = {
    "entity_type": "data_contract", "mapping": LIFECYCLE, "enabled": False,
    "tag_key_format": STATUS_KEY, "tag_value_format": "{CONTRACT.STATUS}",
}
PRODUCT_LIFECYCLE = {
    "entity_type": "data_product", "mapping": LIFECYCLE, "enabled": True,
    "tag_key_format": STATUS_KEY, "tag_value_format": "{PRODUCT.STATUS}",
}


@pytest.fixture
def jobs_manager(db_session):
    return JobsManager(db=db_session, ws_client=MagicMock())


@pytest.fixture
def definitions(jobs_manager):
    return jobs_manager.get_workflow_parameter_definitions(WORKFLOW)


def _save(db_session, configuration):
    workflow_configuration_repo.upsert(db_session, workflow_id=WORKFLOW,
                                       configuration=configuration)
    db_session.flush()


def test_the_yaml_default_marks_the_lifecycle_entries(definitions):
    param = next(d for d in definitions if d.name == "tag_sync_configs")
    marked = [e for e in param.default if e.get("mapping")]

    assert marked == [CONTRACT_LIFECYCLE, PRODUCT_LIFECYCLE]


def test_an_old_saved_list_gets_the_lifecycle_entries_appended(definitions):
    configuration = {"tag_sync_configs": [dict(e) for e in OLD_SAVED], "prefix": "x_"}

    result = add_missing_mapped_entries(configuration, definitions)

    # The saved entries stay first and unchanged (the dialog's main card edits the
    # first unmarked entry per type); the product entry comes last, so it wins the
    # shared key when both are enabled.
    assert result["tag_sync_configs"] == OLD_SAVED + [CONTRACT_LIFECYCLE, PRODUCT_LIFECYCLE]
    assert result["prefix"] == "x_"
    assert configuration["tag_sync_configs"] == OLD_SAVED


def test_a_kept_but_disabled_lifecycle_entry_stays_disabled(definitions):
    disabled = {**PRODUCT_LIFECYCLE, "enabled": False, "tag_key_format": "lifecycle"}
    saved = OLD_SAVED + [disabled]

    result = add_missing_mapped_entries({"tag_sync_configs": saved}, definitions)

    # Only the missing contract entry is added; the product one is the admin's.
    assert result["tag_sync_configs"] == saved + [CONTRACT_LIFECYCLE]


def test_a_list_with_both_lifecycle_entries_is_unchanged(definitions):
    saved = OLD_SAVED + [CONTRACT_LIFECYCLE, PRODUCT_LIFECYCLE]

    result = add_missing_mapped_entries({"tag_sync_configs": saved}, definitions)

    assert result["tag_sync_configs"] == saved


def test_only_lists_of_tag_sync_configs_parameters_get_entries(definitions):
    assert add_missing_mapped_entries({"prefix": "x_"}, definitions) == {"prefix": "x_"}
    assert add_missing_mapped_entries({"tag_sync_configs": "[]"}, definitions) == {
        "tag_sync_configs": "[]"
    }
    other = WorkflowParameterDefinition(
        name="patterns", type="entity_patterns", default=[{"mapping": "x"}]
    )
    assert add_missing_mapped_entries({"patterns": []}, [other]) == {"patterns": []}


def test_reading_an_old_saved_configuration_adds_the_mapping(db_session, jobs_manager):
    _save(db_session, {"tag_sync_configs": OLD_SAVED})

    configuration = jobs_manager.get_workflow_configuration(WORKFLOW)

    assert configuration["tag_sync_configs"][-2:] == [CONTRACT_LIFECYCLE, PRODUCT_LIFECYCLE]
    # Read only: the stored row isn't rewritten.
    stored = workflow_configuration_repo.get_configuration_dict(db_session,
                                                                workflow_id=WORKFLOW)
    assert stored == {"tag_sync_configs": OLD_SAVED}


def test_no_saved_configuration_stays_none(jobs_manager):
    assert jobs_manager.get_workflow_configuration(WORKFLOW) is None


@pytest.fixture(scope="module")
def tag_sync():
    """Load the job script by path; pyspark is stubbed when missing."""
    added = []
    if "pyspark.sql" not in sys.modules:
        try:
            import pyspark.sql  # noqa: F401
        except ImportError:
            pyspark = types.ModuleType("pyspark")
            pyspark_sql = types.ModuleType("pyspark.sql")
            pyspark_sql.SparkSession = object
            pyspark.sql = pyspark_sql
            sys.modules["pyspark"] = pyspark
            sys.modules["pyspark.sql"] = pyspark_sql
            added = ["pyspark", "pyspark.sql"]
    spec = importlib.util.spec_from_file_location("uc_tag_sync_upgrade_under_test",
                                                  _JOB_DIR / "uc_tag_sync.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    yield module
    for name in added:
        sys.modules.pop(name, None)


def test_a_run_with_an_old_saved_configuration_writes_the_lifecycle_tag(
    db_session, jobs_manager, tag_sync
):
    _save(db_session, {"tag_sync_configs": OLD_SAVED})

    params = jobs_manager.get_merged_job_parameters(WORKFLOW)

    row = {
        "contract_id": "c-1", "contract_name": "orders contract",
        "contract_version": "1.0", "contract_status": "active",
        "product_name_from_contract": None, "object_id": "obj-1",
        "schema_name": "orders", "physical_name": "main.sales.orders",
        "schema_semantic_iri": None, "schema_semantic_label": None,
        "domain_id": None, "domain_name": None, "contract_additional_domains": None,
        "product_id": "p-1", "product_name": "orders", "product_version": "1.0",
        "product_status": "deprecated", "product_domain": None,
        "product_additional_domains": None,
    }
    datasets = tag_sync.merge_dataset_tag_infos(
        tag_sync.build_dataset_tag_infos([row], None, None), []
    )
    desired = tag_sync.build_desired_for_dataset(
        datasets[0], json.loads(params["tag_sync_configs"])
    )

    assert desired[STATUS_KEY] == "deprecated"
    assert desired["ontos_product_name"] == "orders"

