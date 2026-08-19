"""Outbound governed-tag domain emission in the uc_tag_sync job (nebw #3).

The job ships to a Databricks cluster and imports pyspark / databricks.sdk,
which aren't installed in the test env. We stub those modules so the pure
tag-building functions can be imported and exercised.
"""
import importlib.util
import sys
import types
from pathlib import Path

import pytest


@pytest.fixture(scope="module")
def tag_sync():
    # Stub heavy cluster-only deps before importing the standalone job file.
    stubs = {}
    for name in ("pyspark", "pyspark.sql"):
        if name not in sys.modules:
            mod = types.ModuleType(name)
            sys.modules[name] = mod
            stubs[name] = mod
    if not hasattr(sys.modules["pyspark.sql"], "SparkSession"):
        sys.modules["pyspark.sql"].SparkSession = object
    if "databricks" not in sys.modules:
        sys.modules["databricks"] = types.ModuleType("databricks")
    if "databricks.sdk" not in sys.modules:
        sdk = types.ModuleType("databricks.sdk")
        sdk.WorkspaceClient = object
        sys.modules["databricks.sdk"] = sdk
    if "databricks.sdk.errors" not in sys.modules:
        errs = types.ModuleType("databricks.sdk.errors")
        errs.NotFound = type("NotFound", (Exception,), {})
        sys.modules["databricks.sdk.errors"] = errs

    path = (
        Path(__file__).resolve().parents[2]
        / "workflows" / "uc_tag_sync" / "uc_tag_sync.py"
    )
    spec = importlib.util.spec_from_file_location("uc_tag_sync_under_test", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _dataset(mod, domain_name=None, domain_parent_name=None):
    return mod.DatasetTagInfo(
        fqn="c.s.t", catalog="c", schema="s", table="t",
        contract_id=None, contract_name=None, contract_version=None, contract_status=None,
        product_id=None, product_name=None, product_version=None, product_status=None,
        domain_id=None, domain_name=domain_name, semantic_links=[],
        domain_parent_name=domain_parent_name,
    )


def test_domain_tag_value_helper(tag_sync):
    assert tag_sync.domain_tag_value("Finance") == "Finance"
    assert tag_sync.domain_tag_value("Payments", "Finance") == "Finance/Payments"
    assert tag_sync.domain_tag_value("") is None


def test_governed_domain_tag_emitted_for_top_level(tag_sync):
    d = _dataset(tag_sync, domain_name="Finance")
    cfg = [{"entity_type": "data_domain", "enabled": True, "use_governed_domain_tag": True}]
    desired = tag_sync.build_desired_for_dataset(d, cfg)
    assert desired == {tag_sync.DOMAIN_TAG_KEY: "Finance"}


def test_governed_domain_tag_emitted_for_subdomain(tag_sync):
    d = _dataset(tag_sync, domain_name="Payments", domain_parent_name="Finance")
    cfg = [{"entity_type": "data_domain", "enabled": True, "use_governed_domain_tag": True}]
    desired = tag_sync.build_desired_for_dataset(d, cfg)
    assert desired == {tag_sync.DOMAIN_TAG_KEY: "Finance/Payments"}


def test_plain_tag_when_flag_off(tag_sync):
    d = _dataset(tag_sync, domain_name="Finance")
    cfg = [{
        "entity_type": "data_domain", "enabled": True,
        "tag_key_format": "ontos_data_domain_name", "tag_value_format": "{DOMAIN.NAME}",
    }]
    desired = tag_sync.build_desired_for_dataset(d, cfg)
    # Governed key not used; the plain configurable key is.
    assert tag_sync.DOMAIN_TAG_KEY not in desired
    assert desired.get("ontos_data_domain_name") == "Finance"
