# Initialize configuration and logging first
from src.common.config import get_settings, init_config
from src.common.logging import get_logger, setup_logging

init_config()
settings = get_settings()
setup_logging(level=settings.LOG_LEVEL, log_file=settings.LOG_FILE)
logger = get_logger(__name__)

import os
import time
from pathlib import Path

# Server startup timestamp for cache invalidation
SERVER_STARTUP_TIME = int(time.time())

from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles

from src.common.middleware import ErrorHandlingMiddleware, LoggingMiddleware
from src.routes import (
    access_grants_routes,
    audit_routes,
    catalog_commander_routes,
    change_log_routes,
    comments_routes,
    compliance_routes,
    costs_routes,
    data_asset_reviews_routes,
    data_catalog_routes,
    data_contracts_routes,
    data_domains_routes,
    data_product_routes,
    datasets_routes,
    entitlements_routes,
    entitlements_sync_routes,
    estate_manager_routes,
    jobs_routes,
    llm_search_routes,
    mcp_routes,
    mcp_tokens_routes,
    mdm_routes,
    metadata_routes,
    notifications_routes,
    projects_routes,
    search_routes,
    security_features_routes,
    self_service_routes,
    semantic_links_routes,
    semantic_models_routes,
    settings_routes,
    tags_routes,
    teams_routes,
    user_routes,
    graph_explorer_routes,
    workflows_routes,
    workspace_routes,
)
from src.utils.startup_tasks import initialize_database, initialize_managers

logger.info(f"Starting application in {settings.ENV} mode.")
logger.info(f"Debug mode: {settings.DEBUG}")

# Define paths earlier for use in startup
BASE_DIR = Path(__file__).parent
DATA_DIR = BASE_DIR / "data"
STATIC_ASSETS_PATH = BASE_DIR.parent / "static"

# --- Dependency Providers (Defined globally or before app) ---

# def get_auth_manager(request: Request) -> AuthorizationManager:
# ... (rest of the function is removed)

# --- Application Lifecycle Events ---


# Application Startup Event
async def startup_event():
    import os

    # Skip startup tasks if running tests
    if os.getenv("SKIP_STARTUP_TASKS") == "true":
        logger.info("SKIP_STARTUP_TASKS=true detected - skipping startup tasks (test mode)")
        return

    logger.info("Running application startup event...")
    settings = get_settings()

    initialize_database(settings=settings)
    initialize_managers(app)  # Handles DB-backed manager init

    # Initialize Git service for indirect delivery mode
    try:
        logger.info("Initializing Git service...")
        from src.common.git import init_git_service

        git_service = init_git_service(settings)
        app.state.git_service = git_service
        logger.info(
            f"Git service initialized (status: {git_service.get_status().clone_status.value})"
        )
    except Exception as e:
        logger.warning(f"Failed initializing Git service: {e}", exc_info=True)
        app.state.git_service = None

    # Initialize Grant Manager for direct delivery mode
    try:
        logger.info("Initializing Grant Manager...")
        from src.common.workspace_client import get_workspace_client
        from src.controller.grant_manager import init_grant_manager

        ws_client = get_workspace_client(settings=settings)
        grant_manager = init_grant_manager(ws_client=ws_client, settings=settings)
        app.state.grant_manager = grant_manager
        logger.info("Grant Manager initialized")
    except Exception as e:
        logger.warning(f"Failed initializing Grant Manager: {e}", exc_info=True)
        app.state.grant_manager = None

    # Initialize Delivery Service for multi-mode delivery
    try:
        logger.info("Initializing Delivery Service...")
        from src.controller.delivery_service import init_delivery_service

        delivery_service = init_delivery_service(
            settings=settings,
            git_service=getattr(app.state, "git_service", None),
            grant_manager=getattr(app.state, "grant_manager", None),
            notifications_manager=getattr(app.state, "notifications_manager", None),
        )
        app.state.delivery_service = delivery_service
        logger.info(
            f"Delivery Service initialized (active modes: {[m.value for m in delivery_service.get_active_modes()]})"
        )
    except Exception as e:
        logger.warning(f"Failed initializing Delivery Service: {e}", exc_info=True)
        app.state.delivery_service = None

    # Demo data is loaded on-demand via POST /api/settings/demo-data/load
    # See: src/backend/src/data/demo_data.sql

    # Ensure SearchManager is initialized and index built
    try:
        from src.common.search_interfaces import SearchableAsset
        from src.controller.search_manager import SearchManager

        logger.info("Initializing SearchManager after data load (app.py)...")
        searchable_managers_instances = []
        for attr_name, manager_instance in list(getattr(app.state, "_state", {}).items()):
            try:
                if isinstance(manager_instance, SearchableAsset) and hasattr(
                    manager_instance, "get_search_index_items"
                ):
                    searchable_managers_instances.append(manager_instance)
            except Exception:
                continue
        app.state.search_manager = SearchManager(searchable_managers=searchable_managers_instances)
        app.state.search_manager.build_index()
        logger.info("Search index initialized and built from DB-backed managers (app.py).")
    except Exception as e:
        logger.error(f"Failed initializing or building search index in app.py: {e}", exc_info=True)

    logger.info("Application startup complete.")


