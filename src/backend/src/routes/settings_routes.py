from typing import List, Dict, Any, Optional
import uuid
from datetime import datetime

from databricks.sdk import WorkspaceClient
from fastapi import APIRouter, Depends, HTTPException, status, Body, Request, BackgroundTasks, Query
from sqlalchemy.orm import Session

from ..common.workspace_client import get_workspace_client
from ..controller.settings_manager import SettingsManager
from ..models.settings import AppRole, AppRoleCreate, JobCluster
from ..models.search_config import SearchConfig, SearchConfigResponse, SearchConfigUpdate
from ..common.database import get_db
from ..common.dependencies import (
    get_settings_manager,
    get_notifications_manager,
    get_change_log_manager,
    get_search_manager,
    AuditManagerDep,
    AuditCurrentUserDep,
    DBSessionDep,
)
from ..common.authorization import get_user_details_from_sdk
from ..common.manager_dependencies import get_auth_manager
from ..controller.authorization_manager import AuthorizationManager
from ..models.users import UserInfo
from ..models.settings import HandleRoleRequest
from ..models.notifications import Notification, NotificationType
from ..controller.notifications_manager import NotificationsManager
from ..common.config import get_settings
from ..common.sanitization import sanitize_markdown_input
from ..common.search_config_loader import get_search_config_loader
from ..common.authorization import PermissionChecker
from ..common.features import FeatureAccessLevel

# Configure logging
from src.common.logging import get_logger
logger = get_logger(__name__)


router = APIRouter(prefix="/api", tags=["Settings"])

SETTINGS_FEATURE_ID = "settings" # Define a feature ID for settings
ROLE_NOT_FOUND = "Role not found"

