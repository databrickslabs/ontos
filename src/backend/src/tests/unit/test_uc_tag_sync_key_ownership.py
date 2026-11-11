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
        copied = json.loads(json.dumps(state))
        if replace:
            env.state = copied
        else:
            # Like the real save: the objects of this run replace theirs, the rest stay.
            for object_type, objects in copied.items():
                env.state.setdefault(object_type, {}).update(objects)
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

    def run(configs, datasets=(), extra_args=()):
        monkeypatch.setattr(tag_sync, "build_dataset_tag_infos",
                            lambda _rows, _cat, _schema: list(datasets))
        monkeypatch.setattr(sys, "argv", [
            "uc_tag_sync.py",
            "--tag_sync_configs", json.dumps(configs),
            "--lakebase_instance_name", "instance",
            "--postgres_host", "host",
            "--postgres_db", "db",
            *extra_args,
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


SEMANTIC_CFG = {
    "entity_type": "semantic_assignment", "enabled": True,
    "tag_key_format": "ontos_semantic_{LINK.SLUG}", "tag_value_format": "{LINK.IRI}",
}


def test_a_placeholder_key_owns_no_tag_by_pattern(tag_sync):
    """A placeholder key (even a short literal like 'x_') claims no tag by pattern."""
    owned = tag_sync.TagOwnership.from_configs([SEMANTIC_CFG])
    assert owned.prefixes == ()
    assert not owned.owns("ontos_semantic_pii")
    assert not owned.owns("owner")

    short = tag_sync.TagOwnership.from_configs(
        [dict(SEMANTIC_CFG, tag_key_format="x_{LINK.SLUG}")])
    assert not short.owns("x_owner")


def test_a_placeholder_key_does_not_widen_an_exact_key(tag_sync):
    owned = tag_sync.TagOwnership.from_configs([DOMAIN_CFG, SEMANTIC_CFG])
    assert owned.owns(DOMAIN_KEY)
    assert not owned.owns("ontos_semantic_pii")
    assert not owned.owns("owner")


def test_a_recorded_placeholder_tag_is_removed_and_an_unrecorded_one_kept(tag_sync, job):
    """Placeholder tags are removed only when the delivery state recorded them."""
    _seed(job, ORDERS, {"ontos_semantic_old": "stale", "ontos_semantic_new": "x",
                        "owner": "finance"})
    job.state = _previous(ORDERS, {"ontos_semantic_old": "stale"})

    job.run([DOMAIN_CFG, SEMANTIC_CFG],
            [_table(tag_sync, domain="Finance")])

    assert job.store[("TABLE", ORDERS)] == {
        "ontos_semantic_new": "x", "owner": "finance", DOMAIN_KEY: "Finance",
    }


def test_a_numbered_domain_key_is_owned_only_for_a_data_domain_base(tag_sync):
    owned = tag_sync.TagOwnership.from_configs([DOMAIN_CFG, STATUS_CFG])
    assert owned.owns("ontos_domain_1")
    assert owned.owns("ontos_domain_12")
    assert not owned.owns("agent_readable_2")
    assert not owned.owns("ontos_domain_x")


def test_an_unrecorded_numbered_domain_tag_is_removed_and_a_user_numbered_tag_kept(
    tag_sync, job
):
    """ontos_domain_2 is the job's numbered key; agent_readable_2 is not, so it stays."""
    _seed(job, ORDERS, {"ontos_domain_2": "Sales", "agent_readable_2": "mine"})
    job.state = {}

    job.run([DOMAIN_CFG, STATUS_CFG],
            [_table(tag_sync, domain="Finance")])

    assert job.store[("TABLE", ORDERS)] == {
        "agent_readable_2": "mine", DOMAIN_KEY: "Finance",
    }


def test_a_disabled_config_does_not_own_its_key(tag_sync):
    owned = tag_sync.TagOwnership.from_configs([dict(STATUS_CFG, enabled=False)])
    assert not owned.owns(STATUS_KEY)


def test_an_unrecorded_tag_of_a_disabled_config_is_kept(tag_sync, job):
    """A user's agent_readable stays when its config is disabled and nothing was recorded."""
    _seed(job, ORDERS, {STATUS_KEY: "mine"})
    job.state = {}

    job.run([DOMAIN_CFG, dict(STATUS_CFG, enabled=False)],
            [_table(tag_sync, domain="Finance")])

    assert job.store[("TABLE", ORDERS)] == {STATUS_KEY: "mine", DOMAIN_KEY: "Finance"}


def test_a_sanitized_key_owns_the_stored_key(tag_sync):
    owned = tag_sync.TagOwnership.from_configs([dict(DOMAIN_CFG, tag_key_format="ontos-domain")])
    assert owned.owns(DOMAIN_KEY)


def test_an_unrecorded_sanitized_key_is_removed_from_a_linked_table(tag_sync, job):
    """Key 'ontos-domain' is stored as ontos_domain: an unrecorded copy with no value
    desired any more is removed from the still-linked table."""
    _seed(job, ORDERS, {DOMAIN_KEY: "Old", STATUS_KEY: "active"})
    job.state = {}

    job.run([dict(DOMAIN_CFG, tag_key_format="ontos-domain"), STATUS_CFG],
            [_table(tag_sync, status="active")])

    assert job.store[("TABLE", ORDERS)] == {STATUS_KEY: "active"}


def test_a_failed_removal_of_a_placeholder_tag_is_retried_next_run(tag_sync, job, monkeypatch):
    """A failed UNSET of a placeholder-key tag stays in the state, so the next run removes it."""
    _seed(job, ORDERS, {"ontos_semantic_old": "stale", "owner": "finance"})
    job.state = _previous(ORDERS, {"ontos_semantic_old": "stale"})
    real_unassign = tag_sync.unassign_tag

    def failing(_spark, _object_type, _name, _key):
        raise RuntimeError("transient")

    monkeypatch.setattr(tag_sync, "unassign_tag", failing)
    with pytest.raises(SystemExit):
        job.run([DOMAIN_CFG, SEMANTIC_CFG], [_table(tag_sync, domain="Finance")])
    assert job.state["TABLE"][ORDERS] == {"ontos_semantic_old": "stale", DOMAIN_KEY: "Finance"}

    monkeypatch.setattr(tag_sync, "unassign_tag", real_unassign)
    job.run([DOMAIN_CFG, SEMANTIC_CFG], [_table(tag_sync, domain="Finance")])

    assert job.store[("TABLE", ORDERS)] == {"owner": "finance", DOMAIN_KEY: "Finance"}


def test_legacy_cleanup_is_gated_on_the_prefix_it_always_was(tag_sync, job, monkeypatch):
    """The legacy cleanup gate keeps the value the job computed before this fix."""
    seen = []

    def record(_spark, _engine, _datasets, _direct, prefix, **_kwargs):
        seen.append(prefix)
        return (0, [])

    monkeypatch.setattr(tag_sync, "handle_legacy_tag_cleanup", record)

    job.run([DOMAIN_CFG, STATUS_CFG])
    job.run([DOMAIN_CFG])
    job.run([SEMANTIC_CFG])

    # Mixed keys share no prefix (default x_ontos_); a lone key is its own prefix.
    assert seen == ["x_ontos_", "ontos_domain", "ontos_semantic_"]


COLUMN = f"{ORDERS}.amount"
SCHEMA = "main.finance"


def test_a_column_or_schema_keeps_a_user_tag_that_shares_an_exact_key(
    tag_sync, job, monkeypatch
):
    """ontos_domain and agent_readable are table keys here: a column (semantic links only)
    and a schema (aggregated from its tables) never get them from the job, so the user's
    copies stay. Only the placeholder key is the job's there."""
    link = tag_sync.SemanticLink(iri="http://x/pii", label="PII", slug="pii")
    direct = tag_sync.DirectLinkInfos(
        columns=[tag_sync.ColumnTagInfo(table_fqn=ORDERS, column="amount",
                                        semantic_links=[link])],
        schemas={SCHEMA: [link]},
    )
    monkeypatch.setattr(tag_sync, "build_direct_link_infos", lambda *_a, **_k: direct)
    _seed(job, COLUMN, {DOMAIN_KEY: "user", STATUS_KEY: "mine"}, object_type="COLUMN")
    _seed(job, SCHEMA, {DOMAIN_KEY: "user", STATUS_KEY: "mine"}, object_type="SCHEMA")

    job.run([DOMAIN_CFG, STATUS_CFG, SEMANTIC_CFG], [])

    assert job.store[("COLUMN", COLUMN)] == {
        DOMAIN_KEY: "user", STATUS_KEY: "mine", "ontos_semantic_pii": "http://x/pii",
    }
    assert job.store[("SCHEMA", SCHEMA)] == {
        DOMAIN_KEY: "user", STATUS_KEY: "mine", "ontos_semantic_pii": "http://x/pii",
    }


def test_a_partial_run_keeps_the_placeholder_records_it_cannot_clean_up(tag_sync, job):
    """--limit: nothing is removed on the partial read, and the placeholder tag the state
    recorded stays recorded, so the next full run removes it."""
    _seed(job, ORDERS, {"ontos_semantic_old": "stale", DOMAIN_KEY: "Finance"})
    job.state = _previous(ORDERS, {"ontos_semantic_old": "stale"})

    job.run([DOMAIN_CFG, SEMANTIC_CFG], [_table(tag_sync, domain="Finance")],
            extra_args=("--limit", "5"))

    assert job.state["TABLE"][ORDERS]["ontos_semantic_old"] == "stale"

    job.run([DOMAIN_CFG, SEMANTIC_CFG], [_table(tag_sync, domain="Finance")])

    assert job.store[("TABLE", ORDERS)] == {DOMAIN_KEY: "Finance"}


def _sqlite_engine(sqlalchemy, stored_value):
    from sqlalchemy.pool import StaticPool

    engine = sqlalchemy.create_engine(
        "sqlite://", poolclass=StaticPool, connect_args={"check_same_thread": False})
    with engine.begin() as conn:
        conn.execute(sqlalchemy.text(
            "CREATE TABLE app_settings (key TEXT PRIMARY KEY, value TEXT, "
            "updated_at TEXT)"))
        if stored_value is not None:
            conn.execute(sqlalchemy.text(
                "INSERT INTO app_settings (key, value) VALUES "
                "('uc_tag_sync_delivery_state', :v)"), {"v": stored_value})
    return engine


def _stored_objects(engine):
    from sqlalchemy import text

    with engine.connect() as conn:
        value = conn.execute(text(
            "SELECT value FROM app_settings WHERE key = 'uc_tag_sync_delivery_state'"
        )).scalar()
    return json.loads(value)["objects"]


def test_a_save_that_does_not_replace_keeps_the_stored_objects(tag_sync):
    """save_delivery_state(replace=False) merges this run's objects into the stored state."""
    import sqlalchemy

    stored = {"version": 1, "prefix": "p", "objects": {
        "TABLE": {OTHER: {"ontos_semantic_keep": "x"}, ORDERS: {"ontos_semantic_old": "s"}},
    }}
    engine = _sqlite_engine(sqlalchemy, json.dumps(stored))

    error = tag_sync.save_delivery_state(
        engine, {"TABLE": {ORDERS: {DOMAIN_KEY: "Finance"}}}, "p", replace=False)

    assert error is None
    assert _stored_objects(engine)["TABLE"] == {
        OTHER: {"ontos_semantic_keep": "x"}, ORDERS: {DOMAIN_KEY: "Finance"},
    }


def test_a_save_that_does_not_replace_leaves_an_unreadable_state_alone(tag_sync):
    """If the stored state can't be read, a partial save must not overwrite it."""
    import sqlalchemy

    engine = _sqlite_engine(sqlalchemy, "not json")

    error = tag_sync.save_delivery_state(
        engine, {"TABLE": {ORDERS: {DOMAIN_KEY: "Finance"}}}, "p", replace=False)

    assert error is not None
    with engine.connect() as conn:
        value = conn.execute(sqlalchemy.text(
            "SELECT value FROM app_settings WHERE key = 'uc_tag_sync_delivery_state'"
        )).scalar()
    assert value == "not json"
