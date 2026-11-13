"""uc_tag_sync manages the tags it delivered, whatever the spelling of their keys.

The job used to derive one common prefix from every enabled tag key. Keys that
don't share a prefix (``ontos_domain`` with ``agent_readable``) fell back to the
``x_ontos_`` default, so the job stopped seeing the tags it had written before:
stale tags stayed on linked and unlinked objects. A single key could also yield a
prefix that matches user tags (``ontos_domain`` matches ``ontos_domain_team``).
A tag is removed only when the delivery state recorded it on that object with its
current value: a configured key alone may be the customer's tag.

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
            # Like the real save: merged key by key, every stored key stays.
            for object_type, objects in copied.items():
                stored = env.state.setdefault(object_type, {})
                for fqn, tags in objects.items():
                    stored[fqn] = {**stored.get(fqn, {}), **tags}
        return None

    env.real_read = tag_sync.read_delivery_state
    env.real_save = tag_sync.save_delivery_state
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


def test_an_unrecorded_numbered_domain_tag_is_kept(tag_sync, job):
    """ontos_domain_2 has the job's numbered key, but the state never recorded it there:
    the customer may have set it, so it stays (as does agent_readable_2)."""
    _seed(job, ORDERS, {"ontos_domain_2": "Sales", "agent_readable_2": "mine"})
    job.state = {}

    job.run([DOMAIN_CFG, STATUS_CFG],
            [_table(tag_sync, domain="Finance")])

    assert job.store[("TABLE", ORDERS)] == {
        "ontos_domain_2": "Sales", "agent_readable_2": "mine", DOMAIN_KEY: "Finance",
    }


def test_a_recorded_numbered_domain_tag_is_removed_from_a_linked_table(tag_sync, job):
    """The additional domain went away: the recorded ontos_domain_1 is removed."""
    _seed(job, ORDERS, {DOMAIN_KEY: "Finance", "ontos_domain_1": "Sales"})
    job.state = _previous(ORDERS, {DOMAIN_KEY: "Finance", "ontos_domain_1": "Sales"})

    job.run([DOMAIN_CFG], [_table(tag_sync, domain="Finance")])

    assert job.store[("TABLE", ORDERS)] == {DOMAIN_KEY: "Finance"}


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


def test_a_recorded_sanitized_key_is_removed_from_a_linked_table(tag_sync, job):
    """Key 'ontos-domain' is stored as ontos_domain: the recorded tag, with no value
    desired any more, is removed from the still-linked table."""
    _seed(job, ORDERS, {DOMAIN_KEY: "Old", STATUS_KEY: "active"})
    job.state = _previous(ORDERS, {DOMAIN_KEY: "Old", STATUS_KEY: "active"})

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
    # The partial run removes nothing: the tag is still on the table.
    assert job.store[("TABLE", ORDERS)]["ontos_semantic_old"] == "stale"
    assert ("TABLE", ORDERS, "ontos_semantic_old") not in job.unassigned

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
    """save_delivery_state(replace=False) merges this run's objects into the stored state,
    key by key: a stored key of an object this run tagged stays."""
    import sqlalchemy

    stored = {"version": 1, "prefix": "p", "objects": {
        "TABLE": {OTHER: {"ontos_semantic_keep": "x"}, ORDERS: {"ontos_semantic_old": "s"}},
    }}
    engine = _sqlite_engine(sqlalchemy, json.dumps(stored))

    error = tag_sync.save_delivery_state(
        engine, {"TABLE": {ORDERS: {DOMAIN_KEY: "Finance"}}}, "p", replace=False)

    assert error is None
    assert _stored_objects(engine)["TABLE"] == {
        OTHER: {"ontos_semantic_keep": "x"},
        ORDERS: {"ontos_semantic_old": "s", DOMAIN_KEY: "Finance"},
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


def test_a_partial_run_removes_no_owned_table_tag(tag_sync, job):
    """--limit: a linked table whose domain row wasn't read keeps its owned domain tag."""
    _seed(job, ORDERS, {DOMAIN_KEY: "Finance", STATUS_KEY: "active"})
    job.state = _previous(ORDERS, {STATUS_KEY: "active"})

    job.run([DOMAIN_CFG, STATUS_CFG], [_table(tag_sync, status="active")],
            extra_args=("--limit", "5"))

    assert job.store[("TABLE", ORDERS)] == {DOMAIN_KEY: "Finance", STATUS_KEY: "active"}
    assert job.unassigned == []


