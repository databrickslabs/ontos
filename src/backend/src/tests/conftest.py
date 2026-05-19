# Set test environment variables BEFORE any app imports
# This prevents the app from running startup tasks (database init, etc.) during import
import os
import tempfile as _tempfile

os.environ['TESTING'] = 'true'
os.environ['SKIP_STARTUP_TASKS'] = 'true'

# Provide non-secret defaults for required Settings fields so the suite
# is runnable without a local .env. Real environments (CI or developer
# .env) still take precedence via setdefault.
os.environ.setdefault('DATABRICKS_HOST', 'https://test-databricks.local')
os.environ.setdefault('DATABRICKS_WAREHOUSE_ID', 'test-warehouse')
os.environ.setdefault('APP_AUDIT_LOG_DIR', _tempfile.gettempdir())

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool  # For in-memory SQLite persistence
from unittest.mock import MagicMock
import tempfile
import shutil

# Now safe to import app - startup tasks will be skipped
from src.app import app
from src.common.database import Base, get_db, set_session_factory # Import setter
from src.common.dependencies import get_settings_manager
from src.common.config import Settings # Import the main Settings model
from src.controller.settings_manager import SettingsManager
from src.controller.authorization_manager import AuthorizationManager
from src.controller.data_domains_manager import DataDomainManager  # Add this
from src.repositories.data_domain_repository import DataDomainRepository  # Add this
from databricks.sdk import WorkspaceClient # For mocking
from src.common.authorization import get_user_details_from_sdk
from src.common.manager_dependencies import get_data_domain_manager  # Add this
from src.models.users import UserInfo
from src.db_models.audit_log import AuditLogDb
from src.common.manager_dependencies import get_auth_manager
from src.db_models.data_products import DataProductDb
from src.models.data_products import DataProduct
# Import all DB models so SQLAlchemy knows about them when creating tables
from src.db_models.data_domains import DataDomain  # Add this
from src.db_models.settings import AppRoleDb  # Already created by settings fixture but good to be explicit
import uuid


# In-memory SQLite database for testing
# IMPORTANT: Use a single shared connection to persist schema across test functions
SQLALCHEMY_DATABASE_URL = "sqlite:///:memory:"

# Create a new engine for SQLite
test_engine = create_engine(
    SQLALCHEMY_DATABASE_URL, 
    connect_args={"check_same_thread": False}, # check_same_thread is needed for SQLite
    poolclass=StaticPool  # Use a single connection for in-memory SQLite
)
TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=test_engine)


@pytest.fixture(scope="session")
def temp_audit_log_dir():
    # Create a temporary directory for audit logs
    d = tempfile.mkdtemp()
    yield d
    # Clean up the directory after tests
    shutil.rmtree(d)


@pytest.fixture(scope="session", autouse=True)
def setup_test_database(temp_audit_log_dir): # Add temp_audit_log_dir dependency if needed for settings
    """
    Fixture to create all tables in the in-memory SQLite database once per test session.
    Initializes the global session factory for use by get_db().
    """
    # Initialize the global session factory so get_db() doesn't raise an error
    # This allows the original get_db() to work, but we'll override it per-test for transaction isolation
    set_session_factory(TestingSessionLocal)
    
    Base.metadata.create_all(bind=test_engine)
    yield
    Base.metadata.drop_all(bind=test_engine) # Clean up after tests


@pytest.fixture(scope="function", autouse=True)
def db_session(setup_test_database): # Depends on the session-scoped setup
    """
    Provides a database session for each test function, with transaction rollback.
    This fixture is autouse=True so it runs for ALL tests, ensuring get_db() is overridden.
    """
    connection = test_engine.connect()
    transaction = connection.begin()
    db = TestingSessionLocal(bind=connection)

    # Override get_db to return our test session
    # Must be a generator function (context manager) to match the original get_db signature
    def override_get_db():
        try:
            yield db
        finally:
            pass  # We manage the session lifecycle in the fixture itself

    # Set the override BEFORE any test code runs
    app.dependency_overrides[get_db] = override_get_db

    yield db

    # Cleanup
    db.close()
    transaction.rollback()
    connection.close()
    
    # Remove the override after the test
    app.dependency_overrides.pop(get_db, None)


