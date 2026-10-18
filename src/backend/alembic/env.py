from logging.config import fileConfig

from sqlalchemy import engine_from_config, text
from sqlalchemy import pool

from alembic import context

# --- Import application-specific components ---
import os
import sys
from src.common.database import Base, get_db_url, _oauth_token # Import Base, helper, and OAuth token
from src.common.config import get_settings, Settings, init_config # Import settings loader, model, AND initializer
# Add the project root to the Python path to allow imports from src.*
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
if PROJECT_ROOT not in sys.path:
    sys.path.append(PROJECT_ROOT)
# ---------------------------------------------

# this is the Alembic Config object, which provides
# access to the values within the .ini file in use.
config = context.config

# Interpret the config file for Python logging.
# This line sets up loggers basically.
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# --- Alembic configuration for the application --- 
# Import the Base from your application
# from src.common.database import Base # Already imported above
# Import all model modules to ensure they are registered with Base.metadata
# import src.db_models.data_products
# import src.db_models.notification
# import src.db_models.audit_log
# import src.db_models.settings
# import src.db_models.data_asset_reviews
# Instead of individual imports, import the package to run __init__.py
import src.db_models
# Ensure all models defined in src.db_models.__all__ are now known to Base.metadata

# Set the target metadata for autogenerate
target_metadata = Base.metadata

# --- Load settings and DB URL --- 
# Use a function to handle potential errors during settings loading
def load_app_settings() -> Settings:
    try:
        # Ensure settings are initialized before getting them
        init_config() 
        return get_settings()
    except Exception as e:
        print(f"ERROR: Failed to load application settings for Alembic: {e}")
        # Optionally re-raise or exit if settings are critical
        # sys.exit(1)
        raise # Re-raise for now

settings = load_app_settings()
DB_URL = get_db_url(settings) # Use your helper to construct the URL

# For Lakebase mode: Check if OAuth token was passed via environment variable
# This happens when Alembic is run as a subprocess from database.py
ALEMBIC_DB_PASSWORD = os.environ.get("ALEMBIC_DB_PASSWORD")
if ALEMBIC_DB_PASSWORD:
    # Inject the password into the URL for Lakebase authentication
    from sqlalchemy.engine import make_url
    url_obj = make_url(DB_URL)
    DB_URL = url_obj.set(password=ALEMBIC_DB_PASSWORD).render_as_string(hide_password=False)
    print("INFO: Using OAuth token from ALEMBIC_DB_PASSWORD environment variable")
# --------------------------------

# --- Include Object Hook (To ignore indexes for Databricks SQL) ---
# search_documents columns the app adds at runtime when semantic search is on
# (they need pgvector); autogenerate must never propose dropping them.
_RUNTIME_COLUMNS = {("search_documents", c) for c in (
    "embedding", "embedding_hash", "embedded_at", "embedding_claimed_at",
)}


def include_object(object, name, type_, reflected, compare_to):
    """Exclude indexes from Alembic's consideration."""
    if type_ == "index":
        # print(f"Ignoring index: {name}") # Optional: for debugging
        return False
    if type_ == "column" and reflected and compare_to is None \
            and (getattr(object.table, "name", None), name) in _RUNTIME_COLUMNS:
        return False
    return True
# -----------------------------------------------------------------

# other values from the config, defined by the needs of env.py,
# can be acquired:
# my_important_option = config.get_main_option("my_important_option")
# ... etc.


def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode.

    This configures the context with just a URL
    and not an Engine, though an Engine is acceptable
    here as well.  By skipping the Engine creation
    we don't even need a DBAPI to be available.

    Calls to context.execute() here emit the given string to the
    script output.

    """
    # url = config.get_main_option("sqlalchemy.url") # <-- Don't get from config
    context.configure(
        url=DB_URL, # <--- Use the URL from settings
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        include_object=include_object # Add hook here too if generating offline
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Run migrations in 'online' mode.

    In this scenario we need to create an Engine
    and associate a connection with the context.

    """
    # Check if an engine was provided via config.attributes (from database.py)
    # This engine has OAuth token injection configured for Lakebase
    provided_engine = config.attributes.get('engine', None)
    target_schema = config.attributes.get('target_schema', None)
    
    if provided_engine is not None:
        # Create a COMPLETELY SEPARATE engine for Alembic with its own connection pool
        # This prevents AUTOCOMMIT from affecting the main application's connections
        import logging
        from sqlalchemy import create_engine, event
        
        logger = logging.getLogger("alembic.env")
        logger.info("env.py: Creating dedicated AUTOCOMMIT engine for migrations")
        
        # Create a new engine with AUTOCOMMIT and NullPool (no connection sharing)
        alembic_engine = create_engine(
            provided_engine.url,
            isolation_level="AUTOCOMMIT",
            poolclass=pool.NullPool,  # No pooling - completely isolated
        )
        
        # Register OAuth token injection for Lakebase connections
        # Access the token from the database module
        @event.listens_for(alembic_engine, "do_connect")
        def inject_oauth_token(dialect, conn_rec, cargs, cparams):
            # Import here to get the current token value
            from src.common.database import _oauth_token
            if _oauth_token:
                cparams["password"] = _oauth_token
                logger.debug("env.py: Injected OAuth token into connection")
        
        try:
            logger.info(f"env.py: Connecting to database with target_schema={target_schema}")
            with alembic_engine.connect() as connection:
                logger.info("env.py: Connection established")
                
                # Set search_path (commits immediately in AUTOCOMMIT mode)
                if target_schema:
                    logger.info(f"env.py: Setting search_path to {target_schema}")
                    connection.execute(text(f'SET search_path TO "{target_schema}"'))
                
                logger.info("env.py: Configuring Alembic context")
                context.configure(
                    connection=connection,
                    target_metadata=target_metadata,
                    include_object=include_object,
                    transactional_ddl=False,  # Tell Alembic not to use transactions
                    transaction_per_migration=False,  # No per-migration transactions
                    version_table_schema=target_schema,  # Ensure alembic_version is in correct schema
                )
                
                # Don't use begin_transaction() - AUTOCOMMIT handles each statement
                logger.info("env.py: Running migrations (AUTOCOMMIT mode, no transaction wrapper)")
                context.run_migrations()
                logger.info("env.py: Migrations completed")
        except Exception as e:
            logger.error(f"env.py: Migration failed with error: {e}", exc_info=True)
            raise
        finally:
            # Dispose the dedicated engine - this is critical to not leak connections
            alembic_engine.dispose()
            logger.info("env.py: Dedicated Alembic engine disposed")
    else:
        # Standalone mode - create own engine (for CLI usage like `alembic upgrade head`)
        # Also used for stamp operations from database.py when engine is not passed
        import logging
        logger = logging.getLogger("alembic.env")
        
        configuration = config.get_section(config.config_ini_section, {})
        configuration["sqlalchemy.url"] = DB_URL

        logger.info("env.py: Standalone mode - creating engine from URL")
        connectable = engine_from_config(
            configuration,
            prefix="sqlalchemy.",
            poolclass=pool.NullPool,
        )

        try:
            with connectable.connect() as connection:
                logger.info("env.py: Standalone mode - connection established")
                context.configure(
                    connection=connection, 
                    target_metadata=target_metadata,
                    include_object=include_object
                )

                logger.info("env.py: Standalone mode - running migrations with transaction")
                with context.begin_transaction():
                    context.run_migrations()
                logger.info("env.py: Standalone mode - migrations completed")
        finally:
            connectable.dispose()
            logger.info("env.py: Standalone mode - engine disposed")


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