def test_a_partial_run_does_not_clean_up_objects_it_did_not_read(tag_sync, job):
    """--limit: a recorded table that wasn't read is still linked; its tags stay."""
    _seed(job, ORDERS, {DOMAIN_KEY: "Finance"})
    _seed(job, OTHER, {DOMAIN_KEY: "Finance"})
    job.state = {"TABLE": {ORDERS: {DOMAIN_KEY: "Finance"},
                           OTHER: {DOMAIN_KEY: "Finance"}}}

    job.run([DOMAIN_CFG], [_table(tag_sync, domain="Finance")], extra_args=("--limit", "5"))

    assert job.store[("TABLE", OTHER)] == {DOMAIN_KEY: "Finance"}
    assert ("TABLE", OTHER, DOMAIN_KEY) not in job.unassigned
    assert job.state["TABLE"][OTHER] == {DOMAIN_KEY: "Finance"}


def test_a_corrupt_stored_state_reads_as_nothing_delivered_and_is_repaired(tag_sync):
    """A stored value that doesn't parse is read as {} so a full run overwrites it;
    a state that can't be read at all stays None."""
    import sqlalchemy

    corrupt = _sqlite_engine(sqlalchemy, "not json")
    assert tag_sync.read_delivery_state(corrupt) == {}
    assert tag_sync.save_delivery_state(
        corrupt, {"TABLE": {ORDERS: {DOMAIN_KEY: "Finance"}}}, "p") is None
    assert _stored_objects(corrupt)["TABLE"] == {ORDERS: {DOMAIN_KEY: "Finance"}}

    no_table = sqlalchemy.create_engine("sqlite://")
    assert tag_sync.read_delivery_state(no_table) is None


def test_a_corrupt_stored_state_is_replaced_but_does_not_open_the_legacy_cleanup(
    tag_sync, job, monkeypatch
):
    """A corrupt record is repaired by the main sync, but with no delivery history the
    legacy cleanup still sees an unavailable state and skips."""
    import sqlalchemy

    corrupt = _sqlite_engine(sqlalchemy, "not json")
    monkeypatch.setattr(tag_sync, "read_delivery_state", job.real_read)
    monkeypatch.setattr(tag_sync, "create_engine_from_params", lambda *_a, **_k: corrupt)
    legacy, saves = [], []
    monkeypatch.setattr(tag_sync, "handle_legacy_tag_cleanup",
                        lambda *_a, **kwargs: legacy.append(kwargs) or (0, []))
    monkeypatch.setattr(tag_sync, "save_delivery_state",
                        lambda _e, _state, _p, replace=True: saves.append(replace))

    job.run([DOMAIN_CFG], [_table(tag_sync, domain="Finance")],
            extra_args=["--cleanup_legacy_tags", "true"])

    assert saves == [True]
    assert legacy[0]["previous"] is None
    assert legacy[0]["cleanup_enabled"] is True


# Only recorded tags are removed -------------------------------------------------------

def test_a_customer_tag_with_a_configured_key_on_a_linked_table_is_kept(tag_sync, job):
    """The table gets agent_readable and no domain. The customer set ontos_domain by
    hand and the state never recorded it there: it stays."""
    _seed(job, ORDERS, {DOMAIN_KEY: "CustomerTeam"})
    job.state = {}

    job.run([DOMAIN_CFG, STATUS_CFG], [_table(tag_sync, status="active")])

    assert job.store[("TABLE", ORDERS)] == {DOMAIN_KEY: "CustomerTeam", STATUS_KEY: "active"}
    assert ("TABLE", ORDERS, DOMAIN_KEY) not in job.unassigned
    assert DOMAIN_KEY not in job.state["TABLE"][ORDERS]