@router.get('/settings')
async def get_settings_route(
    manager: SettingsManager = Depends(get_settings_manager),
    _: bool = Depends(PermissionChecker('settings-general', FeatureAccessLevel.READ_ONLY)),
):
    """Get all settings including available job clusters"""
    try:
        settings_data = manager.get_settings() # Renamed variable to avoid conflict
        return settings_data
    except Exception as e:
        logger.error("Error getting settings", exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to get settings")

@router.put('/settings')
async def update_settings(
    request: Request,
    background_tasks: BackgroundTasks,
    db: DBSessionDep,
    audit_manager: AuditManagerDep,
    current_user: AuditCurrentUserDep,
    settings_payload: dict, # Renamed to avoid conflict with module
    manager: SettingsManager = Depends(get_settings_manager),
    _: bool = Depends(PermissionChecker('settings-general', FeatureAccessLevel.READ_WRITE)),
):
    """Update settings"""
    success = False
    details = {}
    try:
        logger.info(f"Received settings update request: {settings_payload}")
        logger.info(f"job_cluster_id in payload: {settings_payload.get('job_cluster_id')}")

        # Track what settings changed
        if 'job_cluster_id' in settings_payload:
            details['job_cluster_id'] = settings_payload.get('job_cluster_id')
        if 'sync_enabled' in settings_payload:
            details['sync_enabled'] = settings_payload.get('sync_enabled')
        if 'sync_repository' in settings_payload:
            details['sync_repository'] = settings_payload.get('sync_repository')
        if 'enabled_jobs' in settings_payload:
            details['enabled_jobs'] = settings_payload.get('enabled_jobs')

        updated = manager.update_settings(settings_payload)
        success = True
        return updated.to_dict()
    except Exception as e:
        logger.error("Error updating settings", exc_info=True)
        details['exception'] = str(e)
        raise HTTPException(status_code=500, detail="Failed to update settings")
    finally:
        background_tasks.add_task(
            audit_manager.log_action_background,
            username=current_user.username,
            ip_address=request.client.host if request.client else None,
            feature=SETTINGS_FEATURE_ID,
            action="UPDATE",
            success=success,
            details=details
        )

@router.get('/settings/llm')
async def get_llm_config():
    """Get LLM configuration (publicly accessible for UI)"""
    try:
        app_settings = get_settings()
        return {
            "enabled": app_settings.LLM_ENABLED,
            "endpoint": app_settings.LLM_ENDPOINT,
            "disclaimer_text": sanitize_markdown_input(app_settings.LLM_DISCLAIMER_TEXT) if app_settings.LLM_DISCLAIMER_TEXT else None,
            # Do not expose system_prompt or injection_check_prompt to frontend
        }
    except Exception as e:
        logger.error("Error getting LLM config", exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to get LLM config")


@router.get('/settings/ui-customization')
async def get_ui_customization():
    """Get UI customization settings (publicly accessible for UI theming and branding).
    
    Returns settings for:
    - i18n_enabled: Whether internationalization is enabled (disable forces English)
    - custom_logo_url: URL to custom logo image
    - about_content: Custom Markdown content for About page
    - custom_css: Custom CSS to inject into the app
    """
    try:
        app_settings = get_settings()
        return {
            "i18n_enabled": app_settings.UI_I18N_ENABLED,
            "custom_logo_url": app_settings.UI_CUSTOM_LOGO_URL,
            "about_content": sanitize_markdown_input(app_settings.UI_ABOUT_CONTENT) if app_settings.UI_ABOUT_CONTENT else None,
            "custom_css": app_settings.UI_CUSTOM_CSS,
        }
    except Exception as e:
        logger.error("Error getting UI customization settings", exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to get UI customization settings")


@router.get('/settings/health')
async def health_check(manager: SettingsManager = Depends(get_settings_manager)):
    """Check if the settings API is healthy"""
    try:
        manager.list_available_workflows()
        logger.info("Workflows health check successful")
        return {"status": "healthy"}
    except Exception as e:
        error_msg = f"Workflows health check failed: {e!s}"
        logger.error(error_msg)
        raise HTTPException(status_code=500, detail=error_msg)

@router.get('/settings/job-clusters', response_model=List[JobCluster])
async def list_job_clusters(manager: SettingsManager = Depends(get_settings_manager)):
    """List all available job clusters"""
    try:
        return manager.get_job_clusters()
    except Exception as e:
        logger.error("Error fetching job clusters", exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to fetch job clusters")

# --- RBAC Routes ---

@router.get("/settings/features", response_model=Dict[str, Dict[str, Any]])
async def get_features_config(manager: SettingsManager = Depends(get_settings_manager)):
    """Get the application feature configuration including allowed access levels."""
    try:
        features = manager.get_features_with_access_levels()
        return features
    except Exception as e:
        logger.error("Error getting features configuration", exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to get features configuration")

@router.get("/settings/roles", response_model=List[AppRole])
async def list_roles(
    manager: SettingsManager = Depends(get_settings_manager),
    user_details: UserInfo = Depends(get_user_details_from_sdk),
    auth_manager: AuthorizationManager = Depends(get_auth_manager),
):
    """List application roles.

    Ontos admins (members of an AppRole with ``is_admin=True``) receive the
    full role catalog — required for the admin role-switcher impersonation
    path and for Settings admin UI. Non-admins receive only roles whose
    ``assigned_groups`` intersect their own groups (case-insensitive); this
    is the set they may legitimately switch to via the membership-scoped
    role switcher, and avoids leaking the full role catalog (see #404).
    """
    try:
        roles = manager.list_app_roles()
        if auth_manager.is_user_ontos_admin(user_details.groups):
            return roles

        user_group_set = {(g or '').lower() for g in (user_details.groups or [])}
        if not user_group_set:
            return []
        scoped: List[AppRole] = []
        for role in roles:
            role_groups = {(g or '').lower() for g in (role.assigned_groups or [])}
            if role_groups and role_groups.intersection(user_group_set):
                scoped.append(role)
        return scoped
    except Exception as e:
        logger.error("Error listing roles", exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to list roles")

@router.get("/settings/roles/summary", response_model=List[dict])
async def list_roles_summary(manager: SettingsManager = Depends(get_settings_manager)):
    """Get a simple summary list of role names for dropdowns/selection."""
    try:
        roles = manager.list_app_roles()
        return [{"name": role.name} for role in roles]
    except Exception as e:
        logger.error("Error listing roles summary", exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to list roles summary")

@router.post("/settings/roles", response_model=AppRole, status_code=status.HTTP_201_CREATED)
async def create_role(
    request: Request,
    background_tasks: BackgroundTasks,
    db: DBSessionDep,
    audit_manager: AuditManagerDep,
    current_user: AuditCurrentUserDep,
    role_data: AppRoleCreate = Body(..., embed=False),
    manager: SettingsManager = Depends(get_settings_manager),
    _: bool = Depends(PermissionChecker('settings-roles', FeatureAccessLevel.ADMIN)),
):
    """Create a new application role."""
    success = False
    details = {"role_name": role_data.name}
    try:
        # Delivery handled via _queue_role_delivery in manager
        created_role = manager.create_app_role(
            role=role_data,
            user=current_user.email if current_user else None,
            background_tasks=background_tasks,
        )
        success = True
        if created_role and hasattr(created_role, 'id'):
            details["created_role_id"] = str(created_role.id)
        
        return created_role
    except ValueError as e:
        logger.warning("Validation error creating role '%s': %s", role_data.name, e)
        details["exception"] = str(e)
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid role data")
    except Exception as e:
        logger.error("Error creating role '%s'", role_data.name, exc_info=True)
        details["exception"] = str(e)
        raise HTTPException(status_code=500, detail="Failed to create role")
    finally:
        background_tasks.add_task(
            audit_manager.log_action_background,
            username=current_user.username,
            ip_address=request.client.host if request.client else None,
            feature=SETTINGS_FEATURE_ID,
            action="CREATE",
            success=success,
            details=details
        )

@router.get("/settings/roles/{role_id}", response_model=AppRole)
async def get_role(
    role_id: str,
    manager: SettingsManager = Depends(get_settings_manager)
):
    """Get a specific application role by ID."""
    try:
        role = manager.get_app_role(role_id)
        if role is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=ROLE_NOT_FOUND)
        return role
    except Exception as e:
        logger.error("Error getting role %s", role_id, exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to get role")

@router.put("/settings/roles/{role_id}", response_model=AppRole)
async def update_role(
    role_id: str,
    request: Request,
    background_tasks: BackgroundTasks,
    db: DBSessionDep,
    audit_manager: AuditManagerDep,
    current_user: AuditCurrentUserDep,
    role_data: AppRole = Body(..., embed=False),
    manager: SettingsManager = Depends(get_settings_manager),
    _: bool = Depends(PermissionChecker('settings-roles', FeatureAccessLevel.ADMIN)),
):
    """Update an existing application role."""
    success = False
    details = {"role_id": role_id, "role_name": role_data.name}
    try:
        # Delivery handled via _queue_role_delivery in manager
        updated_role = manager.update_app_role(
            role_id,
            role_data,
            user=current_user.email if current_user else None,
            background_tasks=background_tasks,
        )
        if updated_role is None:
            details["exception"] = ROLE_NOT_FOUND
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=ROLE_NOT_FOUND)
        success = True
        
        return updated_role
    except ValueError as e:
        logger.warning("Validation error updating role %s: %s", role_id, e)
        details["exception"] = str(e)
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid role data")
    except HTTPException:
        raise
    except Exception as e:
        logger.error("Error updating role %s", role_id, exc_info=True)
        details["exception"] = str(e)
        raise HTTPException(status_code=500, detail="Failed to update role")
    finally:
        background_tasks.add_task(
            audit_manager.log_action_background,
            username=current_user.username,
            ip_address=request.client.host if request.client else None,
            feature=SETTINGS_FEATURE_ID,
            action="UPDATE",
            success=success,
            details=details
        )

@router.delete("/settings/roles/{role_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_role(
    role_id: str,
    request: Request,
    background_tasks: BackgroundTasks,
    db: DBSessionDep,
    audit_manager: AuditManagerDep,
    current_user: AuditCurrentUserDep,
    manager: SettingsManager = Depends(get_settings_manager),
    _: bool = Depends(PermissionChecker('settings-roles', FeatureAccessLevel.ADMIN)),
):
    """Delete an application role."""
    success = False
    details = {"deleted_role_id": role_id}
    try:
        deleted = manager.delete_app_role(role_id)
        if not deleted:
            details["exception"] = ROLE_NOT_FOUND
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=ROLE_NOT_FOUND)
        success = True
        return None # Return None for 204
    except ValueError as e: # Catch potential error like deleting admin role
        logger.warning("Error deleting role %s: %s", role_id, e)
        details["exception"] = str(e)
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Cannot delete role")
    except HTTPException:
        raise
    except Exception as e:
        logger.error("Error deleting role %s", role_id, exc_info=True)
        details["exception"] = str(e)
        raise HTTPException(status_code=500, detail="Failed to delete role")
    finally:
        background_tasks.add_task(
            audit_manager.log_action_background,
            username=current_user.username,
            ip_address=request.client.host if request.client else None,
            feature=SETTINGS_FEATURE_ID,
            action="DELETE",
            success=success,
            details=details
        )

# --- Role Request Handling ---
@router.post("/settings/roles/handle-request", status_code=status.HTTP_200_OK)
async def handle_role_request_decision(
    request: Request,
    db: DBSessionDep,
    audit_manager: AuditManagerDep,
    current_user: AuditCurrentUserDep,
    request_data: HandleRoleRequest = Body(...),
    settings_manager: SettingsManager = Depends(get_settings_manager),
    notifications_manager: NotificationsManager = Depends(get_notifications_manager),
    change_log_manager = Depends(get_change_log_manager),
    _: bool = Depends(PermissionChecker('settings-roles', FeatureAccessLevel.ADMIN)),
):
    """Handles the admin decision (approve/deny) for a role access request."""
    try:
        # Delegate to manager
        result = settings_manager.handle_role_request_decision(
            db=db,
            request_data=request_data,
            notifications_manager=notifications_manager,
            change_log_manager=change_log_manager
        )
        
        audit_manager.log_action(
            db=db,
            username=current_user.username if current_user else 'unknown',
            ip_address=request.client.host if request.client else None,
            feature='settings',
            action='HANDLE_ROLE_REQUEST',
            success=True,
            details={'role_id': request_data.role_id, 'approved': request_data.approved, 'user_email': request_data.requester_email}
        )
        
        return result
    except ValueError as e:
        # Role not found
        logger.error(f"Role validation error: {e}")
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        logger.error(f"Error handling role request decision: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to process role request decision due to an internal error.")

# --- Demo Data Loading ---

# Allowed presets — one self-contained SQL file per preset.
DEMO_DATA_PRESETS = ("retail", "hls", "fsi", "mfg", "auto")


@router.post("/settings/demo-data/load", status_code=status.HTTP_200_OK)
async def load_demo_data(
    request: Request,
    background_tasks: BackgroundTasks,
    db: DBSessionDep,
    audit_manager: AuditManagerDep,
    current_user: AuditCurrentUserDep,
    manager: SettingsManager = Depends(get_settings_manager),
    preset: str = Query(
        default="retail",
        description=(
            "Demo preset to load. Each preset is a fully self-contained vertical demo "
            "(no implicit content from other packs). Allowed values: "
            f"{', '.join(DEMO_DATA_PRESETS)}. Defaults to 'retail'."
        ),
    ),
):
    """
    Load a single demo preset from its self-contained SQL file.

    Each preset maps to exactly one SQL file (`demo_data_{preset}.sql`) and is
    designed to be loaded standalone on an empty database. Loading a preset does
    not pull in content from any other preset.

    Example: POST /api/settings/demo-data/load?preset=hls

    The SQL uses ON CONFLICT DO NOTHING to make re-runs and clear+reload safe.
    """
    success = False
    preset_slug = (preset or "").strip().lower()
    details: Dict[str, Any] = {"action": "load_demo_data", "preset": preset_slug}

    if preset_slug not in DEMO_DATA_PRESETS:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                f"Invalid preset '{preset}'. Allowed values: "
                f"{', '.join(DEMO_DATA_PRESETS)}."
            ),
        )

    try:
        from pathlib import Path
        from sqlalchemy import text

        data_dir = Path(__file__).parent.parent / "data"
        sql_file: Path = data_dir / f"demo_data_{preset_slug}.sql"

        if not sql_file.exists():
            details["exception"] = f"{sql_file.name} not found"
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Demo data SQL file not found: {sql_file.name}",
            )

        connection = db.connection()
        sql_content = sql_file.read_text(encoding="utf-8")

        statements = []
        current_statement = []
        in_dollar_quote = False

        for line in sql_content.split('\n'):
            stripped = line.strip()

            if not stripped or stripped.startswith('--'):
                if current_statement:
                    current_statement.append(line)
                continue

            if "E'" in line or "$$" in line:
                in_dollar_quote = not in_dollar_quote if "$$" in line else in_dollar_quote

            current_statement.append(line)

            if stripped.endswith(';') and not in_dollar_quote:
                full_statement = '\n'.join(current_statement).strip()
                if full_statement and not full_statement.startswith('--'):
                    if full_statement.upper() not in ('BEGIN;', 'COMMIT;'):
                        statements.append(full_statement)
                current_statement = []

        executed_count = 0
        for stmt in statements:
            if stmt.strip():
                try:
                    nested = connection.begin_nested()
                    connection.execute(text(stmt))
                    nested.commit()
                    executed_count += 1
                except Exception as stmt_error:
                    nested.rollback()
                    logger.warning(
                        f"Statement execution warning ({sql_file.name}): {stmt_error}"
                    )

        db.commit()

        success = True
        details["statements_executed"] = executed_count
        details["file"] = sql_file.name

        logger.info(
            f"Demo data loaded successfully. Preset='{preset_slug}', "
            f"file='{sql_file.name}', statements={executed_count}."
        )

        return {
            "status": "success",
            "message": (
                f"Demo data loaded successfully (preset='{preset_slug}'). "
                f"Executed {executed_count} SQL statements from {sql_file.name}."
            ),
            "preset": preset_slug,
            "file": sql_file.name,
            "statements_executed": executed_count,
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error("Error loading demo data", exc_info=True)
        details["exception"] = str(e)
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to load demo data: {str(e)}"
        )
    finally:
        background_tasks.add_task(
            audit_manager.log_action_background,
            username=current_user.username,
            ip_address=request.client.host if request.client else None,
            feature=SETTINGS_FEATURE_ID,
            action="LOAD_DEMO_DATA",
            success=success,
            details=details
        )


@router.delete("/settings/demo-data", status_code=status.HTTP_200_OK)
async def clear_demo_data(
    request: Request,
    background_tasks: BackgroundTasks,
    db: DBSessionDep,
    audit_manager: AuditManagerDep,
    current_user: AuditCurrentUserDep,
    manager: SettingsManager = Depends(get_settings_manager)
):
    """
    Clear all demo data from the database.
    
    This endpoint is Admin-only and removes all demo data that was loaded
    via the /settings/demo-data/load endpoint.
    
    WARNING: This will delete all data with IDs matching the demo data patterns.
    """
    success = False
    details = {"action": "clear_demo_data"}
    
    try:
        from sqlalchemy import text
        
        # Delete in reverse dependency order
        # UUID patterns use type codes in first 3 hex chars (see demo_data_retail.sql for mapping)
        # Pattern: {type:3}{seq:5}-{dataset:4}-4000-8000-...
        # Dataset segments: 0000=retail, 0001=hls, 0002=fsi, 0003=mfg, 0004=auto.
        # The LIKE patterns below match by type-code prefix only, so they remove rows
        # from every preset (the dataset segment is in chars 9-12, not the prefix).
        delete_statements = [
            # Suggested quality checks (02e%) - before data_profiling_runs
            "DELETE FROM suggested_quality_checks WHERE id::text LIKE '02e%'",
            
            # Data profiling runs (02d%)
            "DELETE FROM data_profiling_runs WHERE id::text LIKE '02d%'",
            
            # Comments/ratings (02c%)
            "DELETE FROM comments WHERE id::text LIKE '02c%'",
            
            # Workflow steps (02b%, 02e%) - before process_workflows
            "DELETE FROM workflow_steps WHERE id::text LIKE '02b%'",
            "DELETE FROM workflow_steps WHERE id::text LIKE '02e%'",
            
            # Process workflows (02a%, 02d%)
            "DELETE FROM process_workflows WHERE id::text LIKE '02a%'",
            "DELETE FROM process_workflows WHERE id::text LIKE '02d%'",
            
            # Entity tag associations (029%) - all entity types, before tags
            "DELETE FROM entity_tag_associations WHERE id::text LIKE '029%'",
            
            # Tag namespace permissions (028%) - before tag_namespaces
            "DELETE FROM tag_namespace_permissions WHERE id::text LIKE '028%'",
            
            # Tags (027%) - before tag_namespaces
            "DELETE FROM tags WHERE id::text LIKE '027%'",
            
            # Tag namespaces (0260%) - note: uses 02601xx pattern to avoid collision with dataset_subscriptions
            "DELETE FROM tag_namespaces WHERE id::text LIKE '0260%'",
            
            # RDF triples (020%, 030%)
            "DELETE FROM rdf_triples WHERE id::text LIKE '020%'",
            "DELETE FROM rdf_triples WHERE id::text LIKE '030%'",
            
            # Entity subscriptions (022%, 0260%) — migrated from dataset_subscriptions
            "DELETE FROM entity_subscriptions WHERE id::text LIKE '022%'",
            "DELETE FROM entity_subscriptions WHERE id::text LIKE '0260%'",
            
            # Entity relationships (0215%) — Dataset→Table/View/Contract
            "DELETE FROM entity_relationships WHERE id::text LIKE '0215%'",
            # Entity relationships (0f4%) — asset lineage/containment
            "DELETE FROM entity_relationships WHERE id::text LIKE '0f4%'",
            # Entity relationships (0fa%) — business lineage
            "DELETE FROM entity_relationships WHERE id::text LIKE '0fa%'",
            # Entity relationships (0f6%) — hasColumn
            "DELETE FROM entity_relationships WHERE id::text LIKE '0f6%'",
            
            # Physical assets (025%) — migrated from dataset_instances
            "DELETE FROM assets WHERE id::text LIKE '025%'",
            
            # Dataset assets (021%) — migrated from datasets table
            "DELETE FROM assets WHERE id::text LIKE '021%'",
            
            # Policy assets (0f1%)
            "DELETE FROM assets WHERE id::text LIKE '0f1%'",
            # General catalog assets (0f3%) — Tables, Views, Dashboards, Streams,
            # Patient Cohorts, ICSR cases, etc. (covers all preset packs).
            "DELETE FROM assets WHERE id::text LIKE '0f3%'",
            # Column assets (0f5%)
            "DELETE FROM assets WHERE id::text LIKE '0f5%'",
            # Business Term assets (0f7%)
            "DELETE FROM assets WHERE id::text LIKE '0f7%'",
            # Logical Entity/Attribute assets (0f8%)
            "DELETE FROM assets WHERE id::text LIKE '0f8%'",
            # Delivery Channel assets (0f9%)
            "DELETE FROM assets WHERE id::text LIKE '0f9%'",
            # Business Owners — must be removed before business_roles because
            # of the role_id FK. Retail uses the 0f6% prefix; the vertical
            # packs (hls/fsi/mfg/auto) use 0fb%.
            "DELETE FROM business_owners WHERE id::text LIKE '0f6%'",
            "DELETE FROM business_owners WHERE id::text LIKE '0fb%'",
            # Vertical-specific demo asset types (0f2%, is_system=false)
            "DELETE FROM asset_types WHERE id::text LIKE '0f2%' AND is_system = false AND created_by = 'system@demo'",
            # Demo-inserted business_roles and delivery_methods — scoped by
            # created_by to avoid touching app-seeded reference rows.
            "DELETE FROM business_roles WHERE id::text LIKE '0f0%' AND created_by = 'system@demo'",
            "DELETE FROM delivery_methods WHERE id::text LIKE '0f4%' AND created_by = 'system@demo'",
            # Note: legacy dataset_subscriptions / dataset_custom_properties /
            # dataset_instances / datasets tables were dropped by migration
            # c1_drop_legacy_dataset_tables.py — no DELETEs needed.
            
            # Data contract servers (srv pattern for server IDs)
            "DELETE FROM data_contract_servers WHERE id::text LIKE 'srv%'",
            
            # Metadata (018=document, 017=link, 016=rich_text)
            "DELETE FROM document_metadata WHERE id::text LIKE '018%'",
            "DELETE FROM link_metadata WHERE id::text LIKE '017%'",
            "DELETE FROM rich_text_metadata WHERE id::text LIKE '016%'",
            
            # MDM (01c=match_candidates, 01b=match_runs, 01a=source_links, 019=configs)
            "DELETE FROM mdm_match_candidates WHERE id::text LIKE '01c%'",
            "DELETE FROM mdm_match_runs WHERE id::text LIKE '01b%'",
            "DELETE FROM mdm_source_links WHERE id::text LIKE '01a%'",
            "DELETE FROM mdm_configs WHERE id::text LIKE '019%'",
            
            # Authoritative Definitions (01f=property, 01e=schema_object, 01d=contract)
            "DELETE FROM data_contract_schema_property_authoritative_definitions WHERE id::text LIKE '01f%'",
            "DELETE FROM data_contract_schema_object_authoritative_definitions WHERE id::text LIKE '01e%'",
            "DELETE FROM data_contract_authoritative_definitions WHERE id::text LIKE '01d%'",
            
            # Semantic Links (015)
            "DELETE FROM entity_semantic_links WHERE id::text LIKE '015%'",
            
            # Cost Items (014)
            "DELETE FROM cost_items WHERE id::text LIKE '014%'",
            
            # Compliance (013=results, 012=runs, 011=policies)
            "DELETE FROM compliance_results WHERE id::text LIKE '013%'",
            "DELETE FROM compliance_runs WHERE id::text LIKE '012%'",
            "DELETE FROM compliance_policies WHERE id::text LIKE '011%'",
            
            # Notifications (010)
            "DELETE FROM notifications WHERE id::text LIKE '010%'",
            
            # Reviews (00f=reviewed_assets, 00e=requests)
            "DELETE FROM reviewed_assets WHERE id::text LIKE '00f%'",
            "DELETE FROM data_asset_review_requests WHERE id::text LIKE '00e%'",
            
            # Data Products (00d=team_members, 00c=teams, 00b=support, 00a=input, 009=output, 008=desc, 007=products)
            "DELETE FROM data_product_team_members WHERE id::text LIKE '00d%'",
            "DELETE FROM data_product_teams WHERE id::text LIKE '00c%'",
            "DELETE FROM data_product_support_channels WHERE id::text LIKE '00b%'",
            "DELETE FROM data_product_input_ports WHERE id::text LIKE '00a%'",
            "DELETE FROM data_product_output_ports WHERE id::text LIKE '009%'",
            "DELETE FROM data_product_descriptions WHERE id::text LIKE '008%'",
            "DELETE FROM data_products WHERE id::text LIKE '007%'",
            
            # Data Contracts (006=properties, 005=schema_objects, 004=contracts)
            "DELETE FROM data_contract_schema_properties WHERE id::text LIKE '006%'",
            "DELETE FROM data_contract_schema_objects WHERE id::text LIKE '005%'",
            "DELETE FROM data_contracts WHERE id::text LIKE '004%'",
            
            # Projects (003)
            "DELETE FROM project_teams WHERE project_id::text LIKE '003%'",
            "DELETE FROM projects WHERE id::text LIKE '003%'",
            
            # Teams (002=members, 001=teams)
            "DELETE FROM team_members WHERE id::text LIKE '002%'",
            "DELETE FROM teams WHERE id::text LIKE '001%'",
            
            # Domains (000)
            "DELETE FROM data_domains WHERE id::text LIKE '000%'",
        ]
        
        # Wrap each statement in a SAVEPOINT so that a single failing
        # DELETE (e.g. against a table dropped by a later migration) does
        # not poison the surrounding transaction and silently abort all
        # subsequent deletes. Accumulate rowcounts per table since several
        # patterns target the same table (e.g. entity_relationships).
        deleted_counts: Dict[str, int] = {}
        skipped: List[Dict[str, str]] = []
        for stmt in delete_statements:
            table_name = stmt.split("FROM ")[1].split(" ")[0]
            try:
                with db.begin_nested():
                    result = db.execute(text(stmt))
                rowcount = result.rowcount or 0
                if rowcount > 0:
                    deleted_counts[table_name] = deleted_counts.get(table_name, 0) + rowcount
            except Exception as e:
                err_short = str(e).splitlines()[0][:200]
                logger.warning(
                    f"Delete statement FAILED ({table_name}): {err_short} | stmt={stmt}"
                )
                skipped.append({
                    "table": table_name,
                    "statement": stmt,
                    "error": err_short,
                })
        
        db.commit()

        success = True
        details["deleted_counts"] = deleted_counts
        details["skipped"] = skipped

        total_deleted = sum(deleted_counts.values())
        skipped_msg = f", {len(skipped)} statements skipped" if skipped else ""
        logger.info(f"Demo data cleared. Deleted {total_deleted} records{skipped_msg}.")

        return {
            "status": "success" if not skipped else "partial",
            "message": f"Demo data cleared. Deleted {total_deleted} records{skipped_msg}.",
            "deleted_counts": deleted_counts,
            "skipped": skipped,
        }
        
    except Exception as e:
        logger.error("Error clearing demo data", exc_info=True)
        details["exception"] = str(e)
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to clear demo data: {str(e)}"
        )
    finally:
        background_tasks.add_task(
            audit_manager.log_action_background,
            username=current_user.username,
            ip_address=request.client.host if request.client else None,
            feature=SETTINGS_FEATURE_ID,
            action="CLEAR_DEMO_DATA",
            success=success,
            details=details
        )


# --- Registration --- 

def register_routes(app):
    """Register routes with the app"""
    app.include_router(router)
    logger.info("Settings routes registered")


# --- Compliance mapping (object-type policies) ---

@router.get('/settings/compliance-mapping')
async def get_compliance_mapping():
    """Return compliance mapping YAML content as JSON.

    See structure documented in self_service_routes._load_compliance_mapping.
    """
    try:
        from src.common.config import get_config_manager
        cfg = get_config_manager()
        data = cfg.load_yaml('compliance_mapping.yaml')
        return data or {}
    except FileNotFoundError:
        return {}
    except Exception as e:
        logger.error("Error loading compliance mapping", exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to load compliance mapping")


@router.put('/settings/compliance-mapping')
async def save_compliance_mapping(
    request: Request,
    db: DBSessionDep,
    audit_manager: AuditManagerDep,
    current_user: AuditCurrentUserDep,
    payload: Dict[str, Any] = Body(...),
    manager: SettingsManager = Depends(get_settings_manager)
):
    """Persist compliance mapping to YAML."""
    try:
        from src.common.config import get_config_manager
        cfg = get_config_manager()
        cfg.save_yaml('compliance_mapping.yaml', payload)
        
        audit_manager.log_action(
            db=db,
            username=current_user.username if current_user else 'unknown',
            ip_address=request.client.host if request.client else None,
            feature='settings',
            action='SAVE_COMPLIANCE_MAPPING',
            success=True,
            details={}
        )
        
        return {"status": "ok"}
    except Exception as e:
        logger.error("Error saving compliance mapping", exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to save compliance mapping")


# --- Documentation System ---

@router.get('/user-docs')
async def list_available_docs(manager: SettingsManager = Depends(get_settings_manager)):
    """List all available user documentation files"""
    try:
        docs = manager.get_available_docs()
        # Return without the internal 'path' field
        result = {}
        for doc_key, doc_info in docs.items():
            entry = {
                "title": doc_info["title"],
                "description": doc_info["description"],
                "file": doc_info["file"]
            }
            # Include optional category field if present
            if "category" in doc_info:
                entry["category"] = doc_info["category"]
            result[doc_key] = entry
        return result
    except Exception as e:
        logger.error("Error listing documentation", exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to list documentation")

@router.get('/user-docs/{doc_name}')
async def get_documentation(doc_name: str, manager: SettingsManager = Depends(get_settings_manager)):
    """Serve a specific user documentation file by name"""
    try:
        return manager.get_documentation_content(doc_name)
    except ValueError as e:
        # Doc not found in registry
        logger.warning(f"Documentation not found: {e}")
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        logger.error("Error reading documentation '%s'", doc_name, exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to read documentation")

@router.get('/user-guide')
async def get_user_guide(manager: SettingsManager = Depends(get_settings_manager)):
    """Serve the USER-GUIDE.md content (alias for /user-docs/user-guide for backward compatibility)"""
    return await get_documentation("user-guide", manager)


# --- Database Schema ERD ---

@router.get('/database-schema')
async def get_database_schema(manager: SettingsManager = Depends(get_settings_manager)):
    """Extract database schema from SQLAlchemy models for ERD visualization"""
    try:
        return manager.extract_database_schema()
    except Exception as e:
        logger.error("Error extracting database schema", exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to extract database schema")


# --- Search Configuration ---

@router.get('/settings/search-config', response_model=SearchConfigResponse)
async def get_search_config(
    _: bool = Depends(PermissionChecker('settings-search', FeatureAccessLevel.READ_ONLY)),
):
    """
    Get the current search configuration.
    
    Returns the search configuration including:
    - Default field settings (title, description, tags)
    - Per-asset-type configurations
    - Ranking/sorting behavior
    """
    try:
        loader = get_search_config_loader()
        config = loader.load()
        return SearchConfigResponse.from_config(config)
    except Exception as e:
        logger.error("Error getting search config", exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to get search configuration")


@router.put('/settings/search-config', response_model=SearchConfigResponse)
async def update_search_config(
    request: Request,
    background_tasks: BackgroundTasks,
    db: DBSessionDep,
    audit_manager: AuditManagerDep,
    current_user: AuditCurrentUserDep,
    config_update: SearchConfigUpdate = Body(...),
    manager: SettingsManager = Depends(get_settings_manager),
    _: bool = Depends(PermissionChecker('settings-search', FeatureAccessLevel.ADMIN)),
):
    """
    Update the search configuration.
    
    Accepts partial updates - only provided fields will be updated.
    Requires Admin permissions.
    
    After updating, the search index should be rebuilt to apply changes.
    """
    success = False
    details = {"action": "update_search_config"}
    
    try:
        loader = get_search_config_loader()
        
        # Build updates dict from the Pydantic model
        updates = {}
        if config_update.defaults is not None:
            updates["defaults"] = {
                "fields": {
                    "title": _field_config_to_dict(config_update.defaults.fields.title),
                    "description": _field_config_to_dict(config_update.defaults.fields.description),
                    "tags": _field_config_to_dict(config_update.defaults.fields.tags),
                }
            }
        
        if config_update.asset_types is not None:
            updates["asset_types"] = {}
            for asset_type, asset_config in config_update.asset_types.items():
                asset_dict = {
                    "enabled": asset_config.enabled,
                    "inherit_defaults": asset_config.inherit_defaults,
                }
                if asset_config.fields:
                    asset_dict["fields"] = {
                        k: _field_config_to_dict(v) 
                        for k, v in asset_config.fields.items()
                    }
                if asset_config.extra_fields:
                    asset_dict["extra_fields"] = {
                        k: _field_config_to_dict(v) 
                        for k, v in asset_config.extra_fields.items()
                    }
                updates["asset_types"][asset_type] = asset_dict
        
        if config_update.ranking is not None:
            updates["ranking"] = {
                "primary_sort": config_update.ranking.primary_sort.value,
                "secondary_sort": config_update.ranking.secondary_sort.value,
                "tertiary_sort": config_update.ranking.tertiary_sort.value,
            }
        
        # Apply updates
        updated_config = loader.update(updates)
        
        success = True
        details["updated_sections"] = list(updates.keys())
        
        return SearchConfigResponse.from_config(updated_config)
        
    except ValueError as e:
        logger.warning("Validation error updating search config: %s", e)
        details["exception"] = str(e)
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    except Exception as e:
        logger.error("Error updating search config", exc_info=True)
        details["exception"] = str(e)
        raise HTTPException(status_code=500, detail="Failed to update search configuration")
    finally:
        background_tasks.add_task(
            audit_manager.log_action_background,
            username=current_user.username,
            ip_address=request.client.host if request.client else None,
            feature=SETTINGS_FEATURE_ID,
            action="UPDATE_SEARCH_CONFIG",
            success=success,
            details=details
        )


@router.post('/settings/search-config/rebuild-index', status_code=status.HTTP_200_OK)
async def rebuild_search_index(
    request: Request,
    background_tasks: BackgroundTasks,
    db: DBSessionDep,
    audit_manager: AuditManagerDep,
    current_user: AuditCurrentUserDep,
    manager: SettingsManager = Depends(get_settings_manager),
    _: bool = Depends(PermissionChecker('settings-search', FeatureAccessLevel.ADMIN)),
):
    """
    Rebuild the search index.
    
    This reloads the search configuration and rebuilds the entire search index
    from all registered searchable asset managers.
    
    Use this after updating the search configuration to apply changes.
    """
    success = False
    details = {"action": "rebuild_search_index"}
    
    try:
        search_manager = get_search_manager(request)
        if search_manager is None:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Search manager not available"
            )
        
        # Reload config and rebuild index
        search_manager.reload_config()
        search_manager.build_index()
        
        success = True
        details["index_size"] = len(search_manager.index)
        
        return {
            "status": "success",
            "message": f"Search index rebuilt with {len(search_manager.index)} items",
            "index_size": len(search_manager.index)
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error("Error rebuilding search index", exc_info=True)
        details["exception"] = str(e)
        raise HTTPException(status_code=500, detail="Failed to rebuild search index")
    finally:
        background_tasks.add_task(
            audit_manager.log_action_background,
            username=current_user.username,
            ip_address=request.client.host if request.client else None,
            feature=SETTINGS_FEATURE_ID,
            action="REBUILD_SEARCH_INDEX",
            success=success,
            details=details
        )


def _field_config_to_dict(field) -> dict:
    """Helper to convert FieldConfig to dict for loader."""
    from ..models.search_config import FieldConfig
    if isinstance(field, FieldConfig):
        result = {
            "indexed": field.indexed,
            "match_type": field.match_type.value,
            "priority": field.priority,
            "boost": field.boost,
        }
        if field.source:
            result["source"] = field.source
        return result
    return field


# --- Git Repository Management ---

@router.get('/settings/git/status')
async def get_git_status(
    include_diffs: bool = False,
    manager: SettingsManager = Depends(get_settings_manager),
    _: bool = Depends(PermissionChecker('settings-git', FeatureAccessLevel.READ_ONLY)),
):
    """Get the current status of the Git repository.
    
    Returns clone status, pending changes count, and optionally file diffs.
    
    Args:
        include_diffs: Whether to include file-level diffs in the response
    """
    try:
        from ..common.git import get_git_service
        git_service = get_git_service()
        status = git_service.get_status(include_diffs=include_diffs)
        return status.to_dict()
    except RuntimeError as e:
        # Git service not initialized
        return {
            "clone_status": "not_configured",
            "error_message": str(e)
        }
    except Exception as e:
        logger.error("Error getting Git status", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to get Git status: {str(e)}")


@router.post('/settings/git/clone', status_code=status.HTTP_200_OK)
async def clone_git_repository(
    request: Request,
    background_tasks: BackgroundTasks,
    db: DBSessionDep,
    audit_manager: AuditManagerDep,
    current_user: AuditCurrentUserDep,
    manager: SettingsManager = Depends(get_settings_manager),
    _: bool = Depends(PermissionChecker('settings-git', FeatureAccessLevel.READ_WRITE)),
):
    """Clone the Git repository to the UC Volume.
    
    This is an explicit admin action to initialize the Git repository.
    The repository will be cloned to {DATABRICKS_VOLUME}/git-export/.
    """
    success = False
    details = {"action": "clone_git_repository"}
    
    try:
        from ..common.git import get_git_service
        git_service = get_git_service()
        result = git_service.clone()
        
        if result.clone_status.value == "cloned":
            success = True
            details["volume_path"] = result.volume_path
            return result.to_dict()
        else:
            details["error"] = result.error_message
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=result.error_message or "Failed to clone repository"
            )
    except RuntimeError as e:
        details["exception"] = str(e)
        raise HTTPException(status_code=400, detail=str(e))
    except HTTPException:
        raise
    except Exception as e:
        logger.error("Error cloning Git repository", exc_info=True)
        details["exception"] = str(e)
        raise HTTPException(status_code=500, detail=f"Failed to clone repository: {str(e)}")
    finally:
        background_tasks.add_task(
            audit_manager.log_action_background,
            username=current_user.username,
            ip_address=request.client.host if request.client else None,
            feature=SETTINGS_FEATURE_ID,
            action="GIT_CLONE",
            success=success,
            details=details
        )


@router.post('/settings/git/pull', status_code=status.HTTP_200_OK)
async def pull_git_repository(
    request: Request,
    background_tasks: BackgroundTasks,
    db: DBSessionDep,
    audit_manager: AuditManagerDep,
    current_user: AuditCurrentUserDep,
    manager: SettingsManager = Depends(get_settings_manager),
    _: bool = Depends(PermissionChecker('settings-git', FeatureAccessLevel.READ_WRITE)),
):
    """Pull latest changes from the remote Git repository."""
    success = False
    details = {"action": "pull_git_repository"}
    
    try:
        from ..common.git import get_git_service
        git_service = get_git_service()
        result = git_service.pull()
        
        if result.error_message:
            details["error"] = result.error_message
            raise HTTPException(status_code=400, detail=result.error_message)
        
        success = True
        return result.to_dict()
    except RuntimeError as e:
        details["exception"] = str(e)
        raise HTTPException(status_code=400, detail=str(e))
    except HTTPException:
        raise
    except Exception as e:
        logger.error("Error pulling Git repository", exc_info=True)
        details["exception"] = str(e)
        raise HTTPException(status_code=500, detail=f"Failed to pull repository: {str(e)}")
    finally:
        background_tasks.add_task(
            audit_manager.log_action_background,
            username=current_user.username,
            ip_address=request.client.host if request.client else None,
            feature=SETTINGS_FEATURE_ID,
            action="GIT_PULL",
            success=success,
            details=details
        )


@router.get('/settings/git/diff')
async def get_git_diff(
    manager: SettingsManager = Depends(get_settings_manager),
    _: bool = Depends(PermissionChecker('settings-git', FeatureAccessLevel.READ_ONLY)),
):
    """Get detailed diff of all pending changes in the Git repository."""
    try:
        from ..common.git import get_git_service
        git_service = get_git_service()
        status = git_service.get_status(include_diffs=True)
        return {
            "pending_changes_count": status.pending_changes_count,
            "changed_files": [
                {
                    "path": f.path,
                    "change_type": f.change_type,
                    "diff": f.diff
                }
                for f in status.changed_files
            ]
        }
    except RuntimeError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error("Error getting Git diff", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to get diff: {str(e)}")


@router.post('/settings/git/push', status_code=status.HTTP_200_OK)
async def push_git_repository(
    request: Request,
    background_tasks: BackgroundTasks,
    db: DBSessionDep,
    audit_manager: AuditManagerDep,
    current_user: AuditCurrentUserDep,
    commit_message: Optional[str] = Body(None, embed=True),
    manager: SettingsManager = Depends(get_settings_manager),
    _: bool = Depends(PermissionChecker('settings-git', FeatureAccessLevel.READ_WRITE)),
):
    """Commit and push all pending changes to the remote Git repository.
    
    Args:
        commit_message: Optional commit message. Auto-generated if not provided.
    """
    success = False
    details = {"action": "push_git_repository"}
    
    try:
        from ..common.git import get_git_service
        git_service = get_git_service()
        result = git_service.commit_and_push(commit_message)
        
        if result.error_message and "No changes to commit" not in result.error_message:
            details["error"] = result.error_message
            raise HTTPException(status_code=400, detail=result.error_message)
        
        success = True
        details["commit_message"] = commit_message or "(auto-generated)"
        return result.to_dict()
    except RuntimeError as e:
        details["exception"] = str(e)
        raise HTTPException(status_code=400, detail=str(e))
    except HTTPException:
        raise
    except Exception as e:
        logger.error("Error pushing Git repository", exc_info=True)
        details["exception"] = str(e)
        raise HTTPException(status_code=500, detail=f"Failed to push repository: {str(e)}")
    finally:
        background_tasks.add_task(
            audit_manager.log_action_background,
            username=current_user.username,
            ip_address=request.client.host if request.client else None,
            feature=SETTINGS_FEATURE_ID,
            action="GIT_PUSH",
            success=success,
            details=details
        )


# --- Delivery Mode Management ---

@router.get('/settings/delivery/status')
async def get_delivery_status(
    manager: SettingsManager = Depends(get_settings_manager),
    _: bool = Depends(PermissionChecker('settings-delivery', FeatureAccessLevel.READ_ONLY)),
):
    """Get the current delivery mode configuration and status."""
    try:
        from ..controller.delivery_service import get_delivery_service
        delivery_service = get_delivery_service()
        active_modes = delivery_service.get_active_modes()
        return {
            "modes": {
                "direct": {
                    "enabled": manager._settings.DELIVERY_MODE_DIRECT,
                    "dry_run": manager._settings.DELIVERY_DIRECT_DRY_RUN,
                },
                "indirect": {
                    "enabled": manager._settings.DELIVERY_MODE_INDIRECT,
                },
                "manual": {
                    "enabled": manager._settings.DELIVERY_MODE_MANUAL,
                },
            },
            "active_modes": [m.value for m in active_modes],
        }
    except RuntimeError:
        # Delivery service not initialized
        return {
            "modes": {
                "direct": {"enabled": False, "dry_run": False},
                "indirect": {"enabled": False},
                "manual": {"enabled": True},
            },
            "active_modes": ["manual"],
        }


@router.get('/settings/delivery/pending')
async def get_pending_delivery_tasks(
    db: DBSessionDep,
    change_type: Optional[str] = None,
    notifications_manager = Depends(get_notifications_manager),
    _: bool = Depends(PermissionChecker('settings-delivery', FeatureAccessLevel.READ_ONLY)),
):
    """Get pending manual delivery tasks (notifications)."""
    try:
        pending = notifications_manager.get_pending_delivery_notifications(
            db=db,
            change_type=change_type
        )
        return {
            "count": len(pending),
            "tasks": [n.model_dump() for n in pending]
        }
    except Exception as e:
        logger.error("Error getting pending delivery tasks", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.post('/settings/delivery/complete/{notification_id}', status_code=status.HTTP_200_OK)
async def complete_delivery_task(
    notification_id: str,
    request: Request,
    background_tasks: BackgroundTasks,
    db: DBSessionDep,
    audit_manager: AuditManagerDep,
    current_user: AuditCurrentUserDep,
    notes: Optional[str] = Body(None, embed=True),
    notifications_manager = Depends(get_notifications_manager),
    _: bool = Depends(PermissionChecker('settings-delivery', FeatureAccessLevel.READ_WRITE)),
):
    """Mark a manual delivery task as completed.
    
    Args:
        notification_id: ID of the delivery notification to complete
        notes: Optional notes about the completion
    """
    success = False
    details = {"notification_id": notification_id}
    
    try:
        from ..controller.notifications_manager import NotificationNotFoundError
        
        result = notifications_manager.complete_delivery_notification(
            db=db,
            notification_id=notification_id,
            completed_by=current_user.username,
            notes=notes,
        )
        
        if result is None:
            raise HTTPException(status_code=404, detail="Notification not found")
        
        success = True
        details["completed_by"] = current_user.username
        return result.model_dump()
        
    except NotificationNotFoundError:
        raise HTTPException(status_code=404, detail="Notification not found")
    except HTTPException:
        raise
    except Exception as e:
        logger.error("Error completing delivery task", exc_info=True)
        details["exception"] = str(e)
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        background_tasks.add_task(
            audit_manager.log_action_background,
            username=current_user.username,
            ip_address=request.client.host if request.client else None,
            feature=SETTINGS_FEATURE_ID,
            action="DELIVERY_COMPLETE",
            success=success,
            details=details
        )


# ============================================================================
# Legacy connector config endpoints (DEPRECATED — use /api/connections instead)
# Kept for backward compatibility; will be removed in a future version.
# ============================================================================

@router.get('/settings/connectors')
async def list_connectors_legacy():
    """DEPRECATED: Use GET /api/connections instead."""
    from fastapi.responses import RedirectResponse
    return RedirectResponse(url="/api/connections", status_code=307)


@router.post('/settings/connectors/{connector_type}/test')
async def test_connector_legacy(connector_type: str):
    """DEPRECATED: Use POST /api/connections/{id}/test instead."""
    return {"error": "Deprecated. Use /api/connections/{id}/test with a connection ID."}
