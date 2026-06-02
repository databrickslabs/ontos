from pathlib import Path
from typing import Optional, Dict, List
import json # Import json for parsing

from fastapi import FastAPI
from sqlalchemy.orm import Session
from sqlalchemy import text

from src.common.config import get_settings, Settings
from src.common.logging import get_logger
from src.common.database import init_db, get_session_factory, Base, engine, cleanup_db
from src.common.workspace_client import get_workspace_client
from src.common.features import FeatureAccessLevel, APP_FEATURES, get_feature_config
from src.models.settings import AppRoleCreate, AppRole as AppRoleApi
from src.controller.settings_manager import SettingsManager
from src.controller.jobs_manager import JobsManager

# Import Managers needed for instantiation
from src.controller.data_products_manager import DataProductsManager
from src.controller.data_asset_reviews_manager import DataAssetReviewManager
from src.controller.data_contracts_manager import DataContractsManager
# Business glossaries manager has been removed in favor of SemanticModelsManager
from src.controller.search_manager import SearchManager
from src.controller.users_manager import UsersManager
from src.controller.authorization_manager import AuthorizationManager
from src.controller.notifications_manager import NotificationsManager
from src.controller.audit_manager import AuditManager
from src.controller.data_domains_manager import DataDomainManager # Import new manager
from src.controller.tags_manager import TagsManager # Import TagsManager
from src.controller.semantic_models_manager import SemanticModelsManager
from src.controller.teams_manager import TeamsManager
from src.controller.projects_manager import ProjectsManager

# Import repositories (needed for manager instantiation)
from src.repositories.settings_repository import AppRoleRepository
from src.repositories.audit_log_repository import AuditLogRepository
from src.repositories.data_asset_reviews_repository import DataAssetReviewRepository
from src.repositories.data_products_repository import DataProductRepository
from src.repositories.data_domain_repository import DataDomainRepository # Import new repo
# Import repository for semantic models
from src.repositories.semantic_models_repository import SemanticModelsRepository
# Import the required DB model
from src.db_models.settings import AppRoleDb
# Import the AuditLog DB model
from src.db_models.audit_log import AuditLogDb
# Import the DataAssetReviewRequestDb DB model
from src.db_models.data_asset_reviews import DataAssetReviewRequestDb
# Import the DataProductDb DB model
from src.db_models.data_products import DataProductDb, InputPortDb, OutputPortDb

# Import the CORRECT base class for type checking
from src.common.search_interfaces import SearchableAsset

# Import repositories that managers might need
from src.repositories.data_products_repository import data_product_repo
from src.repositories.settings_repository import app_role_repo
# Import tag repositories
from src.repositories.tags_repository import (
    tag_namespace_repo, tag_repo, tag_namespace_permission_repo, entity_tag_repo
)

from src.common.search_registry import SEARCHABLE_ASSET_MANAGERS

# Import connector registry and connectors for pluggable asset support
from src.connectors import get_registry
from src.connectors.databricks import DatabricksConnector
from src.connectors.snowflake import SnowflakeConnector
from src.connectors.kafka import KafkaConnector
from src.connectors.powerbi import PowerBIConnector
from src.connectors.bigquery import BigQueryConnector

logger = get_logger(__name__)

# Demo data SQL file path
DEMO_DATA_SQL_FILE = Path(__file__).parent.parent / "data" / "demo_data_retail.sql"


def load_demo_data_from_sql() -> bool:
    """
    Load demo data from the SQL file into the database.
    
    This function should only be called when:
    - APP_DEMO_MODE is True
    - APP_DB_DROP_ON_START is True (schema was recreated)
    
    Returns:
        True if demo data was loaded successfully, False otherwise.
    """
    logger.info("Loading demo data from SQL file...")
    
    if not DEMO_DATA_SQL_FILE.exists():
        logger.warning(f"Demo data SQL file not found: {DEMO_DATA_SQL_FILE}")
        return False
    
    session_factory = get_session_factory()
    if not session_factory:
        logger.error("Cannot load demo data: Database session factory not available.")
        return False
    
    try:
        with open(DEMO_DATA_SQL_FILE, 'r', encoding='utf-8') as f:
            sql_commands = f.read()
        
        if not sql_commands.strip():
            logger.warning("Demo data SQL file is empty.")
            return False
        
        with session_factory() as db:
            db.execute(text(sql_commands))
            db.commit()
        
        logger.info("✓ Demo data loaded successfully from SQL file.")
        return True
        
    except Exception as e:
        logger.error(f"Failed to load demo data from SQL: {e}", exc_info=True)
        return False


