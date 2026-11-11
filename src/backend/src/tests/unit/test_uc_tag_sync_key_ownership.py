"""uc_tag_sync owns the keys its enabled configs produce, whatever their spelling.

The job used to derive one common prefix from every enabled tag key. Keys that
don't share a prefix (``ontos_domain`` with ``agent_readable``) fell back to the
``x_ontos_`` default, so the job stopped seeing the tags it had written before:
stale tags stayed on linked and unlinked objects. A single key could also yield a
prefix that matches user tags (``ontos_domain`` matches ``ontos_domain_team``).

These tests run the real ``main()``. Only the UC, Spark and Lakebase boundaries are
replaced by an in-memory tag store, so no workspace is touched.
"""

import copy
import importlib.util
import json
import sys
import types
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

_MODULE_PATH = (
    Path(__file__).resolve().parents[2] / "workflows" / "uc_tag_sync"
    / "uc_tag_sync.py"
)

DOMAIN_KEY = "ontos_domain"
STATUS_KEY = "agent_readable"
ORDERS = "main.finance.orders"
OTHER = "main.sales.other"
DOMAIN_CFG = {
    "entity_type": "data_domain", "enabled": True,
    "tag_key_format": DOMAIN_KEY, "tag_value_format": "{DOMAIN.NAME}",
}
STATUS_CFG = {
    "entity_type": "data_contract", "enabled": True,
    "tag_key_format": STATUS_KEY, "tag_value_format": "{CONTRACT.STATUS}",
}