@pytest.mark.parametrize("linked", [True, False])
def test_a_recorded_tag_whose_value_was_changed_outside_the_job_is_kept(
    tag_sync, job, linked
):
    """The state recorded ontos_domain=Finance, the customer changed it to Mine: it is
    the customer's now, kept, and no longer recorded."""
    _seed(job, ORDERS, {DOMAIN_KEY: "Mine", STATUS_KEY: "active"})
    job.state = _previous(ORDERS, {DOMAIN_KEY: "Finance", STATUS_KEY: "active"})

    job.run([DOMAIN_CFG, STATUS_CFG],
            [_table(tag_sync, status="active")] if linked else [])

    assert job.store[("TABLE", ORDERS)][DOMAIN_KEY] == "Mine"
    assert DOMAIN_KEY not in job.state["TABLE"].get(ORDERS, {})


def test_tag_keys_are_compared_case_sensitively(tag_sync, job):
    """UC tag keys are case-sensitive: a recorded ontos_domain is not Ontos_Domain."""
    _seed(job, ORDERS, {"Ontos_Domain": "Finance"})
    job.state = _previous(ORDERS, {DOMAIN_KEY: "Finance"})

    job.run([DOMAIN_CFG], [])

    assert job.store[("TABLE", ORDERS)] == {"Ontos_Domain": "Finance"}
    assert job.unassigned == []


def test_a_failed_assign_then_an_unlink_keeps_the_customer_value(
    tag_sync, job, monkeypatch
):
    """A tag policy rejects ontos_domain=Finance where the customer has Mine: the state
    must not say Finance was delivered, so the later unlink keeps Mine."""
    _seed(job, ORDERS, {DOMAIN_KEY: "Mine"})
    job.state = {}
    real_assign = tag_sync.assign_tag

    def rejected(spark, object_type, name, key, value):
        if key == DOMAIN_KEY:
            raise RuntimeError("[INVALID_PARAMETER_VALUE] value not allowed by tag policy")
        real_assign(spark, object_type, name, key, value)

    monkeypatch.setattr(tag_sync, "assign_tag", rejected)
    with pytest.raises(SystemExit):
        job.run([DOMAIN_CFG, STATUS_CFG],
                [_table(tag_sync, domain="Finance", status="active")])
    assert job.state["TABLE"][ORDERS] == {STATUS_KEY: "active"}

    job.run([DOMAIN_CFG, STATUS_CFG], [])

    assert job.store[("TABLE", ORDERS)] == {DOMAIN_KEY: "Mine"}


def test_a_failed_update_keeps_the_value_the_job_wrote_before(tag_sync, job, monkeypatch):
    """The update to Sales fails and the table still has the job's Finance: still
    recorded, so a later unlink removes it."""
    _seed(job, ORDERS, {DOMAIN_KEY: "Finance"})
    job.state = _previous(ORDERS, {DOMAIN_KEY: "Finance"})

    def failing(*_a):
        raise RuntimeError("transient")

    monkeypatch.setattr(tag_sync, "assign_tag", failing)
    with pytest.raises(SystemExit):
        job.run([DOMAIN_CFG], [_table(tag_sync, domain="Sales")])

    assert job.state["TABLE"][ORDERS] == {DOMAIN_KEY: "Finance"}