def initialize_database(settings: Settings): # Keep settings param for future use if needed
    """Initializes the database by calling the main init_db function."""
    logger.info("Triggering database initialization...")
    try:
        init_db() # Call the function from common.database
        logger.info("Database initialization routine completed successfully.")
    except ConnectionError as e:
        logger.critical(f"Database connection/initialization failed: {e}", exc_info=True)
        raise RuntimeError("Application cannot start without database connection.") from e
    except Exception as e:
        logger.critical(f"An unexpected error occurred during database initialization: {e}", exc_info=True)
        raise RuntimeError("Application cannot start due to database initialization error.") from e

def initialize_managers(app: FastAPI):
    """Initializes and stores manager instances directly in app.state."""
    logger.info("Initializing manager singletons...")
    settings = get_settings()
    session_factory = get_session_factory() # Assumes DB is initialized
    db_session = None
    ws_client = None

    # Access health state for soft-fail reporting (set in app.py startup_event)
    health = getattr(app.state, 'health', {"warnings": []})

    try:
        # --- Initialize Workspace Client (soft-fail) ---
        logger.info("Attempting to initialize WorkspaceClient...")
        try:
            ws_client = get_workspace_client(settings=settings)
            if not ws_client:
                raise RuntimeError("WorkspaceClient returned None.")
            logger.info("WorkspaceClient initialized successfully.")
            health["ws_ok"] = True
        except Exception as ws_err:
            ws_client = None
            msg = f"Workspace client unavailable: {ws_err}"
            logger.warning(msg, exc_info=True)
            health.setdefault("warnings", []).append(msg)
            health["ws_ok"] = False
        
        # --- Initialize Connector Registry ---
        logger.info("Initializing asset connector registry...")
        try:
            registry = get_registry()
            
            # Register Databricks/UC connector (primary connector)
            databricks_connector = DatabricksConnector(workspace_client=ws_client)
            registry.register_instance("databricks", databricks_connector, set_as_default=True)
            logger.info("Registered Databricks connector (default)")
            
            # Register additional connectors (lazily instantiated when first accessed)
            registry.register_class("bigquery", BigQueryConnector)
            registry.register_class("snowflake", SnowflakeConnector)
            registry.register_class("kafka", KafkaConnector)
            registry.register_class("powerbi", PowerBIConnector)
            logger.info("Registered connectors: bigquery, snowflake, kafka, powerbi")
            
            logger.info(f"Connector registry initialized with {len(registry.list_registered())} connectors")
        except Exception as e:
            logger.warning(f"Failed to initialize connector registry: {e}")
            # Don't fail startup if connector registry fails

        # --- Initialize DB Session --- 
        db_session = session_factory()

        # --- Define Data Directory --- 
        data_dir = Path(__file__).parent.parent / "data"
        if not data_dir.is_dir():
            logger.warning(f"Data directory not found: {data_dir}. Some managers might fail.")

        # --- Initialize Repositories --- 
        logger.debug("Initializing repositories...")
        app_role_repo = AppRoleRepository(model=AppRoleDb)
        # Pass the DB model to the repository constructor
        audit_repo = AuditLogRepository(model=AuditLogDb)
        data_asset_review_repo = DataAssetReviewRepository(model=DataAssetReviewRequestDb)
        data_product_repo = DataProductRepository(model=DataProductDb)
        data_domain_repo = DataDomainRepository()
        semantic_models_repo = SemanticModelsRepository(model=None)  # model unused due to singleton instance
        # Add other repos if needed
        logger.debug("Repositories initialized.")

        # --- Instantiate and Store Managers Directly on app.state --- 
        logger.debug("Instantiating managers...")
        
        # Store the global settings object on app.state for easy access
        app.state.settings = settings
        logger.info(f"Stored global settings object on app.state.settings: {type(app.state.settings)}")

        # Instantiate SettingsManager first, passing settings
        app.state.settings_manager = SettingsManager(db=db_session, settings=settings, workspace_client=ws_client)

        # Initialise ConnectionsManager — manages external connections (BQ, etc.)
        from src.controller.connections_manager import ConnectionsManager
        connections_mgr = ConnectionsManager(db=db_session, workspace_client=ws_client)
        connections_mgr.ensure_system_databricks_connection()
        migrated = connections_mgr.migrate_from_app_settings()
        if migrated:
            logger.info(f"Migrated {migrated} legacy connector config(s) to connections table")
        db_session.commit()
        app.state.connections_manager = connections_mgr
        logger.info("ConnectionsManager initialized")

        # Instantiate other managers, passing the settings_manager instance if needed
        audit_manager = AuditManager(settings=settings, db_session=db_session)
        app.state.users_manager = UsersManager(ws_client=ws_client)
        app.state.audit_manager = audit_manager
        app.state.authorization_manager = AuthorizationManager(
            settings_manager=app.state.settings_manager 
        )
        
        # Instantiate WorkspaceManager for workspace asset search
        from src.controller.workspace_manager import WorkspaceManager
        app.state.workspace_manager = WorkspaceManager(ws_client=ws_client)
        logger.info("WorkspaceManager initialized.")
        app.state.notifications_manager = NotificationsManager(settings_manager=app.state.settings_manager)
        # Back-reference for progress notifications
        app.state.settings_manager.set_notifications_manager(app.state.notifications_manager)
        # Make jobs_manager accessible via app.state
        app.state.jobs_manager = app.state.settings_manager._jobs

        # Feature Managers
        app.state.data_asset_review_manager = DataAssetReviewManager(
            db=db_session,
            ws_client=ws_client,
            notifications_manager=app.state.notifications_manager
        )
        app.state.data_domain_manager = DataDomainManager(repository=data_domain_repo)
        # data_contracts_manager moved below after tags_manager initialization
        app.state.semantic_models_manager = SemanticModelsManager(db=db_session, data_dir=Path(__file__).parent.parent / "data")
        # Also register in global app_state fallback
        try:
            from src.common.app_state import set_app_state_manager
            set_app_state_manager('semantic_models_manager', app.state.semantic_models_manager)
        except Exception:
            pass

        try:
            from src.controller.term_mapping_manager import TermMappingManager
            app.state.term_mapping_manager = TermMappingManager(
                semantic_models_manager=app.state.semantic_models_manager,
                reviews_manager=app.state.data_asset_review_manager,
                notifications_manager=app.state.notifications_manager,
            )
            logger.info("TermMappingManager initialised.")
        except Exception as e:
            logger.error(f"Failed to initialise TermMappingManager: {e}", exc_info=True)
        # Remove BusinessGlossariesManager; rely solely on SemanticModelsManager
        # app.state.business_glossaries_manager = BusinessGlossariesManager(data_dir=data_dir, semantic_models_manager=app.state.semantic_models_manager)

        # Teams and Projects Managers
        app.state.teams_manager = TeamsManager()
        app.state.projects_manager = ProjectsManager()

        # Reference Data Managers
        from src.controller.assets_manager import AssetsManager
        from src.controller.business_roles_manager import BusinessRolesManager
        from src.controller.business_owners_manager import BusinessOwnersManager
        app.state.assets_manager = AssetsManager()
        app.state.business_roles_manager = BusinessRolesManager()
        app.state.business_owners_manager = BusinessOwnersManager()
        from src.controller.delivery_methods_manager import DeliveryMethodsManager
        app.state.delivery_methods_manager = DeliveryMethodsManager()
        logger.info("Reference data managers initialized (Assets, Business Roles, Business Owners, Delivery Methods).")

        notifications_manager = getattr(app.state, 'notifications_manager', None)
        # Add other managers: Compliance, Estate, MDM, Security, Entitlements, Catalog Commander...

        # (moved) SearchManager initialization now happens AFTER all feature managers are constructed

        # Instantiate and store TagsManager
        try:
            tags_manager = TagsManager(
                namespace_repo=tag_namespace_repo,
                tag_repository=tag_repo,
                permission_repo=tag_namespace_permission_repo
                # entity_assoc_repo will be used when integrating with other features
            )
            app.state.tags_manager = tags_manager
            SEARCHABLE_ASSET_MANAGERS.append(tags_manager) # Register for search
            logger.info("TagsManager initialized and registered for search.")

            # Now instantiate DataProductsManager with TagsManager dependency
            app.state.data_products_manager = DataProductsManager(
                db=db_session,
                ws_client=ws_client,
                notifications_manager=app.state.notifications_manager,
                tags_manager=tags_manager
            )
            logger.info("DataProductsManager initialized with TagsManager integration.")
            
            # Now instantiate DataContractsManager with TagsManager dependency
            app.state.data_contracts_manager = DataContractsManager(data_dir=data_dir, tags_manager=tags_manager)
            logger.info("DataContractsManager initialized with TagsManager integration.")
            
            # Ensure default tag namespace exists (using a new session for this setup task)
            with session_factory() as setup_db:
                try:
                    tags_manager.get_or_create_default_namespace(setup_db, user_email="system@startup.ucapp")
                    logger.info("Default tag namespace ensured.")
                except Exception as e_ns:
                    logger.error(f"Failed to ensure default tag namespace: {e_ns}", exc_info=True)
                    # Decide if this is a fatal error for startup

        except Exception as e:
            logger.error(f"Error initializing TagsManager: {e}", exc_info=True)
            # Decide if this is a fatal error

        # --- Instantiate MetadataManager (if it exists and needs to be in app.state) --- 
        # This was removed in previous steps as tag CRUD moved to TagsManager
        # If MetadataManager still has other responsibilities, initialize it here.
        # For now, assuming it's not strictly needed for basic app startup if its main role was tags.
        # if hasattr(app.state, 'ws_client'): # Example: if it needs ws_client
        #     metadata_manager = MetadataManager(ws_client=app.state.ws_client)
        #     app.state.metadata_manager = metadata_manager
        #     SEARCHABLE_ASSET_MANAGERS.append(metadata_manager) # If it's searchable
        #     logger.info("MetadataManager initialized.")

        # --- OntologySchemaManager ---
        try:
            from src.controller.ontology_schema_manager import OntologySchemaManager
            app.state.ontology_schema_manager = OntologySchemaManager(
                semantic_models_manager=app.state.semantic_models_manager
            )
            # Wire ontology into AssetsManager for property validation
            if hasattr(app.state, 'assets_manager'):
                app.state.assets_manager._ontology = app.state.ontology_schema_manager
            logger.info("OntologySchemaManager initialized.")

            # Sync ontology-defined asset types to AssetTypeDb
            with session_factory() as sync_db:
                try:
                    sync_result = app.state.ontology_schema_manager.sync_asset_types(sync_db)
                    logger.info(
                        f"Ontology asset type sync: {len(sync_result.created)} created, "
                        f"{len(sync_result.updated)} updated, {len(sync_result.errors)} errors"
                    )
                except Exception as e_sync:
                    logger.error(f"Failed to sync ontology asset types: {e_sync}", exc_info=True)
        except Exception as e:
            logger.error(f"Failed to initialize OntologySchemaManager: {e}", exc_info=True)

        # --- OntologyGeneratorManager ---
        try:
            from src.controller.ontology_generator_manager import OntologyGeneratorManager
            app.state.ontology_generator_manager = OntologyGeneratorManager(settings=settings)
            logger.info("OntologyGeneratorManager initialized.")
        except Exception as e:
            logger.error(f"Failed to initialize OntologyGeneratorManager: {e}", exc_info=True)

        # --- EntityRelationshipsManager ---
        try:
            from src.controller.entity_relationships_manager import EntityRelationshipsManager
            app.state.entity_relationships_manager = EntityRelationshipsManager(
                ontology_schema_manager=app.state.ontology_schema_manager
            )
            logger.info("EntityRelationshipsManager initialized.")
        except Exception as e:
            logger.error(f"Failed to initialize EntityRelationshipsManager: {e}", exc_info=True)

        # --- EntitySubscriptionsManager ---
        try:
            from src.controller.entity_subscriptions_manager import EntitySubscriptionsManager
            app.state.entity_subscriptions_manager = EntitySubscriptionsManager()
            logger.info("EntitySubscriptionsManager initialized.")
        except Exception as e:
            logger.error(f"Failed to initialize EntitySubscriptionsManager: {e}", exc_info=True)

        try:
            from src.controller.directory_manager import DirectoryManager
            app.state.directory_manager = DirectoryManager()
            logger.info("DirectoryManager initialized.")
        except Exception as e:
            logger.error(f"Failed to initialize DirectoryManager: {e}", exc_info=True)

        logger.info("All managers instantiated and stored in app.state.")

        # Defer SearchManager initialization until after initial data loading completes
        logger.info("Deferring SearchManager initialization until after initial data load.")
        
        # --- Ensure default roles exist using the manager method --- 
        app.state.settings_manager.ensure_default_roles_exist()

        # --- Backfill Admin role with ADMIN on any newly-added feature IDs ---
        # Idempotent migration; covers the settings-* sub-page permissions
        # added by the Settings permissions refactor and any future additions.
        app.state.settings_manager.upgrade_admin_role_for_new_features()

        # --- Ensure default team and project exist for admins ---
        app.state.settings_manager.ensure_default_team_and_project()

        # --- Commit session potentially used for default role creation ---
        # This commit is crucial AFTER all managers are initialized AND
        # default roles are potentially created by the SettingsManager
        db_session.commit()
        logger.info("Manager initialization and default role creation transaction committed.")

        # --- Start background job polling ---
        try:
            if app.state.jobs_manager:
                # Use configured polling interval (default: 5 minutes)
                app.state.jobs_manager.start_background_polling(interval_seconds=settings.JOB_POLLING_INTERVAL_SECONDS)
                logger.info(f"Started background job polling (interval: {settings.JOB_POLLING_INTERVAL_SECONDS}s)")
        except Exception as e:
            logger.error(f"Failed to start background job polling: {e}", exc_info=True)
            # Don't fail startup if polling fails to start

        # --- Load demo data if conditions are met ---
        # Only load demo data when:
        # 1. APP_DEMO_MODE is enabled
        # 2. APP_DB_DROP_ON_START is enabled (schema was recreated)
        if settings.APP_DEMO_MODE and settings.APP_DB_DROP_ON_START:
            logger.info("APP_DEMO_MODE and APP_DB_DROP_ON_START both enabled - loading demo data...")
            try:
                load_demo_data_from_sql()
                # Rebuild semantic models cache to include demo data
                if hasattr(app.state, 'semantic_models_manager') and app.state.semantic_models_manager:
                    try:
                        app.state.semantic_models_manager.rebuild_graph_from_enabled()
                        logger.info("Rebuilt semantic models cache to include demo data.")
                    except Exception as e:
                        logger.warning(f"Failed to rebuild semantic models cache: {e}")
            except Exception as e:
                logger.error(f"Failed to load demo data: {e}", exc_info=True)
                # Don't fail startup if demo data loading fails
        elif settings.APP_DEMO_MODE:
            logger.info("APP_DEMO_MODE enabled but APP_DB_DROP_ON_START disabled - skipping automatic demo data loading.")
            logger.info("Use POST /api/settings/demo-data/load to load demo data manually.")

    except Exception as e:
        logger.critical(f"Failed during application startup (manager init or default roles): {e}", exc_info=True)
        if db_session: db_session.rollback()
        msg = f"Manager initialization failed: {e}"
        health.setdefault("warnings", []).append(msg)
    finally:
        # Keep the DB session open for manager singletons that rely on it.
        # It will be managed at application shutdown.
        pass

