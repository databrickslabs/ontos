import os
import uuid
import time
import threading
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Dict, List, Optional, TypeVar

from sqlalchemy import create_engine, text, event
from sqlalchemy.orm import sessionmaker, Session as SQLAlchemySession
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy import pool
from sqlalchemy.engine import Connection, URL

from alembic.config import Config as AlembicConfig
from alembic.script import ScriptDirectory
from alembic.runtime.migration import MigrationContext
from alembic import command as alembic_command

from .config import get_settings, Settings
from .logging import get_logger
from src.common.workspace_client import get_workspace_client
from src.common.unity_catalog_utils import (
    ensure_catalog_exists,
    ensure_schema_exists,
    sanitize_postgres_identifier,
)
# Import SDK components
from databricks.sdk.errors import NotFound, DatabricksError
from databricks.sdk.core import Config, oauth_service_principal

logger = get_logger(__name__)

T = TypeVar('T')

# Define the base class for SQLAlchemy models
Base = declarative_base()

# --- Import all db_models so every table is registered with Base --- #
# Model modules are imported in src.db_models.__init__.py; importing the
# package here ensures Base.metadata is populated before init_db needs it.
logger.debug("Importing all DB model modules to register with Base...")
try:
    import src.db_models  # noqa: F401
    logger.debug("DB model modules imported successfully.")
except ImportError as e:
    logger.critical(
        f"Failed to import a DB model module during initial registration: {e}", exc_info=True)
    raise
# ------------------------------------------------------------------------- #

# Singleton engine instance
_engine = None
_SessionLocal = None
# Public engine instance (will be assigned after creation)
engine = None

# OAuth token state for Lakebase connections
_oauth_token: Optional[str] = None
_token_last_refresh: float = 0
_token_refresh_lock = threading.Lock()
_token_refresh_thread: Optional[threading.Thread] = None
_token_refresh_stop_event = threading.Event()


@dataclass
class LakebaseInfo:
    """Connection info for a Lakebase database resource (provisioned or autoscale)."""
    lakebase_type: str  # "provisioned" or "autoscale"
    identifier: str     # instance_name (provisioned) or endpoint resource name (autoscale)


# Cached LakebaseInfo to avoid repeated API calls during token refreshes
_lakebase_info: Optional[LakebaseInfo] = None


def get_lakebase_info(app_name: str, ws_client) -> Optional[LakebaseInfo]:
    """Detect the Lakebase type (provisioned or autoscale) from the Databricks App resources
    and return the identifier needed for credential generation.

    For provisioned Lakebase, returns the instance name from ``resource.database``.
    For autoscale Lakebase, discovers the endpoint via ``resource.postgres.branch``
    and ``ws_client.postgres.list_endpoints``.

    The result is cached globally so subsequent token refreshes skip the API calls.
    """
    global _lakebase_info
    if _lakebase_info is not None:
        return _lakebase_info

    try:
        app_info = ws_client.apps.get(app_name)
        if app_info.resources:
            for resource in app_info.resources:
                # Provisioned Lakebase — resource.database with instance_name
                if resource.database is not None:
                    _lakebase_info = LakebaseInfo("provisioned", resource.database.instance_name)
                    logger.info(f"Detected provisioned Lakebase instance: {_lakebase_info.identifier}")
                    return _lakebase_info

                # Autoscale Lakebase — resource.postgres with branch
                # Use hasattr for SDK compatibility (postgres attr added in SDK >=0.95.0)
                if hasattr(resource, 'postgres') and resource.postgres is not None:
                    branch = resource.postgres.branch
                    logger.info(f"Detected autoscale Lakebase resource on branch: {branch}")
                    endpoints = list(ws_client.postgres.list_endpoints(parent=branch))
                    if endpoints:
                        endpoint_name = endpoints[0].name
                        _lakebase_info = LakebaseInfo("autoscale", endpoint_name)
                        logger.info(f"Resolved autoscale Lakebase endpoint: {endpoint_name}")
                        return _lakebase_info
                    else:
                        logger.error(f"No endpoints found for autoscale Lakebase branch: {branch}")
    except Exception as e:
        logger.error(f"Failed to get Lakebase info for app {app_name}: {e}")
    return None


@dataclass
class InMemorySession:
    """In-memory session for managing transactions."""
    changes: List[Dict[str, Any]]

    def __init__(self):
        self.changes = []

    def commit(self):
        """Commit changes to the global store."""

    def rollback(self):
        """Discard changes."""
        self.changes = []