@pytest.fixture(scope="function")
def mock_workspace_client():
    mock_client = MagicMock(spec=WorkspaceClient)
    # Configure default return values for methods that might be called during setup or basic tests
    # For example, if settings_manager.get_job_clusters() is called via settings_manager.get_settings()
    mock_client.clusters.list.return_value = [] # No clusters by default

    # Mock catalog operations
    mock_client.catalogs.list.return_value = []
    mock_client.schemas.list.return_value = []
    mock_client.tables.list.return_value = []

    # Mock job operations
    mock_client.jobs.list.return_value = []
    mock_client.jobs.get.return_value = MagicMock()

    # Mock workspace operations
    mock_client.workspace.list.return_value = []

    return mock_client


@pytest.fixture(scope="function")
def mock_test_user():
    """Provides a test user for authentication in tests."""
    return UserInfo(
        username="test_user",
        email="test@example.com",
        user="test_user",
        ip="127.0.0.1",
        groups=["test_admins"]
    )


@pytest.fixture(scope="function")
def verify_audit_log(db_session: Session):
    """Helper fixture to verify audit log entries."""
    def _verify(
        feature: str,
        action: str,
        success: bool = True,
        username: str = "test_user",
        check_details: dict = None
    ):
        audit = db_session.query(AuditLogDb).filter_by(
            feature=feature,
            action=action,
            username=username
        ).order_by(AuditLogDb.timestamp.desc()).first()

        assert audit is not None, f"No audit log found for feature='{feature}', action='{action}', username='{username}'"
        assert audit.success == success, f"Expected success={success}, got {audit.success}"

        if check_details:
            import json
            details = json.loads(audit.details) if audit.details else {}
            for key, expected_value in check_details.items():
                assert key in details, f"Expected key '{key}' not found in audit details"
                assert details[key] == expected_value, f"Expected details['{key}']={expected_value}, got {details[key]}"

        return audit

    return _verify


@pytest.fixture(scope="function")
def test_settings(temp_audit_log_dir: str) -> Settings:
    # Create a Settings instance with minimal viable test data
    # Adjust these values as necessary for your application's needs
    return Settings(
        DATABRICKS_HOST="https://test-databricks.com",
        DATABRICKS_WAREHOUSE_ID="test_warehouse_id",
        DATABRICKS_CATALOG="test_catalog",
        DATABRICKS_SCHEMA="test_schema",
        DATABRICKS_VOLUME="test_volume",
        DATABRICKS_TOKEN="test_token_val", # Even if optional, good to have a mock value
        APP_AUDIT_LOG_DIR=temp_audit_log_dir, # Use temp dir for tests
        APP_ADMIN_DEFAULT_GROUPS='["test_admins"]', # JSON string
        ENV="TEST",
        DEBUG=True,
        # Provide other required fields from your Settings model or ones with impactful defaults
        # For example, if PGHOST is used conditionally, provide it or ensure logic handles its absence
        PGHOST="localhost_test_db", # Or None if that's handled
        # Ensure all fields without defaults in Pydantic Settings model are covered
    )


