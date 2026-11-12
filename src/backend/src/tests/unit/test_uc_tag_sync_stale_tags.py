"""uc_tag_sync removes tags it delivered once an object's last link is gone.

Covers #1145, #1155. UC is replaced by an in-memory tag store: the functions
that read and write UC tags through Spark are patched, so no workspace is
touched. Delivery state is stored in SQLite with an app_settings table replica.
"""

import importlib.util
import json
import sys
import types
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from sqlalchemy import Column, String, Text, create_engine, func, TIMESTAMP
from sqlalchemy.orm import declarative_base, Session

_MODULE_PATH = (
    Path(__file__).resolve().parents[2] / "workflows" / "uc_tag_sync"
    / "uc_tag_sync.py"
)

PREFIX = "ontos_"
SEMANTIC_CFG = [
    {
        "entity_type": "semantic_assignment",
        "enabled": True,
        "tag_key_format": "ontos_semantic_{LINK.SLUG}",
        "tag_value_format": "{LINK.IRI}",
    }
]
OPEX = "urn:glossary:finance/opex-spend"
PII = "urn:glossary:privacy/pii"
OPEX_KEY = "ontos_semantic_opex_spend"
PII_KEY = "ontos_semantic_pii"
COLUMN = "main.finance.t.amount"


# In-memory SQLAlchemy models for app_settings
Base = declarative_base()


class AppSettingDb(Base):
    __tablename__ = "app_settings"
    key = Column(String(255), primary_key=True)
    value = Column(Text, nullable=True)
    updated_at = Column(TIMESTAMP(timezone=True), server_default=func.now(),
                        onupdate=func.now(), nullable=True)