def test_an_error_on_one_object_keeps_the_run_going_and_its_records(
    tag_sync, job, monkeypatch
):
    """OTHER's information_schema can't be read: ORDERS is still tagged and recorded,
    OTHER keeps its record, and once both are unlinked no tag is left behind."""
    _seed(job, OTHER, {DOMAIN_KEY: "Sales"})
    job.state = _previous(OTHER, {DOMAIN_KEY: "Sales"})
    real_existing = tag_sync.get_existing_prefixed_tags

    def unreadable(spark, object_type, name, prefix):
        if name == OTHER:
            raise RuntimeError("information_schema unavailable")
        return real_existing(spark, object_type, name, prefix)

    monkeypatch.setattr(tag_sync, "get_existing_prefixed_tags", unreadable)
    with pytest.raises(SystemExit):
        job.run([DOMAIN_CFG], [_table(tag_sync, domain="Finance"),
                               _table(tag_sync, fqn=OTHER, domain="Finance")])

    assert job.store[("TABLE", ORDERS)] == {DOMAIN_KEY: "Finance"}
    assert job.state["TABLE"][ORDERS] == {DOMAIN_KEY: "Finance"}
    assert job.state["TABLE"][OTHER] == {DOMAIN_KEY: "Sales"}

    monkeypatch.setattr(tag_sync, "get_existing_prefixed_tags", real_existing)
    job.run([DOMAIN_CFG], [])

    assert job.store[("TABLE", ORDERS)] == {}
    assert job.store[("TABLE", OTHER)] == {}


def test_a_run_that_stops_part_way_saves_what_it_delivered(tag_sync, job, monkeypatch):
    """The run aborts after tagging ORDERS: the state holds ORDERS and keeps the record
    of the schema it never reached, so an unlink later leaves no orphan."""
    _seed(job, SCHEMA, {DOMAIN_KEY: "Sales"}, object_type="SCHEMA")
    job.state = _previous(SCHEMA, {DOMAIN_KEY: "Sales"}, object_type="SCHEMA")

    real_aggregate = tag_sync.aggregate_parent_desired

    def abort(*_a, **_k):
        raise RuntimeError("aborted")

    monkeypatch.setattr(tag_sync, "aggregate_parent_desired", abort)
    with pytest.raises(RuntimeError):
        job.run([DOMAIN_CFG], [_table(tag_sync, domain="Finance")])

    assert job.store[("TABLE", ORDERS)] == {DOMAIN_KEY: "Finance"}
    assert job.state["TABLE"][ORDERS] == {DOMAIN_KEY: "Finance"}
    assert job.state["SCHEMA"][SCHEMA] == {DOMAIN_KEY: "Sales"}

    monkeypatch.setattr(tag_sync, "aggregate_parent_desired", real_aggregate)
    job.run([DOMAIN_CFG], [])

    assert job.store[("TABLE", ORDERS)] == {}
    assert job.store[("SCHEMA", SCHEMA)] == {}


def test_a_dry_run_splits_recorded_from_customer_owned_tags(tag_sync, job, capsys):
    """Dry run: the recorded tag will be removed, the customer's configured key is kept."""
    _seed(job, ORDERS, {"ontos_semantic_old": "stale", DOMAIN_KEY: "CustomerTeam",
                        "owner": "finance"})
    job.state = _previous(ORDERS, {"ontos_semantic_old": "stale"})

    job.run([DOMAIN_CFG, STATUS_CFG, SEMANTIC_CFG], [_table(tag_sync, status="active")],
            extra_args=("--dry_run", "true"))

    out = capsys.readouterr().out
    assert "remove (recorded, will remove)=['ontos_semantic_old']" in out
    assert f"kept (customer-owned)=['{DOMAIN_KEY}']" in out
    assert job.unassigned == [] and job.assigned == []


def test_two_configs_producing_the_same_key_are_reported(tag_sync, job, capsys):
    job.run([DOMAIN_CFG, dict(STATUS_CFG, tag_key_format=DOMAIN_KEY)])

    out = capsys.readouterr().out
    assert f"[WARN] Tag key {DOMAIN_KEY} is produced by several configs" in out


def test_an_unreadable_state_keeps_matching_tags_recorded(tag_sync, job, monkeypatch):
    """The state can't be read: nothing is removed, a tag that already has the desired
    value stays recorded (merged into the stored state), and the stored records stay,
    also the ones of the tagged table (ontos_semantic_old, removed by a later run)."""
    _seed(job, ORDERS, {DOMAIN_KEY: "Finance", "ontos_semantic_old": "stale"})
    job.state = {"TABLE": {OTHER: {DOMAIN_KEY: "Sales"},
                           ORDERS: {"ontos_semantic_old": "stale"}}}
    monkeypatch.setattr(tag_sync, "read_delivery_state", lambda _engine: None)

    job.run([DOMAIN_CFG, SEMANTIC_CFG], [_table(tag_sync, domain="Finance")])

    # The schema and catalog get the aggregated tag; the table is already right.
    assert [a for a in job.assigned if a[0] == "TABLE"] == [] and job.unassigned == []
    assert job.state["TABLE"] == {
        ORDERS: {DOMAIN_KEY: "Finance", "ontos_semantic_old": "stale"},
        OTHER: {DOMAIN_KEY: "Sales"},
    }


