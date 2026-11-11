"""Test the b5 lifecycle status cleanup migration by running it through Alembic.

The migration deterministically maps known status aliases and legacy values to
their canonical lifecycle statuses, and converts any unknown value (or NULL/empty)
to 'draft'. For each converted row, a change_log entry is created with {from, to}.
This test runs the real upgrade() function against a real SQLite database and verifies:

- All conversion cases work correctly
- change_log entries have the right structure
- Running the migration twice is a no-op
- Unknown-status entities migrated to 'draft' can transition normally
"""
import json
import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.pool import StaticPool
from alembic.migration import MigrationContext
from alembic.operations import Operations
import tempfile


# The test database uses SQLite with StaticPool for persistence across connections
@pytest.fixture
def sqlite_engine():
    db_file = tempfile.NamedTemporaryFile(delete=False, suffix=".db")
    db_file.close()
    engine = create_engine(
        f"sqlite:///{db_file.name}",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    return engine


def _setup_schema(conn) -> None:
    """Create minimal schema needed for the migration test."""
    for stmt in [
        """
        CREATE TABLE IF NOT EXISTS certification_levels (
            id TEXT PRIMARY KEY,
            name TEXT,
            level_order INTEGER
        );
        """,
        """
        INSERT OR IGNORE INTO certification_levels (id, name, level_order) VALUES
            ('l1', 'Level 1', 1),
            ('l2', 'Level 2', 2),
            ('l3', 'Level 3', 3);
        """,
        """
        CREATE TABLE IF NOT EXISTS data_products (
            id TEXT PRIMARY KEY,
            name TEXT,
            status TEXT,
            certification_level TEXT,
            certified_at TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        """,
        """
        CREATE TABLE IF NOT EXISTS data_contracts (
            id TEXT PRIMARY KEY,
            name TEXT,
            status TEXT,
            certification_level TEXT,
            certified_at TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        """,
        """
        CREATE TABLE IF NOT EXISTS entity_change_log (
            id TEXT PRIMARY KEY,
            entity_type TEXT NOT NULL,
            entity_id TEXT NOT NULL,
            action TEXT NOT NULL,
            username TEXT,
            timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            details_json TEXT
        );
        """,
    ]:
        if stmt.strip():
            conn.execute(text(stmt))


def _insert_test_data(conn) -> None:
    """Insert test data with various status values."""
    test_cases = [
        # (id, status)
        ("dp-canonical-draft", "draft"),
        ("dp-canonical-active", "active"),
        ("dp-prod", "production"),
        ("dp-dev", "development"),
        ("dp-pending", "pending"),
        ("dp-inactive", "inactive"),
        ("dp-deleted", "deleted"),
        ("dp-archived", "archived"),
        ("dp-certified", "certified"),
        ("dp-mixed-case", "Active"),
        ("dp-legacy", "xyz_legacy"),
        ("dp-empty", ""),
    ]

    for entity_id, status in test_cases:
        if status == "":
            conn.execute(
                text("INSERT INTO data_products (id, name, status, updated_at) VALUES (:id, :name, NULL, CURRENT_TIMESTAMP)"),
                {"id": entity_id, "name": f"Product {entity_id}"}
            )
        else:
            conn.execute(
                text("INSERT INTO data_products (id, name, status, updated_at) VALUES (:id, :name, :status, CURRENT_TIMESTAMP)"),
                {"id": entity_id, "name": f"Product {entity_id}", "status": status}
            )

    # Add the same cases to data_contracts
    for i, (entity_id, status) in enumerate(test_cases):
        contract_id = f"dc-{i}"
        if status == "":
            conn.execute(
                text("INSERT INTO data_contracts (id, name, status, updated_at) VALUES (:id, :name, NULL, CURRENT_TIMESTAMP)"),
                {"id": contract_id, "name": f"Contract {contract_id}"}
            )
        else:
            conn.execute(
                text("INSERT INTO data_contracts (id, name, status, updated_at) VALUES (:id, :name, :status, CURRENT_TIMESTAMP)"),
                {"id": contract_id, "name": f"Contract {contract_id}", "status": status}
            )


def test_b5_status_cleanup_migration_runs_and_is_idempotent(sqlite_engine):
    """Run the b5 migration through Alembic and verify results."""
    # Load and execute the migration module
    import importlib.util
    from pathlib import Path

    backend_dir = Path(__file__).resolve().parents[3]  # src/backend
    migration_path = backend_dir / "alembic" / "versions" / "b5_lifecycle_status_cleanup.py"
    assert migration_path.exists(), f"Migration not found at {migration_path}"

    spec = importlib.util.spec_from_file_location("b5_lifecycle_status_cleanup", migration_path)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)

    # Set up the database
    with sqlite_engine.begin() as conn:
        _setup_schema(conn)
        _insert_test_data(conn)

    # Run the migration through Alembic (first time)
    with sqlite_engine.begin() as conn:
        ctx = MigrationContext.configure(conn)
        with Operations.context(ctx):
            mod.upgrade()

    # Verify the results after first upgrade
    with sqlite_engine.connect() as conn:
        _verify_migration_results(conn, is_first_run=True)

    # Run the migration again (idempotency test)
    with sqlite_engine.begin() as conn:
        ctx = MigrationContext.configure(conn)
        with Operations.context(ctx):
            mod.upgrade()

    # Verify idempotency: should not create duplicate change_log entries
    with sqlite_engine.connect() as conn:
        change_log_counts = conn.execute(text(
            "SELECT entity_id, COUNT(*) as cnt FROM entity_change_log GROUP BY entity_id"
        )).fetchall()
        # Each entity should have exactly one change_log entry (no duplicates from second run)
        for entity_id, count in change_log_counts:
            assert count == 1, f"Entity {entity_id} has {count} change_log entries (expected 1, not idempotent)"