@pytest.fixture(scope="function")
def client(db_session: Session, test_settings: Settings, mock_workspace_client: MagicMock, mock_test_user: UserInfo):
    """
    Provides a TestClient instance.
    Overrides get_settings_manager to use test_settings and a mock_workspace_client.
    Overrides get_user_details_from_sdk to use mock_test_user for authentication.
    Overrides get_auth_manager to use a test AuthorizationManager.
    Ensures default roles are created by SettingsManager.
    """

    # This is the actual SettingsManager instance that will be used by the app during tests
    # when get_settings_manager is called.
    settings_manager_instance = SettingsManager(
        db=db_session,
        settings=test_settings,
        workspace_client=mock_workspace_client
    )

    # Call ensure_default_roles_exist to populate necessary roles for tests
    # This needs to happen after the SettingsManager is configured with test_settings
    # as it might use settings like APP_ADMIN_DEFAULT_GROUPS
    try:
        settings_manager_instance.ensure_default_roles_exist()
        db_session.commit() # Commit role creation if successful
    except Exception as e:
        db_session.rollback() # Rollback on error
        print(f"Error ensuring default roles in test setup: {e}")
        # Depending on test needs, you might want to raise this exception
        # or log it and proceed if roles are not critical for all tests.
        # For now, we'll print and proceed.
        # raise # Uncomment to make test setup fail if role creation fails

    # Create AuthorizationManager instance for tests
    authorization_manager_instance = AuthorizationManager(
        settings_manager=settings_manager_instance
    )
    
    # Create DataDomainManager instance for tests
    data_domain_repository = DataDomainRepository()
    data_domain_manager_instance = DataDomainManager(
        repository=data_domain_repository
    )

    def override_get_settings_manager():
        return settings_manager_instance

    def override_get_auth_manager():
        return authorization_manager_instance
    
    def override_get_data_domain_manager():
        return data_domain_manager_instance

    async def override_get_user_details():
        return mock_test_user

    original_get_settings_manager = app.dependency_overrides.get(get_settings_manager)
    original_get_auth_manager = app.dependency_overrides.get(get_auth_manager)
    original_get_data_domain_manager = app.dependency_overrides.get(get_data_domain_manager)
    original_get_user_details = app.dependency_overrides.get(get_user_details_from_sdk)

    app.dependency_overrides[get_settings_manager] = override_get_settings_manager
    app.dependency_overrides[get_auth_manager] = override_get_auth_manager
    app.dependency_overrides[get_data_domain_manager] = override_get_data_domain_manager
    app.dependency_overrides[get_user_details_from_sdk] = override_get_user_details

    with TestClient(app) as c:
        yield c

    if original_get_settings_manager:
        app.dependency_overrides[get_settings_manager] = original_get_settings_manager
    else:
        app.dependency_overrides.pop(get_settings_manager, None)

    if original_get_auth_manager:
        app.dependency_overrides[get_auth_manager] = original_get_auth_manager
    else:
        app.dependency_overrides.pop(get_auth_manager, None)
    
    if original_get_data_domain_manager:
        app.dependency_overrides[get_data_domain_manager] = original_get_data_domain_manager
    else:
        app.dependency_overrides.pop(get_data_domain_manager, None)

    if original_get_user_details:
        app.dependency_overrides[get_user_details_from_sdk] = original_get_user_details
    else:
        app.dependency_overrides.pop(get_user_details_from_sdk, None)


# ============================================================================
# Data Product Fixtures
# ============================================================================

@pytest.fixture
def sample_data_product(db_session: Session):
    """Create and return a sample data product in the database."""
    product_data = DataProductDb(
        id=str(uuid.uuid4()),
        name="Sample Test Product",
        version="1.0.0",
        status="draft",
        product_type="sourceAligned",
        owner="test@example.com",
        description='{"purpose": "Test product for fixtures"}',
    )
    db_session.add(product_data)
    db_session.commit()
    db_session.refresh(product_data)
    return product_data


@pytest.fixture
def sample_data_product_dict():
    """Return a dictionary representing a data product for API calls."""
    return {
        "id": str(uuid.uuid4()),
        "name": "API Test Product",
        "description": {"purpose": "Test product for API testing"},
        "version": "1.0.0",
        "productType": "sourceAligned",
        "status": "draft",
        "owner": "test@example.com",
        "tags": ["test", "fixture"],
    }


@pytest.fixture
def multiple_data_products(db_session: Session):
    """Create multiple data products for list/pagination testing."""
    products = []
    for i in range(5):
        product = DataProductDb(
            id=str(uuid.uuid4()),
            name=f"Test Product {i}",
            version="1.0.0",
            status="draft" if i < 2 else "active",
            product_type="sourceAligned",
            owner=f"owner{i}@example.com",
            description=f'{{"purpose": "Test product {i}"}}',
        )
        db_session.add(product)
        products.append(product)

    db_session.commit()
    for product in products:
        db_session.refresh(product)

    return products 