@pytest.fixture(scope="module")
def tag_sync():
    """Load the job script by path; it is not part of the src package.

    pyspark is only available on the job cluster, so a stub is registered when
    missing.
    """
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
    spec = importlib.util.spec_from_file_location("uc_tag_sync_stale_under_test",
                                                   _MODULE_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    yield module
    for name in added:
        sys.modules.pop(name, None)


@pytest.fixture
def db():
    """SQLite in-memory database with app_settings table."""
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    return engine


@pytest.fixture
def uc(tag_sync, monkeypatch):
    """In-memory UC tags: (object_type, fqn) -> {tag key: value}."""
    store = {}

    def existing(_spark, object_type, name, prefix):
        tags = store.get((object_type, name), {})
        return {k: v for k, v in tags.items() if k.startswith(prefix)}

    def assign(_spark, object_type, name, key, value):
        store.setdefault((object_type, name), {})[key] = value

    def unassign(_spark, object_type, name, key):
        store.get((object_type, name), {}).pop(key, None)

    monkeypatch.setattr(tag_sync, "get_existing_prefixed_tags", existing)
    monkeypatch.setattr(tag_sync, "assign_tag", assign)
    monkeypatch.setattr(tag_sync, "unassign_tag", unassign)
    monkeypatch.setattr(tag_sync, "ensure_tag_key", lambda _ws, _key: None)
    return store


def _row(entity_type, entity_id, iri=OPEX):
    return {"entity_type": entity_type, "entity_id": entity_id, "iri": iri,
            "label": None}


def _asset_dataset(tag_sync, fqn, iris):
    cat, sch, tbl = fqn.split(".")
    return tag_sync.DatasetTagInfo(
        fqn=fqn, catalog=cat, schema=sch, table=tbl,
        contract_id=None, contract_name=None, contract_version=None,
        contract_status=None,
        product_id=None, product_name=None, product_version=None,
        product_status=None, domain_id=None, domain_name=None,
        semantic_links=[
            tag_sync.SemanticLink(iri=i, label=None,
                                  slug=tag_sync.slugify_iri(i)) for i in iris
        ],
        asset_id="a-1", asset_type_name="Table",
    )


def _run(tag_sync, rows, previous, asset_datasets=(), dry_run=False):
    """One job run over the given direct-link rows (and asset datasets)."""
    direct = tag_sync.build_direct_link_infos(rows, None, None)
    datasets = tag_sync.merge_dataset_tag_infos([], list(asset_datasets),
                                                direct.tables)
    return tag_sync.sync_tags(
        MagicMock(), MagicMock(), datasets, direct, SEMANTIC_CFG, PREFIX,
        previous=previous, dry_run=dry_run,
    )


def _ontos_tags(store):
    return {obj: tags for obj, tags in store.items()
            if any(k.startswith(PREFIX) for k in tags)}


@pytest.mark.parametrize(
    "entity_type, entity_id, object_key",
    [
        ("uc_column", COLUMN, ("COLUMN", COLUMN)),
        ("uc_table", "main.finance.t", ("TABLE", "main.finance.t")),
        ("uc_schema", "main.finance", ("SCHEMA", "main.finance")),
        ("uc_catalog", "main", ("CATALOG", "main")),
    ],
)
def test_unlinking_the_final_link_removes_the_tag(
    tag_sync, uc, entity_type, entity_id, object_key
):
    """Link → sync → unlink final link → sync → tag removed."""
    first = _run(tag_sync, [_row(entity_type, entity_id)], previous={})
    assert uc[object_key] == {OPEX_KEY: OPEX}
    assert first.errors == []

    second = _run(tag_sync, [], previous=first.delivered)

    # A table link also tags its schema and catalog; all cleaned up.
    assert _ontos_tags(uc) == {}
    assert second.removed == first.updated
    assert second.errors == []
    assert all(objects == {} for objects in second.delivered.values())


def test_a_user_tag_with_the_same_key_on_another_object_is_untouched(tag_sync,
                                                                      uc):
    """User-set tags with same key elsewhere stay untouched."""
    uc[("COLUMN", "main.finance.t.other")] = {OPEX_KEY: "set by a user"}
    first = _run(tag_sync, [_row("uc_column", COLUMN)], previous={})
    # Tags added on the linked object after the sync
    uc[("COLUMN", COLUMN)].update({"ontos_note": "user", "owner": "finance"})

    _run(tag_sync, [], previous=first.delivered)

    assert uc[("COLUMN", "main.finance.t.other")] == {OPEX_KEY: "set by a user"}
    assert uc[("COLUMN", COLUMN)] == {"ontos_note": "user", "owner": "finance"}


def test_removing_one_of_two_concept_links_keeps_the_other_tag(tag_sync, uc):
    """Removing one of two links to same object keeps the other tag."""
    first = _run(tag_sync, [_row("uc_column", COLUMN, OPEX),
                            _row("uc_column", COLUMN, PII)], {})
    assert uc[("COLUMN", COLUMN)] == {OPEX_KEY: OPEX, PII_KEY: PII}

    second = _run(tag_sync, [_row("uc_column", COLUMN, OPEX)],
                  previous=first.delivered)

    assert uc[("COLUMN", COLUMN)] == {OPEX_KEY: OPEX}
    assert second.delivered["COLUMN"] == {COLUMN: {OPEX_KEY: OPEX}}


def test_removing_one_of_two_links_to_the_same_concept_keeps_the_tag(tag_sync,
                                                                      uc):
    """Removing one of two data sources linking to same concept keeps tag."""
    table = "main.finance.t"
    first = _run(
        tag_sync, [_row("uc_table", table)], {},
        asset_datasets=[_asset_dataset(tag_sync, table, [OPEX])],
    )
    assert uc[("TABLE", table)] == {OPEX_KEY: OPEX}

    second = _run(
        tag_sync, [], previous=first.delivered,
        asset_datasets=[_asset_dataset(tag_sync, table, [OPEX])],
    )

    assert uc[("TABLE", table)] == {OPEX_KEY: OPEX}
    assert second.removed == 0


def test_dry_run_reports_but_removes_nothing(tag_sync, uc, capsys):
    """Dry run reports what would be removed but doesn't remove it."""
    first = _run(tag_sync, [_row("uc_column", COLUMN)], previous={})

    _run(tag_sync, [], previous=first.delivered, dry_run=True)

    assert uc[("COLUMN", COLUMN)] == {OPEX_KEY: OPEX}
    out = capsys.readouterr().out
    assert f"[DRY-RUN] COLUMN {COLUMN} remove=['{OPEX_KEY}']" in out


def test_unknown_previous_state_skips_the_cleanup(tag_sync, uc):
    """Unknown previous state (None) skips cleanup."""
    _run(tag_sync, [_row("uc_column", COLUMN)], previous={})

    second = _run(tag_sync, [], previous=None)

    assert uc[("COLUMN", COLUMN)] == {OPEX_KEY: OPEX}
    assert second.removed == 0


def test_a_failed_removal_is_reported_and_retried_next_run(tag_sync, uc,
                                                           monkeypatch):
    """Failed removal is reported and retried next run."""
    first = _run(tag_sync, [_row("uc_column", COLUMN)], previous={})

    def failing_unassign(*_args):
        raise RuntimeError("PERMISSION_DENIED")

    monkeypatch.setattr(tag_sync, "unassign_tag", failing_unassign)
    second = _run(tag_sync, [], previous=first.delivered)

    assert len(second.errors) == 1
    assert "PERMISSION_DENIED" in second.errors[0]
    assert second.delivered["COLUMN"] == {COLUMN: {OPEX_KEY: OPEX}}


def test_an_unreadable_object_is_kept_for_the_next_run(tag_sync, uc,
                                                       monkeypatch):
    """Unreadable object is kept for next run."""
    first = _run(tag_sync, [_row("uc_column", COLUMN)], previous={})

    def unreadable(*_args):
        raise RuntimeError("CATALOG_NOT_FOUND")

    monkeypatch.setattr(tag_sync, "get_existing_prefixed_tags", unreadable)
    second = _run(tag_sync, [], previous=first.delivered)

    assert second.errors == []
    assert second.delivered["COLUMN"] == {COLUMN: {OPEX_KEY: OPEX}}


def test_read_delivery_state_from_app_settings(tag_sync, db):
    """read_delivery_state retrieves JSON blob from app_settings."""
    # Setup app_settings
    with Session(db) as session:
        state_data = {
            "version": 1,
            "prefix": PREFIX,
            "objects": {
                "COLUMN": {COLUMN: {OPEX_KEY: OPEX, PII_KEY: PII}},
                "SCHEMA": {"main.finance": {OPEX_KEY: None}},
            },
        }
        setting = AppSettingDb(key="uc_tag_sync_delivery_state",
                               value=json.dumps(state_data))
        session.add(setting)
        session.commit()

    state = tag_sync.read_delivery_state(db)

    assert state == {
        "COLUMN": {COLUMN: {OPEX_KEY: OPEX, PII_KEY: PII}},
        "SCHEMA": {"main.finance": {OPEX_KEY: None}},
    }


def test_read_delivery_state_returns_empty_dict_when_not_exists(tag_sync, db):
    """read_delivery_state returns {} when key doesn't exist."""
    state = tag_sync.read_delivery_state(db)
    assert state == {}


def test_read_delivery_state_returns_none_when_unreadable(tag_sync):
    """read_delivery_state returns None on database error."""
    engine = MagicMock()
    engine.connect.side_effect = RuntimeError("connection failed")

    assert tag_sync.read_delivery_state(engine) is None


def test_save_delivery_state_to_app_settings(tag_sync, db):
    """save_delivery_state stores JSON blob in app_settings."""
    state = {
        "COLUMN": {COLUMN: {OPEX_KEY: OPEX}},
        "TABLE": {},
    }

    error = tag_sync.save_delivery_state(db, state, PREFIX, replace=True)

    assert error is None
    with Session(db) as session:
        row = session.query(AppSettingDb).filter_by(
            key="uc_tag_sync_delivery_state"
        ).first()
        assert row is not None
        data = json.loads(row.value)
        assert data["version"] == 1
        assert data["prefix"] == PREFIX
        assert data["objects"] == state


def test_save_delivery_state_returns_the_error(tag_sync):
    """save_delivery_state returns error message on failure."""
    engine = MagicMock()
    engine.begin.side_effect = RuntimeError("connection reset")

    error = tag_sync.save_delivery_state(engine, {}, PREFIX, replace=True)

    assert error is not None and "connection reset" in error


def test_prefix_changed_between_runs_removes_recorded_keys(tag_sync, db, uc):
    """Prefix changed between runs: old delivered keys removed."""
    # First run with old prefix
    old_prefix = "old_prefix_"
    old_key = "old_prefix_tag"
    uc[("TABLE", "c.s.t")] = {old_key: "some_value"}

    # Save old state
    old_state = {"TABLE": {"c.s.t": {old_key: "some_value"}}}
    old_state_data = {
        "version": 1,
        "prefix": old_prefix,
        "objects": old_state,
    }
    with Session(db) as session:
        setting = AppSettingDb(key="uc_tag_sync_delivery_state",
                               value=json.dumps(old_state_data))
        session.add(setting)
        session.commit()

    # Read with new prefix
    state = tag_sync.read_delivery_state(db)
    assert state == old_state

    # Mock reconcile to track removal
    removals = []
    original_remove = tag_sync.remove_delivered_tags

    def track_remove(spark, obj_type, obj_name, delivered, prefix, dry_run=False):
        removals.append((obj_type, obj_name, delivered, prefix))
        return original_remove(spark, obj_type, obj_name, delivered, prefix,
                               dry_run=dry_run)

    # Patch and run with new prefix
    with patch.object(tag_sync, "remove_delivered_tags", track_remove):
        # New run with different prefix but same tag is recorded with old prefix
        first = _run(tag_sync, [], previous=old_state)

    # Should have attempted to remove the old key
    assert len(removals) == 1
    assert removals[0][0] == "TABLE"
    assert removals[0][1] == "c.s.t"
    assert old_key in removals[0][2]


def test_limit_skips_cleanup(tag_sync, uc):
    """--limit skips cleanup (partial read)."""
    first = _run(tag_sync, [_row("uc_column", COLUMN)], previous={})

    # Simulate a second run with --limit (pass None for previous to skip cleanup)
    second = _run(tag_sync, [], previous=None)

    # Tag should still exist because cleanup was skipped
    assert uc[("COLUMN", COLUMN)] == {OPEX_KEY: OPEX}
    assert second.removed == 0
    assert second.delivered["COLUMN"] == {}


# Legacy cleanup tests (handle_legacy_tag_cleanup with new spec)

def test_legacy_cleanup_custom_prefix_refuses(tag_sync, db):
    """Custom prefix: refuses cleanup."""
    dataset = _asset_dataset(tag_sync, "main.s.t", [OPEX])
    direct = tag_sync.DirectLinkInfos()

    removed, errors = tag_sync.handle_legacy_tag_cleanup(
        MagicMock(), db, [dataset], direct,
        prefix="custom_",
        previous={},
        cleanup_enabled=True,
        is_partial_read=False,
        dry_run=False,
    )

    assert removed == 0
    assert len(errors) == 1
    assert "default prefix" in errors[0].lower()


def test_legacy_cleanup_partial_run_skipped(tag_sync, db):
    """Partial run (--limit): skips cleanup."""
    dataset = _asset_dataset(tag_sync, "main.s.t", [OPEX])
    direct = tag_sync.DirectLinkInfos()

    removed, errors = tag_sync.handle_legacy_tag_cleanup(
        MagicMock(), db, [dataset], direct,
        prefix="x_ontos_",
        previous={},
        cleanup_enabled=True,
        is_partial_read=True,
        dry_run=False,
    )

    assert removed == 0
    assert errors == []


def test_legacy_cleanup_unreadable_state_skipped(tag_sync, db):
    """Unreadable previous state: skips cleanup."""
    dataset = _asset_dataset(tag_sync, "main.s.t", [OPEX])
    direct = tag_sync.DirectLinkInfos()

    removed, errors = tag_sync.handle_legacy_tag_cleanup(
        MagicMock(), db, [dataset], direct,
        prefix="x_ontos_",
        previous=None,
        cleanup_enabled=True,
        is_partial_read=False,
        dry_run=False,
    )

    assert removed == 0
    assert errors == []


def test_legacy_cleanup_already_done_skipped(tag_sync, db):
    """Already marked done: skips cleanup."""
    dataset = _asset_dataset(tag_sync, "main.s.t", [OPEX])
    direct = tag_sync.DirectLinkInfos()

    # Mark cleanup as already done
    with Session(db) as session:
        setting = AppSettingDb(
            key="uc_tag_sync_cleanup_legacy_status",
            value=json.dumps({"cleanup_done": True})
        )
        session.add(setting)
        session.commit()

    removed, errors = tag_sync.handle_legacy_tag_cleanup(
        MagicMock(), db, [dataset], direct,
        prefix="x_ontos_",
        previous={},
        cleanup_enabled=True,
        is_partial_read=False,
        dry_run=False,
    )

    assert removed == 0
    assert errors == []


def test_legacy_cleanup_linked_table_keeps_tag(tag_sync, uc, db, monkeypatch):
    """Linked table with desired tag: keeps it."""
    default_prefix = "x_ontos_"
    default_key = f"{default_prefix}legacy_tag"

    # Table in UC with legacy tag
    uc[("TABLE", "main.s.t")] = {default_key: OPEX}

    # Mock the bulk reader
    def fake_bulk_read(spark, catalog, prefix):
        result = {}
        for (obj_type, fqn), tags in uc.items():
            if fqn.lower().startswith(catalog.lower()):
                result[(obj_type, fqn)] = {k: v for k, v in tags.items()
                                           if k.startswith(prefix)}
        return result

    monkeypatch.setattr(tag_sync, "_bulk_read_prefixed_tags_per_catalog",
                        fake_bulk_read)

    # Dataset linking to the table
    dataset = _asset_dataset(tag_sync, "main.s.t", [OPEX])
    direct = tag_sync.DirectLinkInfos(
        tables=[dataset],
    )

    # No previous delivery state (legacy cleanup only)
    previous = {}

    removed, errors = tag_sync.handle_legacy_tag_cleanup(
        MagicMock(), db, [dataset], direct,
        prefix=default_prefix,
        previous=previous,
        cleanup_enabled=True,
        is_partial_read=False,
        dry_run=False,
    )

    # Tag should NOT be removed (table is in desired set)
    assert uc[("TABLE", "main.s.t")] == {default_key: OPEX}
    assert removed == 0
    assert errors == []


def test_legacy_cleanup_unlinked_table_loses_tag(tag_sync, uc, db, monkeypatch):
    """Unlinked table with legacy tag: loses it."""
    default_prefix = "x_ontos_"
    default_key = f"{default_prefix}legacy_tag"

    # Unlinked table in UC with legacy tag
    uc[("TABLE", "main.s.unlinked")] = {default_key: OPEX}

    def fake_bulk_read(spark, catalog, prefix):
        result = {}
        for (obj_type, fqn), tags in uc.items():
            if fqn.lower().startswith(catalog.lower()):
                result[(obj_type, fqn)] = {k: v for k, v in tags.items()
                                           if k.startswith(prefix)}
        return result

    def fake_unassign(spark, obj_type, fqn, key):
        uc.get((obj_type, fqn), {}).pop(key, None)

    monkeypatch.setattr(tag_sync, "_bulk_read_prefixed_tags_per_catalog",
                        fake_bulk_read)
    monkeypatch.setattr(tag_sync, "unassign_tag", fake_unassign)

    # No direct links (empty)
    dataset = _asset_dataset(tag_sync, "main.s.other", [OPEX])
    direct = tag_sync.DirectLinkInfos(tables=[dataset])

    # Previous is empty (no delivered tags)
    previous = {}

    removed, errors = tag_sync.handle_legacy_tag_cleanup(
        MagicMock(), db, [dataset], direct,
        prefix=default_prefix,
        previous=previous,
        cleanup_enabled=True,
        is_partial_read=False,
        dry_run=False,
    )

    # Unlinked table's tag should be removed
    assert uc.get(("TABLE", "main.s.unlinked"), {}) == {}
    assert removed == 1
    assert errors == []

    # Cleanup should be marked done
    status = tag_sync.read_cleanup_legacy_status(db)
    assert status.get("cleanup_done")


def test_legacy_cleanup_tag_in_delivery_state_skipped(tag_sync, uc, db,
                                                      monkeypatch):
    """Tag already in delivery state: skipped (handled by normal cleanup)."""
    default_prefix = "x_ontos_"
    default_key = f"{default_prefix}legacy_tag"

    uc[("TABLE", "main.s.unlinked")] = {default_key: OPEX}

    def fake_bulk_read(spark, catalog, prefix):
        result = {}
        for (obj_type, fqn), tags in uc.items():
            if fqn.lower().startswith(catalog.lower()):
                result[(obj_type, fqn)] = {k: v for k, v in tags.items()
                                           if k.startswith(prefix)}
        return result

    monkeypatch.setattr(tag_sync, "_bulk_read_prefixed_tags_per_catalog",
                        fake_bulk_read)

    dataset = _asset_dataset(tag_sync, "main.s.other", [OPEX])
    direct = tag_sync.DirectLinkInfos(tables=[dataset])

    # Tag already in delivery state (will be handled by normal cleanup)
    previous = {
        "TABLE": {
            "main.s.unlinked": {default_key: OPEX}
        }
    }

    removed, errors = tag_sync.handle_legacy_tag_cleanup(
        MagicMock(), db, [dataset], direct,
        prefix=default_prefix,
        previous=previous,
        cleanup_enabled=True,
        is_partial_read=False,
        dry_run=False,
    )

    # Tag should NOT be removed (already in delivery state)
    assert uc[("TABLE", "main.s.unlinked")] == {default_key: OPEX}
    assert removed == 0


def test_legacy_cleanup_failed_removal_not_marked_done(tag_sync, uc, db,
                                                       monkeypatch):
    """Failed removal: not marked done, retried next run."""
    default_prefix = "x_ontos_"
    default_key = f"{default_prefix}legacy_tag"

    uc[("TABLE", "main.s.unlinked")] = {default_key: OPEX}

    def fake_bulk_read(spark, catalog, prefix):
        result = {}
        for (obj_type, fqn), tags in uc.items():
            if fqn.lower().startswith(catalog.lower()):
                result[(obj_type, fqn)] = {k: v for k, v in tags.items()
                                           if k.startswith(prefix)}
        return result

    def fake_unassign_fails(spark, obj_type, fqn, key):
        raise RuntimeError("PERMISSION_DENIED")

    monkeypatch.setattr(tag_sync, "_bulk_read_prefixed_tags_per_catalog",
                        fake_bulk_read)
    monkeypatch.setattr(tag_sync, "unassign_tag", fake_unassign_fails)

    dataset = _asset_dataset(tag_sync, "main.s.other", [OPEX])
    direct = tag_sync.DirectLinkInfos(tables=[dataset])
    previous = {}

    removed, errors = tag_sync.handle_legacy_tag_cleanup(
        MagicMock(), db, [dataset], direct,
        prefix=default_prefix,
        previous=previous,
        cleanup_enabled=True,
        is_partial_read=False,
        dry_run=False,
    )

    # Should have error
    assert len(errors) == 1
    assert "PERMISSION_DENIED" in errors[0]

    # Should NOT be marked done
    status = tag_sync.read_cleanup_legacy_status(db)
    assert not status.get("cleanup_done")

    # Tag should still be there
    assert uc[("TABLE", "main.s.unlinked")] == {default_key: OPEX}


def test_legacy_cleanup_dry_run_lists_no_remove(tag_sync, uc, db, monkeypatch,
                                                capsys):
    """Dry run: lists candidates but removes nothing, marks nothing."""
    default_prefix = "x_ontos_"
    default_key = f"{default_prefix}legacy_tag"

    uc[("TABLE", "main.s.unlinked")] = {default_key: OPEX}

    def fake_bulk_read(spark, catalog, prefix):
        result = {}
        for (obj_type, fqn), tags in uc.items():
            if fqn.lower().startswith(catalog.lower()):
                result[(obj_type, fqn)] = {k: v for k, v in tags.items()
                                           if k.startswith(prefix)}
        return result

    monkeypatch.setattr(tag_sync, "_bulk_read_prefixed_tags_per_catalog",
                        fake_bulk_read)

    dataset = _asset_dataset(tag_sync, "main.s.other", [OPEX])
    direct = tag_sync.DirectLinkInfos(tables=[dataset])
    previous = {}

    removed, errors = tag_sync.handle_legacy_tag_cleanup(
        MagicMock(), db, [dataset], direct,
        prefix=default_prefix,
        previous=previous,
        cleanup_enabled=True,
        is_partial_read=False,
        dry_run=True,
    )

    # Nothing removed in dry run
    assert removed == 0
    assert uc[("TABLE", "main.s.unlinked")] == {default_key: OPEX}

    # Not marked done in dry run
    status = tag_sync.read_cleanup_legacy_status(db)
    assert not status.get("cleanup_done")


def test_legacy_cleanup_flag_off_logs_samples(tag_sync, uc, db, monkeypatch,
                                              capsys):
    """Flag off: logs count + samples on first full run."""
    default_prefix = "x_ontos_"
    default_key = f"{default_prefix}legacy_tag"

    uc[("TABLE", "main.s.unlinked")] = {default_key: OPEX}

    def fake_bulk_read(spark, catalog, prefix):
        result = {}
        for (obj_type, fqn), tags in uc.items():
            if fqn.lower().startswith(catalog.lower()):
                result[(obj_type, fqn)] = {k: v for k, v in tags.items()
                                           if k.startswith(prefix)}
        return result

    monkeypatch.setattr(tag_sync, "_bulk_read_prefixed_tags_per_catalog",
                        fake_bulk_read)

    dataset = _asset_dataset(tag_sync, "main.s.other", [OPEX])
    direct = tag_sync.DirectLinkInfos(tables=[dataset])
    previous = {}

    removed, errors = tag_sync.handle_legacy_tag_cleanup(
        MagicMock(), db, [dataset], direct,
        prefix=default_prefix,
        previous=previous,
        cleanup_enabled=False,
        is_partial_read=False,
        dry_run=False,
    )

    assert removed == 0
    assert errors == []

    # Should be marked "checked"
    status = tag_sync.read_cleanup_legacy_status(db)
    assert status.get("checked_first_run")

    # Should have logged
    out = capsys.readouterr().out
    assert "Found" in out or "legacy" in out.lower()


def test_legacy_cleanup_flag_off_second_run_silent(tag_sync, uc, db,
                                                   monkeypatch, capsys):
    """Flag off: second run is silent (checked marker prevents repeat)."""
    default_prefix = "x_ontos_"

    # Mark as already checked
    with Session(db) as session:
        setting = AppSettingDb(
            key="uc_tag_sync_cleanup_legacy_status",
            value=json.dumps({"checked_first_run": True})
        )
        session.add(setting)
        session.commit()

    def fake_bulk_read(spark, catalog, prefix):
        return {}

    monkeypatch.setattr(tag_sync, "_bulk_read_prefixed_tags_per_catalog",
                        fake_bulk_read)

    dataset = _asset_dataset(tag_sync, "main.s.other", [OPEX])
    direct = tag_sync.DirectLinkInfos(tables=[dataset])
    previous = {}

    removed, errors = tag_sync.handle_legacy_tag_cleanup(
        MagicMock(), db, [dataset], direct,
        prefix=default_prefix,
        previous=previous,
        cleanup_enabled=False,
        is_partial_read=False,
        dry_run=False,
    )

    assert removed == 0
    assert errors == []


def test_legacy_cleanup_multi_level_objects(tag_sync, uc, db, monkeypatch):
    """Cleanup finds and removes candidates at all four levels."""
    default_prefix = "x_ontos_"
    default_key = f"{default_prefix}legacy"

    # Unlinked objects at all 4 levels
    uc[("CATALOG", "unlinked_cat")] = {default_key: OPEX}
    uc[("SCHEMA", "main.unlinked_sch")] = {default_key: OPEX}
    uc[("TABLE", "main.s.unlinked_t")] = {default_key: OPEX}
    uc[("COLUMN", "main.s.t.unlinked_col")] = {default_key: OPEX}

    def fake_bulk_read(spark, catalog, prefix):
        result = {}
        for (obj_type, fqn), tags in uc.items():
            if fqn.lower().startswith(catalog.lower()):
                result[(obj_type, fqn)] = {k: v for k, v in tags.items()
                                           if k.startswith(prefix)}
        return result

    def fake_unassign(spark, obj_type, fqn, key):
        uc.get((obj_type, fqn), {}).pop(key, None)

    monkeypatch.setattr(tag_sync, "_bulk_read_prefixed_tags_per_catalog",
                        fake_bulk_read)
    monkeypatch.setattr(tag_sync, "unassign_tag", fake_unassign)

    # Only one linked table
    dataset = _asset_dataset(tag_sync, "main.s.t", [OPEX])
    direct = tag_sync.DirectLinkInfos(tables=[dataset])
    previous = {}

    removed, errors = tag_sync.handle_legacy_tag_cleanup(
        MagicMock(), db, [dataset], direct,
        prefix=default_prefix,
        previous=previous,
        cleanup_enabled=True,
        is_partial_read=False,
        dry_run=False,
    )

    # Only unlinked objects in the linked catalog (main) should be removed (3, not the catalog)
    # The CATALOG "unlinked_cat" won't be scanned because it has no linked datasets
    assert removed == 3
    assert errors == []
    assert uc.get(("SCHEMA", "main.unlinked_sch"), {}) == {}
    assert uc.get(("TABLE", "main.s.unlinked_t"), {}) == {}
    assert uc.get(("COLUMN", "main.s.t.unlinked_col"), {}) == {}


def test_legacy_cleanup_keeps_tags_this_run_delivered(tag_sync, uc, db, monkeypatch):
    """A schema that inherits its tag from a linked table isn't a legacy candidate."""
    default_prefix = "x_ontos_"
    key = f"{default_prefix}legacy_tag"
    uc[("SCHEMA", "main.s")] = {key: OPEX}
    uc[("SCHEMA", "main.other")] = {key: OPEX}

    def fake_bulk_read(spark, catalog, prefix):
        return {k: dict(v) for k, v in uc.items() if k[1].startswith(catalog)}

    monkeypatch.setattr(tag_sync, "_bulk_read_prefixed_tags_per_catalog", fake_bulk_read)
    dataset = _asset_dataset(tag_sync, "main.s.t", [OPEX])
    current = {t: {} for t in tag_sync.DELIVERY_OBJECT_TYPES}
    current["SCHEMA"]["main.s"] = {key: OPEX}

    removed, errors = tag_sync.handle_legacy_tag_cleanup(
        MagicMock(), db, [dataset], tag_sync.DirectLinkInfos(),
        prefix=default_prefix, previous={}, cleanup_enabled=True,
        is_partial_read=False, dry_run=False, current=current,
    )

    assert uc[("SCHEMA", "main.s")] == {key: OPEX}
    assert key not in uc[("SCHEMA", "main.other")]
    assert (removed, errors) == (1, [])