@pytest.fixture(scope="module")
def tag_sync():
    """Load the job script by path; pyspark is only on the job cluster."""
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
    spec = importlib.util.spec_from_file_location("uc_tag_sync_key_ownership_under_test",
                                                   _MODULE_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    yield module
    for name in added:
        sys.modules.pop(name, None)


@pytest.fixture
def job(tag_sync, monkeypatch):
    """Run ``main()`` against an in-memory UC tag store and delivery state."""
    env = SimpleNamespace(store={}, state={}, assigned=[], unassigned=[])

    def existing(_spark, object_type, name, prefix):
        tags = env.store.get((object_type, name), {})
        return {k: v for k, v in tags.items() if k.startswith(prefix)}

    def assign(_spark, object_type, name, key, value):
        env.assigned.append((object_type, name, key))
        env.store.setdefault((object_type, name), {})[key] = value

    def unassign(_spark, object_type, name, key):
        env.unassigned.append((object_type, name, key))
        env.store.get((object_type, name), {}).pop(key, None)

    def save(_engine, state, _prefix, replace=True):
        env.state = json.loads(json.dumps(state))
        return None

    monkeypatch.setattr(tag_sync, "get_existing_prefixed_tags", existing)
    monkeypatch.setattr(tag_sync, "assign_tag", assign)
    monkeypatch.setattr(tag_sync, "unassign_tag", unassign)
    monkeypatch.setattr(tag_sync, "ensure_tag_key", lambda _ws, _key: None)
    monkeypatch.setattr(tag_sync, "read_delivery_state",
                        lambda _engine: copy.deepcopy(env.state))
    monkeypatch.setattr(tag_sync, "save_delivery_state", save)
    monkeypatch.setattr(tag_sync, "handle_legacy_tag_cleanup",
                        lambda *_a, **_k: (0, []))
    for name in ("WorkspaceClient", "create_engine_from_params", "SparkSession"):
        monkeypatch.setattr(tag_sync, name, MagicMock())
    for name in ("read_contracts_and_links", "read_output_ports_without_contract",
                 "read_assets_and_links", "read_direct_uc_links"):
        monkeypatch.setattr(tag_sync, name, lambda *_a, **_k: [])

    def run(configs, datasets=()):
        monkeypatch.setattr(tag_sync, "build_dataset_tag_infos",
                            lambda _rows, _cat, _schema: list(datasets))
        monkeypatch.setattr(sys, "argv", [
            "uc_tag_sync.py",
            "--tag_sync_configs", json.dumps(configs),
            "--lakebase_instance_name", "instance",
            "--postgres_host", "host",
            "--postgres_db", "db",
        ])
        tag_sync.main()

    env.run = run
    return env


def _table(tag_sync, fqn=ORDERS, domain=None, status=None, additional=()):
    cat, sch, tbl = fqn.split(".")
    return tag_sync.DatasetTagInfo(
        fqn=fqn, catalog=cat, schema=sch, table=tbl,
        contract_id="c-1" if status else None,
        contract_name="orders" if status else None,
        contract_version=None, contract_status=status,
        product_id=None, product_name=None, product_version=None,
        product_status=None,
        domain_id="d-1" if domain else None, domain_name=domain,
        semantic_links=[], additional_domain_names=list(additional),
    )


def _seed(env, object_name, tags, object_type="TABLE"):
    env.store[(object_type, object_name)] = dict(tags)


def _previous(object_name, tags, object_type="TABLE"):
    return {object_type: {object_name: dict(tags)}}


def test_a_previously_written_domain_tag_is_updated(tag_sync, job):
    """Tags written by the old logic are still updated when the value changes."""
    _seed(job, ORDERS, {DOMAIN_KEY: "Old", STATUS_KEY: "active"})
    job.state = _previous(ORDERS, {DOMAIN_KEY: "Old", STATUS_KEY: "active"})

    job.run([DOMAIN_CFG, STATUS_CFG],
            [_table(tag_sync, domain="Finance", status="active")])

    assert job.store[("TABLE", ORDERS)] == {DOMAIN_KEY: "Finance", STATUS_KEY: "active"}


def test_a_domain_no_longer_set_removes_its_tag_from_a_linked_table(tag_sync, job):
    """Linked table, domain gone: the stale ontos_domain is removed, status kept."""
    _seed(job, ORDERS, {DOMAIN_KEY: "Finance", STATUS_KEY: "active"})
    job.state = _previous(ORDERS, {DOMAIN_KEY: "Finance", STATUS_KEY: "active"})

    job.run([DOMAIN_CFG, STATUS_CFG], [_table(tag_sync, status="active")])

    assert job.store[("TABLE", ORDERS)] == {STATUS_KEY: "active"}


def test_an_unlinked_table_loses_both_managed_tags(tag_sync, job):
    """Table with no link left: every tag the job delivered there is removed."""
    _seed(job, ORDERS, {DOMAIN_KEY: "Finance", STATUS_KEY: "active"})
    job.state = _previous(ORDERS, {DOMAIN_KEY: "Finance", STATUS_KEY: "active"})

    job.run([DOMAIN_CFG, STATUS_CFG], [])

    assert job.store[("TABLE", ORDERS)] == {}
    assert job.state["TABLE"] == {}


def test_tags_the_job_did_not_create_are_never_removed(tag_sync, job):
    """User tags on a linked table and on an unconfigured table stay untouched."""
    _seed(job, OTHER, {STATUS_KEY: "mine"})
    _seed(job, ORDERS, {"ontos_domain_team": "x", "owner": "finance"})

    job.run([DOMAIN_CFG, STATUS_CFG],
            [_table(tag_sync, domain="Finance", status="active")])

    assert job.store[("TABLE", OTHER)] == {STATUS_KEY: "mine"}
    assert job.store[("TABLE", ORDERS)] == {
        "ontos_domain_team": "x", "owner": "finance",
        DOMAIN_KEY: "Finance", STATUS_KEY: "active",
    }


def test_a_disabled_config_removes_the_tag_it_delivered(tag_sync, job):
    """Disabling a config removes its delivered tag from the still-linked table."""
    _seed(job, ORDERS, {DOMAIN_KEY: "Finance", STATUS_KEY: "active"})
    job.state = _previous(ORDERS, {DOMAIN_KEY: "Finance", STATUS_KEY: "active"})

    job.run([DOMAIN_CFG], [_table(tag_sync, domain="Finance", status="active")])

    assert job.store[("TABLE", ORDERS)] == {DOMAIN_KEY: "Finance"}


def test_a_key_similar_to_an_enabled_key_is_not_removed(tag_sync, job):
    """ontos_domain_team is not ontos_domain: a lone enabled key must not match it."""
    _seed(job, ORDERS, {DOMAIN_KEY: "Finance", "ontos_domain_team": "x"})
    job.state = _previous(ORDERS, {DOMAIN_KEY: "Finance"})

    job.run([DOMAIN_CFG], [_table(tag_sync, domain="Finance")])

    assert job.store[("TABLE", ORDERS)] == {DOMAIN_KEY: "Finance", "ontos_domain_team": "x"}


def test_a_sanitized_key_is_removed_from_an_unlinked_table(tag_sync, job):
    """Key 'ontos-domain' is stored as ontos_domain; the stored tag is still removed."""
    _seed(job, ORDERS, {DOMAIN_KEY: "Finance"})
    job.state = _previous(ORDERS, {DOMAIN_KEY: "Finance"})
    cfg = dict(DOMAIN_CFG, tag_key_format="ontos-domain")

    job.run([cfg], [])

    assert job.store[("TABLE", ORDERS)] == {}


def test_additional_domain_tags_are_removed_with_the_primary(tag_sync, job):
    """Numbered data_domain keys (ontos_domain_1) are managed with the primary key."""
    _seed(job, ORDERS, {DOMAIN_KEY: "Finance", "ontos_domain_1": "Sales"})
    job.state = _previous(ORDERS, {DOMAIN_KEY: "Finance", "ontos_domain_1": "Sales"})

    job.run([DOMAIN_CFG], [])

    assert job.store[("TABLE", ORDERS)] == {}


def test_unchanged_tags_are_not_rewritten_on_the_next_run(tag_sync, job):
    """A second run with nothing changed issues no SET TAGS / UNSET TAGS statements."""
    datasets = [_table(tag_sync, domain="Finance", status="active")]
    job.run([DOMAIN_CFG, STATUS_CFG], datasets)
    assert job.assigned, "the first run should write the tags"
    job.assigned.clear()

    job.run([DOMAIN_CFG, STATUS_CFG], datasets)

    assert job.assigned == []
    assert job.unassigned == []