class InMemoryStore:
    """In-memory storage system."""

    def __init__(self):
        """Initialize the in-memory store."""
        self._data: Dict[str, List[Dict[str, Any]]] = {}
        self._metadata: Dict[str, Dict[str, Any]] = {}

    def create_table(self, table_name: str, metadata: Dict[str, Any] = None) -> None:
        """Create a new table in the store.

        Args:
            table_name: Name of the table
            metadata: Optional metadata for the table
        """
        if table_name not in self._data:
            self._data[table_name] = []
            if metadata:
                self._metadata[table_name] = metadata

    def insert(self, table_name: str, data: Dict[str, Any]) -> None:
        """Insert a record into a table.

        Args:
            table_name: Name of the table
            data: Record to insert
        """
        if table_name not in self._data:
            self.create_table(table_name)

        # Add timestamp and id if not present
        if 'id' not in data:
            data['id'] = str(len(self._data[table_name]) + 1)
        if 'created_at' not in data:
            data['created_at'] = datetime.utcnow().isoformat()
        if 'updated_at' not in data:
            data['updated_at'] = data['created_at']

        self._data[table_name].append(data)

    def get(self, table_name: str, id: str) -> Optional[Dict[str, Any]]:
        """Get a record by ID.

        Args:
            table_name: Name of the table
            id: Record ID

        Returns:
            Record if found, None otherwise
        """
        if table_name not in self._data:
            return None
        return next((item for item in self._data[table_name] if item['id'] == id), None)

    def get_all(self, table_name: str) -> List[Dict[str, Any]]:
        """Get all records from a table.

        Args:
            table_name: Name of the table

        Returns:
            List of records
        """
        return self._data.get(table_name, [])

    def update(self, table_name: str, id: str, data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Update a record.

        Args:
            table_name: Name of the table
            id: Record ID
            data: Updated data

        Returns:
            Updated record if found, None otherwise
        """
        if table_name not in self._data:
            return None

        for item in self._data[table_name]:
            if item['id'] == id:
                item.update(data)
                item['updated_at'] = datetime.utcnow().isoformat()
                return item
        return None

    def delete(self, table_name: str, id: str) -> bool:
        """Delete a record.

        Args:
            table_name: Name of the table
            id: Record ID

        Returns:
            True if deleted, False otherwise
        """
        if table_name not in self._data:
            return False

        initial_length = len(self._data[table_name])
        self._data[table_name] = [
            item for item in self._data[table_name] if item['id'] != id]
        return len(self._data[table_name]) < initial_length

    def clear(self, table_name: str) -> None:
        """Clear all records from a table.

        Args:
            table_name: Name of the table
        """
        if table_name in self._data:
            self._data[table_name] = []


class DatabaseManager:
    """Manages in-memory database operations."""

    def __init__(self) -> None:
        """Initialize the database manager."""
        self.store = InMemoryStore()

    @contextmanager
    def get_session(self) -> InMemorySession:
        """Get a database session.

        Yields:
            In-memory session

        Raises:
            Exception: If session operations fail
        """
        session = InMemorySession()
        try:
            yield session
            session.commit()
        except Exception as e:
            session.rollback()
            logger.error(f"Database session error: {e!s}")
            raise

    def dispose(self) -> None:
        """Clear all data from the store."""
        self.store = InMemoryStore()


# Global database manager instance
db_manager: Optional[DatabaseManager] = None


def refresh_oauth_token(settings: Settings) -> str:
    """Generate fresh OAuth token from Databricks for Lakebase connection."""
    global _oauth_token, _token_last_refresh
    
    with _token_refresh_lock:
        ws_client = get_workspace_client(settings)
        info = get_lakebase_info(settings.DATABRICKS_APP_NAME, ws_client)
        
        if not info and settings.LAKEBASE_INSTANCE_NAME:
            # Fallback: use LAKEBASE_INSTANCE_NAME env var when app resource lookup fails
            logger.info(f"Using LAKEBASE_INSTANCE_NAME fallback: {settings.LAKEBASE_INSTANCE_NAME}")
            if settings.LAKEBASE_INSTANCE_NAME.startswith("projects/"):
                info = LakebaseInfo("autoscale", settings.LAKEBASE_INSTANCE_NAME)
            else:
                info = LakebaseInfo("provisioned", settings.LAKEBASE_INSTANCE_NAME)

        if not info:
            raise ValueError(f"Could not determine Lakebase info for app '{settings.DATABRICKS_APP_NAME}'")
        
        logger.info(f"Generating OAuth token for Lakebase ({info.lakebase_type}): {info.identifier}")

        if info.lakebase_type == "provisioned":
            cred = ws_client.database.generate_database_credential(
                request_id=str(uuid.uuid4()),
                instance_names=[info.identifier],
            )
        else:
            cred = ws_client.postgres.generate_database_credential(
                endpoint=info.identifier,
            )
        
        _oauth_token = cred.token
        _token_last_refresh = time.time()
        logger.info("OAuth token refreshed successfully")
        
        return _oauth_token


def start_token_refresh_background(settings: Settings):
    """Start background thread to refresh OAuth tokens every 50 minutes."""
    global _token_refresh_thread, _token_refresh_stop_event
    
    def refresh_loop():
        while not _token_refresh_stop_event.is_set():
            _token_refresh_stop_event.wait(50 * 60)  # 50 minutes
            if not _token_refresh_stop_event.is_set():
                try:
                    refresh_oauth_token(settings)
                except Exception as e:
                    logger.error(f"Background token refresh failed: {e}", exc_info=True)
    
    _token_refresh_stop_event.clear()
    _token_refresh_thread = threading.Thread(target=refresh_loop, daemon=True)
    _token_refresh_thread.start()
    logger.info("OAuth token refresh background thread started")


def stop_token_refresh_background():
    """Stop the background token refresh thread."""
    global _token_refresh_stop_event, _token_refresh_thread
    if _token_refresh_thread and _token_refresh_thread.is_alive():
        _token_refresh_stop_event.set()
        _token_refresh_thread.join(timeout=2)
        logger.info("OAuth token refresh background thread stopped")


def _use_password_auth(settings: Settings) -> bool:
    """Determine if password auth should be used for the database.
    True when ENV=LOCAL or when DB_USE_PASSWORD_AUTH is explicitly set."""
    return settings.ENV.upper().startswith("LOCAL") or settings.DB_USE_PASSWORD_AUTH


def get_db_url(settings: Settings) -> str:
    """Construct the PostgreSQL SQLAlchemy URL with appropriate auth method."""
    
    # Validate required settings
    if not all([settings.PGHOST, settings.PGDATABASE]):
        raise ValueError("PostgreSQL connection details (PGHOST, PGDATABASE) are missing in settings.")
    
    use_password_auth = _use_password_auth(settings)
    
    if use_password_auth:
        logger.info("Database: Using password authentication (LOCAL mode)")
        if not settings.PGPASSWORD or not settings.PGUSER:
            raise ValueError("PGPASSWORD and PGUSER required for LOCAL mode")
        username = settings.PGUSER
        password = settings.PGPASSWORD
    else:
        logger.info("Database: Using OAuth authentication (Lakebase mode)")
        # Dynamically determine username from authenticated principal
        ws_client = get_workspace_client(settings)
        username = (
            os.getenv("DATABRICKS_CLIENT_ID")
            or ws_client.current_user.me().user_name
        )
        if not username:
            raise ValueError("Could not determine database username from authenticated principal")
        
        logger.info(f"🔑 Detected service principal username: {username}")
        password = ""  # Will be set via event handler
    
    # Build URL with schema options and statement timeout
    query_params = {}
    options_list = []
    
    # Add schema to search_path if specified
    if settings.PGSCHEMA:
        # Validate schema name for connection options to prevent injection
        try:
            validated_schema = sanitize_postgres_identifier(settings.PGSCHEMA)
        except ValueError as e:
            raise ValueError(
                f"Invalid PostgreSQL schema identifier in PGSCHEMA: {e}. "
                "Please check configuration."
            ) from e
        options_list.append(f"-csearch_path={validated_schema}")
        logger.info(f"PostgreSQL schema will be set via options: {validated_schema}")
    else:
        logger.info("No specific PostgreSQL schema configured, using default (public).")
    
    # Add statement timeout to prevent indefinite locks (30 seconds)
    # This helps prevent stuck transactions when operations fail
    options_list.append("-cstatement_timeout=30000")
    logger.info("PostgreSQL statement timeout set to 30 seconds")
    
    if options_list:
        query_params["options"] = " ".join(options_list)
    
    db_url_obj = URL.create(
        drivername="postgresql+psycopg2",
        username=username,
        password=password,
        host=settings.PGHOST,
        port=settings.PGPORT,
        database=settings.PGDATABASE,
        query=query_params if query_params else None
    )
    url_str = db_url_obj.render_as_string(hide_password=False)
    logger.debug(
        f"Constructed PostgreSQL SQLAlchemy URL using URL.create (credentials redacted in log): "
        f"{db_url_obj.render_as_string(hide_password=True)}"
    )
    return url_str


def ensure_database_and_schema_exist(settings: Settings):
    """
    Ensure the target database and schema exist. If not, create them.
    Works in both LOCAL and OAuth modes (authentication differs but logic is unified).
    
    If APP_DB_DROP_ON_START=true, drops the schema CASCADE before creating it.
    Connects to default postgres database to create target database (OAuth mode only),
    then creates schema within it.
    
    The app (as service principal) becomes the owner of what it creates in OAuth mode,
    eliminating permission issues.
    
    Security: All PostgreSQL identifiers are validated to prevent SQL injection.
    """
    is_local_mode = _use_password_auth(settings)
    
    logger.info(f"Ensuring database and schema exist ({'password' if is_local_mode else 'OAuth'} auth mode)...")
    
    # Determine username based on mode
    if is_local_mode:
        username = settings.PGUSER
    else:
        # Get service principal username for OAuth mode
        ws_client = get_workspace_client(settings)
        username = (
            os.getenv("DATABRICKS_CLIENT_ID")
            or ws_client.current_user.me().user_name
        )
    
    if not username:
        raise ValueError("Could not determine username/service principal")
    
    # Validate all PostgreSQL identifiers to prevent SQL injection
    try:
        target_db = sanitize_postgres_identifier(settings.PGDATABASE)
        target_schema = sanitize_postgres_identifier(settings.PGSCHEMA) if settings.PGSCHEMA else None
        username = sanitize_postgres_identifier(username)
    except ValueError as e:
        raise ValueError(
            f"Invalid PostgreSQL identifier in configuration: {e}. "
            "Please check PGDATABASE, PGSCHEMA, and username."
        ) from e
    
    logger.info(f"Username: {username}")
    logger.debug(f"Target database: {target_db}, schema: {target_schema}")
    
    # Generate initial OAuth token for OAuth mode
    if not is_local_mode:
        refresh_oauth_token(settings)
    
    # Build connection URL
    # In OAuth mode, connect directly to the target database (must be pre-created)
    # In LOCAL mode, connect to the target database (should already exist)
    connection_url = URL.create(
        drivername="postgresql+psycopg2",
        username=username,
        password=settings.PGPASSWORD if is_local_mode else "",
        host=settings.PGHOST,
        port=settings.PGPORT,
        database=target_db,
    )
    
    # Create temporary engine for schema setup
    temp_engine = create_engine(
        connection_url.render_as_string(hide_password=False),
        isolation_level="AUTOCOMMIT"  # Needed for CREATE SCHEMA
    )
    
    # Inject OAuth token for connections in OAuth mode
    if not is_local_mode:
        @event.listens_for(temp_engine, "do_connect")
        def inject_token_temp(dialect, conn_rec, cargs, cparams):
            global _oauth_token
            if _oauth_token:
                cparams["password"] = _oauth_token
    
    try:
        # In OAuth mode, verify we can connect to the target database
        # The database must be pre-created by an admin with: 
        #   CREATE DATABASE "app_ontos"; GRANT CREATE ON DATABASE "app_ontos" TO PUBLIC;
        if not is_local_mode:
            try:
                with temp_engine.connect() as conn:
                    conn.execute(text("SELECT 1"))
                    logger.info(f"✓ Connected to database: {target_db}")
            except Exception as e:
                error_msg = str(e).lower()
                if "does not exist" in error_msg or "database" in error_msg:
                    raise RuntimeError(
                        f"Database '{target_db}' does not exist.\n\n"
                        f"SETUP REQUIRED: Before deploying the app, create the database:\n"
                        f"  1. Connect to your Lakebase instance as an admin\n"
                        f"  2. Run these SQL commands:\n"
                        f'     CREATE DATABASE "{target_db}";\n'
                        f'     GRANT CREATE ON DATABASE "{target_db}" TO PUBLIC;\n'
                        f"  3. Restart the app\n\n"
                        f"See the README for detailed setup instructions."
                    ) from e
                raise
        
        # Now handle schema (works for both LOCAL and OAuth modes)
        with temp_engine.connect() as conn:
            if target_schema and target_schema != "public":
                # Handle APP_DB_DROP_ON_START: Drop schema CASCADE before creating
                if settings.APP_DB_DROP_ON_START:
                    logger.warning(f"APP_DB_DROP_ON_START=true: Dropping schema '{target_schema}' CASCADE...")
                    # DROP SCHEMA cannot be parameterized, but identifier is validated
                    conn.execute(text(f'DROP SCHEMA IF EXISTS "{target_schema}" CASCADE'))
                    conn.commit()
                    logger.warning(f"✓ Schema '{target_schema}' dropped CASCADE. Will be recreated.")
                    
                    # Explicitly drop application enum types from public schema
                    # These are often created in public and not dropped with CASCADE on a specific schema
                    logger.info("Dropping application enum types from public schema...")
                    enum_types = ['commentstatus', 'commenttype', 'accesslevel']
                    for enum_type in enum_types:
                        try:
                            conn.execute(text(f'DROP TYPE IF EXISTS "{enum_type}" CASCADE'))
                        except Exception as e:
                            logger.warning(f"Could not drop enum type '{enum_type}': {e}")
                    conn.commit()
                    logger.info("✓ Enum types cleanup completed.")
                
                # Check if schema exists (using parameterized query)
                result = conn.execute(
                    text("SELECT 1 FROM information_schema.schemata WHERE schema_name = :schemaname"),
                    {"schemaname": target_schema}
                )
                schema_exists = result.scalar() is not None
                
                if not schema_exists:
                    logger.info(f"Creating schema: {target_schema}")
                    # CREATE SCHEMA cannot be parameterized, but identifier is validated
                    conn.execute(text(f'CREATE SCHEMA IF NOT EXISTS "{target_schema}"'))
                    logger.info(f"✓ Schema created: {target_schema} (owner: {username})")
                    
                    # Set default privileges for future objects (OAuth mode only)
                    if not is_local_mode:
                        # ALTER statements cannot be parameterized, but identifiers are validated
                        logger.info(f"Setting default privileges in schema: {target_schema}")
                        conn.execute(text(
                            f'ALTER DEFAULT PRIVILEGES IN SCHEMA "{target_schema}" '
                            f'GRANT ALL ON TABLES TO "{username}"'
                        ))
                        conn.execute(text(
                            f'ALTER DEFAULT PRIVILEGES IN SCHEMA "{target_schema}" '
                            f'GRANT ALL ON SEQUENCES TO "{username}"'
                        ))
                        logger.info(f"✓ Default privileges configured")
                    
                    conn.commit()
                else:
                    logger.info(f"✓ Schema already exists: {target_schema}")
            else:
                logger.info(f"Using public schema (no custom schema specified)")
        
    except Exception as e:
        if "permission denied" in str(e).lower():
            logger.error(
                f"❌ Permission denied - check database/schema privileges for user '{username}'"
            )
            if not is_local_mode:
                logger.error(f"To fix this, run as a Lakebase admin:")
                logger.error(f'  DROP DATABASE IF EXISTS "{target_db}";')
                logger.error(f'  CREATE DATABASE "{target_db}";')
                logger.error(f'  GRANT CREATE ON DATABASE "{target_db}" TO "{username}";')
        logger.error(f"Error ensuring database/schema exist: {e}", exc_info=True)
        raise
    finally:
        temp_engine.dispose()
    
    logger.info("✓ Database and schema are ready")


def ensure_catalog_schema_exists(settings: Settings):
    """Checks if the configured catalog and schema exist, creates them if not.
    
    Uses shared Unity Catalog utilities for secure, idempotent catalog/schema creation.
    """
    logger.info("Ensuring required catalog and schema exist...")
    try:
        # Get a workspace client instance
        # Note: Using the caching client is fine; shared utilities handle idempotency
        ws_client = get_workspace_client(settings)

        catalog_name = settings.DATABRICKS_CATALOG
        schema_name = settings.DATABRICKS_SCHEMA
        full_schema_name = f"{catalog_name}.{schema_name}"

        # Use shared utilities for secure, idempotent creation
        try:
            logger.debug(f"Ensuring catalog exists: {catalog_name}")
            ensure_catalog_exists(
                ws=ws_client,
                catalog_name=catalog_name,
                comment=f"System catalog for {settings.APP_NAME}"
            )
            logger.info(f"Catalog '{catalog_name}' is ready.")
        except Exception as e:
            # Map HTTPException or other errors to ConnectionError for consistency
            logger.critical(
                f"Failed to ensure catalog '{catalog_name}': {e}. Check permissions.", 
                exc_info=True
            )
            raise ConnectionError(
                f"Failed to create required catalog '{catalog_name}': {e}"
            ) from e

        try:
            logger.debug(f"Ensuring schema exists: {full_schema_name}")
            ensure_schema_exists(
                ws=ws_client,
                catalog_name=catalog_name,
                schema_name=schema_name,
                comment=f"System schema for {settings.APP_NAME}"
            )
            logger.info(f"Schema '{full_schema_name}' is ready.")
        except Exception as e:
            logger.critical(
                f"Failed to ensure schema '{full_schema_name}': {e}. Check permissions.", 
                exc_info=True
            )
            raise ConnectionError(
                f"Failed to create required schema '{full_schema_name}': {e}"
            ) from e

        logger.info(f"✓ Unity Catalog namespace ready: {full_schema_name}")

    except ConnectionError:
        # Re-raise ConnectionError as-is
        raise
    except Exception as e:
        logger.critical(
            f"An unexpected error occurred during catalog/schema check/creation: {e}", 
            exc_info=True
        )
        raise ConnectionError(
            f"Failed during catalog/schema setup: {e}"
        ) from e


def get_current_db_revision(engine_connection: Connection, alembic_cfg: AlembicConfig) -> str | None:
    """Gets the current revision of the database."""
    context = MigrationContext.configure(engine_connection)
    return context.get_current_revision()


def init_db() -> None:
    """Initializes the database connection, checks/creates catalog/schema, and runs migrations."""
    global _engine, _SessionLocal, engine
    settings = get_settings()

    if _engine is not None:
        logger.debug("Database engine already initialized.")
        return

    logger.info("Initializing database engine and session factory...")
    
    # Ensure database and schema exist (creates them if needed in OAuth mode)
    ensure_database_and_schema_exist(settings)

    try:
        db_url = get_db_url(settings)

        # PostgreSQL connect args are typically empty; URL contains necessary options
        connect_args = {}

        logger.info("Connecting to database...")
        logger.info(f"> Database URL: {db_url}")
        logger.info(f"> Connect args: {connect_args}")
        logger.info(f"> Pool settings: size={settings.DB_POOL_SIZE}, max_overflow={settings.DB_MAX_OVERFLOW}, "
                   f"timeout={settings.DB_POOL_TIMEOUT}s, recycle={settings.DB_POOL_RECYCLE}s")
        
        _engine = create_engine(db_url,
                                connect_args=connect_args, 
                                echo=settings.DB_ECHO, 
                                poolclass=pool.QueuePool, 
                                pool_size=settings.DB_POOL_SIZE, 
                                max_overflow=settings.DB_MAX_OVERFLOW,
                                pool_timeout=settings.DB_POOL_TIMEOUT,
                                pool_recycle=settings.DB_POOL_RECYCLE,
                                pool_pre_ping=True)
        engine = _engine # Assign to public variable

        # Add OAuth token injection if using Lakebase OAuth auth
        if not _use_password_auth(settings):
            logger.info("Setting up OAuth token injection for Lakebase...")
            
            # Generate initial token
            refresh_oauth_token(settings)
            
            # Register event handler to inject tokens for new connections
            # Use 'do_connect' event to inject password at connection creation time
            @event.listens_for(_engine, "do_connect")
            def inject_token_on_connect(dialect, conn_rec, cargs, cparams):
                global _oauth_token
                if _oauth_token:
                    cparams["password"] = _oauth_token
                    logger.debug("Injected OAuth token into new database connection")
            
            # Start background refresh thread
            start_token_refresh_background(settings)
            logger.info("OAuth authentication configured successfully")
        else:
            logger.info("Password authentication configured for LOCAL mode")

        # Explicitly enforce search_path at connection time to ensure correct schema usage in environments
        # where connection options may be ignored.
        if settings.PGSCHEMA:
            # Validate schema name to prevent SQL injection in SET command
            try:
                target_schema = sanitize_postgres_identifier(settings.PGSCHEMA)
            except ValueError as e:
                logger.error(f"Invalid PostgreSQL schema name in PGSCHEMA: {e}")
                raise ValueError(
                    f"Invalid PostgreSQL schema identifier in PGSCHEMA: {e}. "
                    "Please check configuration."
                ) from e

            @event.listens_for(_engine, "connect")
            def set_search_path(dbapi_connection, connection_record):
                try:
                    with dbapi_connection.cursor() as cursor:
                        # SET command cannot be parameterized, but identifier is validated
                        cursor.execute(f'SET search_path TO "{target_schema}"')
                except Exception as e:
                    # Log and continue; the app can still operate using default schema if necessary
                    logger.warning(f"Failed to set search_path to '{target_schema}': {e}")

        _SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=_engine)
        logger.info("Database engine and session factory initialized.")

        # --- Alembic Migration Logic --- #
        alembic_cfg_path = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..' , 'alembic.ini'))
        alembic_script_location = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', 'alembic'))
        logger.info(f"Loading Alembic configuration from: {alembic_cfg_path}")
        logger.info(f"Alembic script location: {alembic_script_location}")
        alembic_cfg = AlembicConfig(alembic_cfg_path)
        alembic_cfg.set_main_option("sqlalchemy.url", db_url.replace("%", "%%")) # Ensure Alembic uses the same URL
        alembic_cfg.set_main_option("script_location", alembic_script_location) # Set absolute path to alembic directory
        script = ScriptDirectory.from_config(alembic_cfg)
        head_revision = script.get_current_head()
        logger.info(f"Alembic Head Revision: {head_revision}")

        # Get current database revision - use separate connection to avoid lock contention
        # IMPORTANT: Must close this connection before doing upgrades to prevent deadlock
        # when the upgrade tries to write to alembic_version while we still hold a read lock
        logger.info("Getting current database revision...")
        with engine.connect() as connection:
            db_revision = get_current_db_revision(connection, alembic_cfg)
        # CRITICAL: Dispose the engine pool immediately after getting revision.
        # This releases the connection used by MigrationContext and clears any
        # implicit transaction state that could interfere with subsequent Alembic operations.
        logger.info("Disposing engine pool after revision check...")
        _engine.dispose()
        logger.info(f"Current Database Revision: {db_revision}")

        # Handle migrations based on database state
        if db_revision is None:
            # Fresh database - will use create_all() + stamp later
            logger.info("Fresh database detected (no Alembic version table). Will initialize with create_all() and stamp.")
        elif db_revision != head_revision:
            # Existing database needs migration
            logger.info(f"Database revision '{db_revision}' differs from head revision '{head_revision}'.")
            logger.info("Attempting Alembic upgrade to head...")
            try:
                # CRITICAL: Dispose the main engine's connection pool before running Alembic.
                # This releases all pooled connections that might hold implicit transaction state.
                logger.info("Disposing engine pool to release connections before Alembic migration...")
                _engine.dispose()
                
                # Run Alembic upgrade via subprocess to avoid hanging issues with
                # Alembic's internal runpy-based execution when called programmatically.
                # This ensures proper process isolation and cleanup.
                import subprocess
                import sys
                import shutil

                # For Lakebase (OAuth mode), we need to pass the token to the subprocess
                # via environment variable since the subprocess can't access our in-memory token
                subprocess_env = os.environ.copy()
                is_lakebase_mode = not _use_password_auth(settings)
                if is_lakebase_mode:
                    # Refresh token to ensure it's valid for the subprocess
                    logger.info("Refreshing OAuth token for Alembic subprocess...")
                    token = refresh_oauth_token(settings)
                    subprocess_env["ALEMBIC_DB_PASSWORD"] = token
                    logger.info("OAuth token passed to subprocess via environment variable")

                # Find Python executable reliably for containerized environments
                python_executable = None

                # Try sys.executable first if it exists and is absolute
                if sys.executable and os.path.isabs(sys.executable) and os.path.exists(sys.executable):
                    python_executable = sys.executable
                    logger.info(f"Using sys.executable: {python_executable}")
                else:
                    # sys.executable is unreliable (relative path or doesn't exist)
                    # Try to find venv Python relative to the current working directory or script location
                    potential_venv_paths = [
                        os.path.join(os.getcwd(), ".venv", "bin", "python3"),
                        os.path.join(os.getcwd(), ".venv", "bin", "python"),
                        os.path.join(os.getcwd(), "venv", "bin", "python3"),
                        os.path.join(os.getcwd(), "venv", "bin", "python"),
                        # Try relative to the backend src directory
                        os.path.join(os.path.dirname(__file__), "..", "..", ".venv", "bin", "python3"),
                        os.path.join(os.path.dirname(__file__), "..", "..", ".venv", "bin", "python"),
                        # Try system Python as fallback
                        "/usr/local/bin/python3",
                        "/usr/bin/python3",
                    ]

                    for path in potential_venv_paths:
                        abs_path = os.path.abspath(path)
                        if os.path.exists(abs_path):
                            python_executable = abs_path
                            logger.info(f"Found Python executable at: {python_executable}")
                            break

                    # Last resort: try to find alembic executable directly
                    if not python_executable:
                        alembic_path = shutil.which("alembic")
                        if alembic_path:
                            logger.warning("Could not find Python executable, will try running alembic command directly")
                            python_executable = None  # Will use alembic directly below
                        else:
                            raise RuntimeError(
                                f"Could not find Python executable for Alembic subprocess. "
                                f"sys.executable={sys.executable}, cwd={os.getcwd()}, "
                                f"tried paths: {potential_venv_paths}"
                            )

                # Run alembic upgrade
                if python_executable:
                    cmd = [python_executable, "-m", "alembic", "upgrade", "head"]
                else:
                    # Use alembic command directly
                    cmd = ["alembic", "upgrade", "head"]

                logger.info(f"Running Alembic upgrade command: {' '.join(cmd)}")
                result = subprocess.run(
                    cmd,
                    cwd=os.path.dirname(alembic_script_location),  # Run from backend dir
                    capture_output=True,
                    text=True,
                    timeout=300,  # 5 minute timeout
                    env=subprocess_env
                )
                if result.returncode != 0:
                    logger.error(f"Alembic upgrade stderr: {result.stderr}")
                    raise RuntimeError(f"Alembic upgrade failed with exit code {result.returncode}: {result.stderr}")
                logger.info(f"Alembic upgrade output: {result.stdout}")
                logger.info("✓ Alembic upgrade to head COMPLETED.")
            except subprocess.TimeoutExpired:
                logger.critical("Alembic upgrade timed out after 5 minutes!")
                raise RuntimeError("Alembic upgrade timed out")
            except Exception as alembic_err:
                logger.critical("Alembic upgrade failed! Manual intervention may be required.", exc_info=True)
                raise RuntimeError("Failed to upgrade database schema.") from alembic_err
        else:
            logger.info("✓ Database schema is up to date according to Alembic.")

        # Ensure all tables defined in Base metadata exist
        logger.info("Verifying/creating tables based on SQLAlchemy models...")
        # Schema for create_all if PostgreSQL
        schema_to_create_in = None
        if settings.PGSCHEMA:
            schema_to_create_in = settings.PGSCHEMA
            # We need to ensure this schema exists before calling create_all if it's not 'public'
            # and if tables don't explicitly define their schema.
            # SQLAlchemy create_all does not create schemas.
            # The search_path option in the URL handles where tables are looked for and created if no schema is specified on the Table object.
            # However, for explicit control, ensuring schema existence might be needed.
            # For now, relying on search_path. If schema needs explicit creation:
            # with engine.connect() as connection:
            # connection.execute(sqlalchemy.text(f"CREATE SCHEMA IF NOT EXISTS {schema_to_create_in}"))
            # connection.commit()
            logger.info(f"PostgreSQL: Tables will be targeted for schema '{schema_to_create_in}' via search_path or model definitions.")

        # No Databricks-specific metadata modifications required
        
        # Note: Schema creation and APP_DB_DROP_ON_START handling is done in 
        # ensure_database_and_schema_exist() before Alembic migrations run

        # Only use create_all() for fresh databases without Alembic version table
        # Once Alembic is tracking the schema, migrations handle all schema changes
        if db_revision is None:
            logger.info("Fresh database detected (no Alembic version). Using create_all() for initial setup...")
            target_schema = settings.PGSCHEMA or 'public'
            
            # Create all tables in the target schema
            with _engine.begin() as connection:
                # Explicitly set search_path to ensure tables are created in correct schema
                connection.execute(text(f'SET search_path TO "{target_schema}"'))
                Base.metadata.create_all(bind=connection, checkfirst=True)
            logger.info("✓ Database tables created by create_all.")
            
            # Stamp the database with the baseline migration
            # Using direct INSERT instead of alembic_command.stamp() to avoid 
            # hanging issues with Alembic's runpy-based execution in some environments
            logger.info("Stamping database with baseline migration...")
            try:
                with _engine.begin() as connection:
                    connection.execute(text(f'SET search_path TO "{target_schema}"'))
                    # Create alembic_version table if needed and insert head revision
                    connection.execute(text("""
                        CREATE TABLE IF NOT EXISTS alembic_version (
                            version_num VARCHAR(32) NOT NULL,
                            CONSTRAINT alembic_version_pkc PRIMARY KEY (version_num)
                        )
                    """))
                    connection.execute(text("DELETE FROM alembic_version"))
                    connection.execute(text("INSERT INTO alembic_version (version_num) VALUES (:rev)"), 
                                      {"rev": head_revision})
                logger.info(f"✓ Database stamped with baseline migration: {head_revision}")
            except Exception as stamp_err:
                logger.error(f"Failed to stamp database: {stamp_err}", exc_info=True)
                raise
        else:
            logger.info("✓ Database schema is managed by Alembic migrations.")
    except Exception as e:
        logger.critical(f"Database initialization failed: {e}", exc_info=True)
        _engine = None
        _SessionLocal = None
        engine = None # Reset public engine on failure
        raise ConnectionError("Failed to initialize database connection or run migrations.") from e

def get_db():
    global _SessionLocal
    if _SessionLocal is None:
        logger.error("Database not initialized. Cannot get session.")
        # Consider raising HTTPException for FastAPI to handle gracefully if this occurs at runtime
        raise RuntimeError("Database session factory is not available. Database might not have been initialized correctly.")
    
    db = _SessionLocal()
    try:
        yield db
        db.commit()  # Commit the transaction on successful completion of the request
    except Exception as e: # Catch all exceptions to ensure rollback
        logger.error(f"Error during database session for request, rolling back: {e}", exc_info=True)
        db.rollback()
        # Re-raise the exception so FastAPI can handle it appropriately
        # (e.g., return a 500 error or specific HTTPException if e is one)
        raise
    finally:
        db.close()

@contextmanager
def get_db_session():
    """Context manager that yields a SQLAlchemy session.

    Ensures the session is committed on success and rolled back on error,
    and that the session is always closed. If the session factory is not
    initialized yet, it attempts to initialize the database first.
    """
    global _SessionLocal
    if _SessionLocal is None:
        try:
            init_db()
        except Exception as e:
            logger.critical(f"Failed to initialize database session factory: {e}", exc_info=True)
            raise RuntimeError("Database session factory not available and initialization failed.") from e

    session = _SessionLocal()
    try:
        yield session
        session.commit()
    except Exception as e:
        logger.error(f"Error during database session, rolling back: {e}", exc_info=True)
        session.rollback()
        raise
    finally:
        session.close()

def get_engine():
    global _engine
    if _engine is None:
        raise RuntimeError("Database engine not initialized.")
    return _engine

def get_session_factory():
    global _SessionLocal
    if _SessionLocal is None:
        raise RuntimeError("Database session factory not initialized.")
    return _SessionLocal


def set_session_factory(factory):
    """
    Set the global session factory. Used by tests to inject a test database session factory.
    
    Args:
        factory: A sessionmaker instance or callable that returns database sessions
    """
    global _SessionLocal
    _SessionLocal = factory

def cleanup_db():
    """Cleanup database resources including OAuth token refresh."""
    global _engine, _SessionLocal, engine
    
    # Stop token refresh if running
    stop_token_refresh_background()
    
    # Dispose engine
    if _engine:
        _engine.dispose()
        logger.info("Database engine disposed")
    
    _engine = None
    _SessionLocal = None
    engine = None