# Application Shutdown Event
async def shutdown_event():
    logger.info("Running application shutdown event...")
    logger.info("Application shutdown complete.")


# --- FastAPI App Instantiation (AFTER defining lifecycle functions) ---

# Define paths
# STATIC_ASSETS_PATH = Path(__file__).parent.parent / "static"
logger.info(f"STATIC_ASSETS_PATH: {STATIC_ASSETS_PATH}")

# mimetypes.add_type('application/javascript', '.js')
# mimetypes.add_type('image/svg+xml', '.svg')
# mimetypes.add_type('image/png', '.png')

# Import version from package
from src import __version__

# Define API tags for Swagger UI ordering
# Grouped by feature category for logical organization
openapi_tags = [
    # Data Products - Core data lifecycle
    {"name": "Data Domains", "description": "Manage data domains for organizing data products"},
    {"name": "Teams", "description": "Manage teams and team members"},
    {"name": "Projects", "description": "Manage projects within teams"},
    {"name": "Tags", "description": "Manage tags and tag namespaces"},
    {"name": "Costs", "description": "Manage cost items and budgets"},
    {"name": "Datasets", "description": "Manage datasets and dataset instances"},
    {"name": "Data Contracts", "description": "Manage data contracts for data products"},
    {"name": "Data Products", "description": "Manage data products and subscriptions"},
    # Governance - Standards and approval workflows
    {"name": "Compliance", "description": "Manage compliance policies and runs"},
    {"name": "Approvals", "description": "Manage approval workflows"},
    {"name": "Process Workflows", "description": "Manage process workflows"},
    {"name": "Data Asset Reviews", "description": "Manage data asset review workflows"},
    # Business Glossary - Semantic models and ontologies
    {"name": "Semantic Models", "description": "Manage semantic models and ontologies"},
    {"name": "Semantic Links", "description": "Manage semantic links between entities"},
    # Operations - Monitoring and technical management
    {"name": "Estates", "description": "Manage data estates"},
    {"name": "Master Data Management", "description": "Master data management features"},
    {"name": "Catalog Commander", "description": "Dual-pane catalog explorer"},
    # Security - Access control and security features
    {"name": "Security Features", "description": "Advanced security features"},
    {"name": "Entitlements", "description": "Manage entitlements and personas"},
    {"name": "Entitlements Sync", "description": "Sync entitlements from external sources"},
    {"name": "Access Grants", "description": "Manage time-limited access grants"},
    # System - Utilities, configuration, auxiliary services
    {"name": "Metadata", "description": "Manage metadata attachments"},
    {"name": "Workspace", "description": "Workspace asset operations"},
    {"name": "Comments", "description": "Manage comments and discussions"},
    {"name": "Notifications", "description": "Manage user notifications"},
    {"name": "Search", "description": "Search across all assets"},
    {"name": "LLM Search", "description": "AI-powered search"},
    {"name": "Jobs", "description": "Manage background jobs and workflows"},
    {"name": "User", "description": "User information and permissions"},
    {"name": "Audit Trail", "description": "View audit trail logs"},
    {"name": "Change Log", "description": "View change history"},
    {"name": "MCP Server", "description": "Model Context Protocol server"},
    {"name": "MCP Tokens", "description": "Manage MCP access tokens"},
    {"name": "Self Service", "description": "Self-service data product creation"},
    {"name": "Settings", "description": "Application settings and configuration"},
]