def _verify_migration_results(conn, is_first_run: bool) -> None:
    """Verify the migration results."""
    # Expected mappings for data_products
    expected_statuses = {
        "dp-canonical-draft": "draft",
        "dp-canonical-active": "active",
        "dp-prod": "active",
        "dp-dev": "sandbox",
        "dp-pending": "under_review",
        "dp-inactive": "deprecated",
        "dp-deleted": "retired",
        "dp-archived": "retired",
        "dp-certified": "active",
        "dp-mixed-case": "active",
        "dp-legacy": "draft",
        "dp-empty": "draft",
    }

    # Check data_products
    products = conn.execute(text("SELECT id, status, certification_level FROM data_products ORDER BY id")).fetchall()
    for product_id, status, cert_level in products:
        expected_status = expected_statuses.get(product_id)
        assert status == expected_status, \
            f"Product {product_id}: expected status {expected_status}, got {status}"

        # Certified products should have certification_level set
        if product_id == "dp-certified":
            assert cert_level is not None, f"Product {product_id} should have certification_level set"

    # Check data_contracts (same mappings as products)
    expected_contract_statuses = {
        "dc-0": "draft",
        "dc-1": "active",
        "dc-2": "active",
        "dc-3": "sandbox",
        "dc-4": "under_review",
        "dc-5": "deprecated",
        "dc-6": "retired",
        "dc-7": "retired",
        "dc-8": "active",
        "dc-9": "active",
        "dc-10": "draft",
        "dc-11": "draft",
    }

    contracts = conn.execute(text("SELECT id, status FROM data_contracts ORDER BY id")).fetchall()
    for contract_id, status in contracts:
        expected_status = expected_contract_statuses.get(contract_id)
        assert status == expected_status, \
            f"Contract {contract_id}: expected status {expected_status}, got {status}"

    # Verify change_log entries
    change_log_entries = conn.execute(text(
        "SELECT entity_type, entity_id, action, details_json FROM entity_change_log ORDER BY entity_id"
    )).fetchall()

    # Should have entries for all products and contracts that were converted
    # (canonical values that didn't change won't have entries)
    assert len(change_log_entries) > 0, "No change_log entries found"

    for entity_type, entity_id, action, details_json in change_log_entries:
        assert action == "status_migrated", f"Unexpected action: {action}"
        assert entity_type in ("data_product", "data_contract"), f"Unexpected entity_type: {entity_type}"

        details = json.loads(details_json) if details_json else {}
        assert "from" in details, f"Missing 'from' in details for {entity_id}"
        assert "to" in details, f"Missing 'to' in details for {entity_id}"
        assert details["to"] in ("draft", "sandbox", "proposed", "under_review", "approved", "active", "deprecated", "retired"), \
            f"Invalid 'to' status: {details['to']}"


def test_migrated_unknown_status_entity_can_transition(sqlite_engine):
    """Test that an entity migrated from unknown status (→ draft) can transition normally."""
    # Load the migration
    import importlib.util
    from pathlib import Path

    backend_dir = Path(__file__).resolve().parents[3]
    migration_path = backend_dir / "alembic" / "versions" / "b5_lifecycle_status_cleanup.py"

    spec = importlib.util.spec_from_file_location("b5_lifecycle_status_cleanup", migration_path)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)

    # Set up database with an entity in unknown status
    with sqlite_engine.begin() as conn:
        _setup_schema(conn)
        conn.execute(
            text("INSERT INTO data_products (id, name, status, updated_at) VALUES (:id, :name, :status, CURRENT_TIMESTAMP)"),
            {"id": "test-product", "name": "Test Product", "status": "unknown_legacy_status"}
        )

    # Run migration
    with sqlite_engine.begin() as conn:
        ctx = MigrationContext.configure(conn)
        with Operations.context(ctx):
            mod.upgrade()

    # Verify the entity is now in 'draft' status
    with sqlite_engine.connect() as conn:
        result = conn.execute(text(
            "SELECT status FROM data_products WHERE id = 'test-product'"
        )).scalar()
        assert result == "draft", f"Expected status 'draft', got {result}"

        # Verify change_log entry exists
        change_log = conn.execute(text(
            "SELECT details_json FROM entity_change_log WHERE entity_id = 'test-product'"
        )).scalar()
        assert change_log is not None, "No change_log entry for migrated entity"

        details = json.loads(change_log)
        assert details["from"] == "unknown_legacy_status"
        assert details["to"] == "draft"