async def startup_event_handler(app: FastAPI):
    """
    Application startup event handler.
    
    Note: Demo data is loaded on-demand via POST /api/settings/demo-data/load.
    Each preset is a standalone self-contained demo pack:
        - retail (default): src/backend/src/data/demo_data_retail.sql
        - hls:               src/backend/src/data/demo_data_hls.sql
        - fsi:               src/backend/src/data/demo_data_fsi.sql
        - mfg:               src/backend/src/data/demo_data_mfg.sql
        - auto:              src/backend/src/data/demo_data_auto.sql
    """
    logger.info("Executing application startup event handler...")
    try:
        initialize_database() # Step 1: Setup Database
        logger.info("Database initialization sequence complete.")

        # Step 1b: Seed reference data that the alembic data-migrations would
        # have inserted but that `create_all()` cannot. On a fresh database
        # init_db() takes the create_all() + stamp path (no `alembic upgrade`),
        # so any rows seeded inside migrations (e.g. Bronze/Silver/Gold in
        # a8_add_certification_levels_table.py) never get written. The
        # seed_defaults() calls below are idempotent — they no-op if rows exist.
        try:
            from src.repositories.certification_levels_repository import certification_levels_repo

            session_factory = get_session_factory()
            with session_factory() as db_session:
                certification_levels_repo.seed_defaults(db_session)
                db_session.commit()
            logger.info("Reference data seed step complete.")
        except Exception as e:
            logger.warning(f"Failed seeding reference data: {e}", exc_info=True)

        # Step 2: Initialize managers (requires ws_client to be set up if managers need it)
        # Create a temporary session for manager initializations that require DB access (like default namespace)
        # Note: Managers themselves should request sessions via DBSessionDep for their operational methods.
        initialize_managers(app) # Pass the app to store managers in app.state
        logger.info("Managers initialization sequence complete.")

        # Step 3: Build the SearchManager
        try:
            logger.info("Initializing SearchManager...")
            searchable_managers_instances = []
            for attr_name, manager_instance in list(getattr(app.state, '_state', {}).items()):
                try:
                    if isinstance(manager_instance, SearchableAsset) and hasattr(manager_instance, 'get_search_index_items'):
                        searchable_managers_instances.append(manager_instance)
                        logger.debug(f"Added searchable manager instance from app.state: {attr_name}")
                except Exception:
                    continue

            app.state.search_manager = SearchManager(searchable_managers=searchable_managers_instances)
            app.state.search_manager.build_index()
            for mgr in searchable_managers_instances:
                mgr.set_search_manager(app.state.search_manager)
            logger.info("Search index initialized and built from DB-backed managers.")
        except Exception as e:
            logger.error(f"Failed initializing or building search index: {e}", exc_info=True)

        # Step 4: Load default workflows
        try:
            logger.info("Loading default process workflows...")
            from src.controller.workflows_manager import WorkflowsManager
            session_factory = get_session_factory()
            with session_factory() as db_session:
                workflows_manager = WorkflowsManager(db_session)
                count = workflows_manager.load_from_yaml()
                logger.info(f"Loaded {count} default process workflow(s)")
        except Exception as e:
            logger.warning(f"Failed loading default workflows: {e}", exc_info=True)

        # Step 5: Initialize Git service for indirect delivery mode
        try:
            logger.info("Initializing Git service...")
            from src.common.git import init_git_service
            settings = get_settings()
            git_service = init_git_service(settings)
            app.state.git_service = git_service
            logger.info(f"Git service initialized (status: {git_service.get_status().clone_status.value})")
        except Exception as e:
            logger.warning(f"Failed initializing Git service: {e}", exc_info=True)
            # Don't fail startup if Git service initialization fails
            git_service = None

        # Step 6: Initialize Grant Manager for direct delivery mode
        try:
            logger.info("Initializing Grant Manager...")
            from src.controller.grant_manager import init_grant_manager
            settings = get_settings()
            ws_client = get_workspace_client(settings=settings)
            grant_manager = init_grant_manager(ws_client=ws_client, settings=settings)
            app.state.grant_manager = grant_manager
            logger.info("Grant Manager initialized")
        except Exception as e:
            logger.warning(f"Failed initializing Grant Manager: {e}", exc_info=True)
            grant_manager = None

        # Step 7: Initialize Delivery Service for multi-mode delivery
        try:
            logger.info("Initializing Delivery Service...")
            from src.controller.delivery_service import init_delivery_service
            settings = get_settings()
            delivery_service = init_delivery_service(
                settings=settings,
                git_service=getattr(app.state, 'git_service', None),
                grant_manager=getattr(app.state, 'grant_manager', None),
                notifications_manager=getattr(app.state, 'notifications_manager', None),
            )
            app.state.delivery_service = delivery_service
            logger.info(f"Delivery Service initialized (active modes: {[m.value for m in delivery_service.get_active_modes()]})")
        except Exception as e:
            logger.warning(f"Failed initializing Delivery Service: {e}", exc_info=True)

        logger.info("Application startup event handler finished successfully.")
    except Exception as e:
        logger.critical(f"CRITICAL ERROR during application startup: {e}", exc_info=True)
        # Depending on the severity, you might want to prevent the app from starting
        # or raise the exception to let FastAPI handle it (which might stop the server).
        # For now, just logging critically.

async def shutdown_event_handler(app: FastAPI):
    # Implement shutdown logic here
    logger.info("Executing application shutdown event handler...")
    
    # Cleanup database resources (including OAuth token refresh thread)
    try:
        cleanup_db()
        logger.info("Database cleanup completed successfully")
    except Exception as e:
        logger.error(f"Error during database cleanup: {e}", exc_info=True)
    
    # Add any other necessary cleanup or resource release logic here
    logger.info("Application shutdown event handler finished successfully.") 