# Create single FastAPI app with settings dependency
app = FastAPI(
    title="Ontos",
    description="A Databricks App for managing data products, contracts, and more",
    version=__version__,
    dependencies=[Depends(get_settings)],
    on_startup=[startup_event],
    on_shutdown=[shutdown_event],
    openapi_tags=openapi_tags,
)

# Configure CORS
origins = [
    "http://localhost:3000",
    "http://localhost:8000",
    "http://localhost:8001",
    "http://localhost:5173",
    "http://localhost:5174",
    "http://localhost:5175",
    "http://0.0.0.0:5173",
    "http://0.0.0.0:5174",
    "http://0.0.0.0:5175",
]
app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Add custom middleware
app.add_middleware(ErrorHandlingMiddleware)
app.add_middleware(LoggingMiddleware)

# Mount static files for the React application (skip in test mode)
if not os.environ.get("TESTING"):
    app.mount("/static", StaticFiles(directory=STATIC_ASSETS_PATH, html=True), name="static")

# Data Products - Core data lifecycle
data_domains_routes.register_routes(app)
teams_routes.register_routes(app)
projects_routes.register_routes(app)
tags_routes.register_routes(app)
costs_routes.register_routes(app)
datasets_routes.register_routes(app)
data_contracts_routes.register_routes(app)
data_product_routes.register_routes(app)
from src.routes import approvals_routes

approvals_routes.register_routes(app)

# Governance - Standards and approval workflows
semantic_models_routes.register_routes(app)
semantic_links_routes.register_routes(app)
data_asset_reviews_routes.register_routes(app)
data_catalog_routes.register_routes(app)

# Operations - Monitoring and technical management
compliance_routes.register_routes(app)
estate_manager_routes.register_routes(app)
mdm_routes.register_routes(app)
catalog_commander_routes.register_routes(app)

# Security - Access control and security features
security_features_routes.register_routes(app)
entitlements_routes.register_routes(app)
entitlements_sync_routes.register_routes(app)
access_grants_routes.register_routes(app)

# System - Utilities, configuration, auxiliary services
metadata_routes.register_routes(app)
workspace_routes.register_routes(app)
comments_routes.register_routes(app)
notifications_routes.register_routes(app)
search_routes.register_routes(app)
llm_search_routes.register_routes(app)
jobs_routes.register_routes(app)
user_routes.register_routes(app)
audit_routes.register_routes(app)
change_log_routes.register_routes(app)
mcp_routes.register_routes(app)
mcp_tokens_routes.register_routes(app)
self_service_routes.register_routes(app)
graph_explorer_routes.register_routes(app)
workflows_routes.register_routes(app)
settings_routes.register_routes(app)


# Define other specific API routes BEFORE the catch-all
@app.get("/api/time")
async def get_current_time():
    """Get the current time (for testing purposes mostly)"""
    return {"time": time.time()}


@app.get("/api/cache-version")
async def get_cache_version():
    """Get the server cache version for client-side cache invalidation"""
    return {"version": SERVER_STARTUP_TIME, "timestamp": int(time.time())}


@app.get("/api/version")
async def get_app_version():
    """Get the application version and server start time"""
    return {"version": __version__, "startTime": SERVER_STARTUP_TIME, "timestamp": int(time.time())}


# Define the SPA catch-all route LAST (skip in test mode)
if not os.environ.get("TESTING"):

    @app.get("/{full_path:path}")
    def serve_spa(full_path: str):
        # Only catch routes that aren't API routes, static files, or API docs
        # This check might be redundant now due to ordering, but safe to keep
        if (
            not full_path.startswith("api/")
            and not full_path.startswith("static/")
            and full_path not in ["docs", "redoc", "openapi.json"]
        ):
            # Ensure the path exists before serving
            spa_index = STATIC_ASSETS_PATH / "index.html"
            if spa_index.is_file():
                return FileResponse(spa_index, media_type="text/html")
            else:
                # Optional: Return a 404 or a simple HTML message if index.html is missing
                logger.error(f"SPA index.html not found at {spa_index}")
                return HTMLResponse(
                    content="<html><body>Frontend not built or index.html missing.</body></html>",
                    status_code=404,
                )
        # If it starts with api/ or static/ but wasn't handled by a router/StaticFiles,
        # FastAPI will return its default 404 Not Found, which is correct.
        # No explicit return needed here for that case.


logger.info("All routes registered.")

if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8000)