# A stored state that doesn't parse -------------------------------------------------

CORRUPT_WITH_RECORDS = '{"version": 1, "objects": {"TABLE": {"main.sales.other": {"ontos_'


def _app_settings(engine):
    from sqlalchemy import text

    with engine.connect() as conn:
        return dict(conn.execute(text("SELECT key, value FROM app_settings")).all())


def test_a_corrupt_state_with_records_is_backed_up_before_it_is_replaced(
    tag_sync, job, monkeypatch, capsys
):
    import sqlalchemy

    engine = _sqlite_engine(sqlalchemy, CORRUPT_WITH_RECORDS)
    monkeypatch.setattr(tag_sync, "create_engine_from_params", lambda *_a, **_k: engine)
    monkeypatch.setattr(tag_sync, "read_delivery_state", job.real_read)
    monkeypatch.setattr(tag_sync, "save_delivery_state", job.real_save)

    job.run([DOMAIN_CFG], [_table(tag_sync, domain="Finance")])

    settings = _app_settings(engine)
    backups = {k: v for k, v in settings.items()
               if k.startswith("uc_tag_sync_delivery_state.corrupt-")}
    assert list(backups.values()) == [CORRUPT_WITH_RECORDS]
    assert _stored_objects(engine)["TABLE"] == {ORDERS: {DOMAIN_KEY: "Finance"}}
    out = capsys.readouterr().out
    assert "orphaned" in out
    assert "copied to app_settings key uc_tag_sync_delivery_state.corrupt-" in out


def test_a_corrupt_state_is_not_replaced_when_the_backup_fails(tag_sync, job, monkeypatch):
    import sqlalchemy

    engine = _sqlite_engine(sqlalchemy, CORRUPT_WITH_RECORDS)
    monkeypatch.setattr(tag_sync, "create_engine_from_params", lambda *_a, **_k: engine)
    monkeypatch.setattr(tag_sync, "read_delivery_state", job.real_read)
    monkeypatch.setattr(tag_sync, "save_delivery_state", job.real_save)
    monkeypatch.setattr(tag_sync, "backup_delivery_state", lambda *_a: "backup failed")

    with pytest.raises(SystemExit):
        job.run([DOMAIN_CFG], [_table(tag_sync, domain="Finance")])

    assert _app_settings(engine) == {"uc_tag_sync_delivery_state": CORRUPT_WITH_RECORDS}


def test_a_corrupt_state_keeps_tags_that_already_match_recorded(tag_sync, job, monkeypatch):
    """With a corrupt state, a tag already right on a linked table is recorded in the
    repaired state, so a later unlink still removes it."""
    import sqlalchemy

    engine = _sqlite_engine(sqlalchemy, CORRUPT_WITH_RECORDS)
    monkeypatch.setattr(tag_sync, "create_engine_from_params", lambda *_a, **_k: engine)
    monkeypatch.setattr(tag_sync, "read_delivery_state", job.real_read)
    monkeypatch.setattr(tag_sync, "save_delivery_state", job.real_save)
    _seed(job, ORDERS, {DOMAIN_KEY: "Finance"})

    job.run([DOMAIN_CFG], [_table(tag_sync, domain="Finance")])

    assert [a for a in job.assigned if a[0] == "TABLE"] == []
    assert _stored_objects(engine)["TABLE"] == {ORDERS: {DOMAIN_KEY: "Finance"}}

    job.run([DOMAIN_CFG], [])

    assert job.store[("TABLE", ORDERS)] == {}
