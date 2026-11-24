from typing import Any, Dict, List, Optional, Tuple

from fastapi import APIRouter, Depends, HTTPException, Body, Request

from src.common.dependencies import (
    DBSessionDep,
    CurrentUserDep,
    AuditManagerDep,
    AuditCurrentUserDep,
)
from src.common.features import FeatureAccessLevel
from src.common.authorization import PermissionChecker
from src.common.config import get_settings, get_config_manager
from src.common.workspace_client import get_workspace_client
from src.common.logging import get_logger
from src.common.unity_catalog_utils import (
    sanitize_uc_identifier,
    ensure_catalog_exists,
    ensure_schema_exists,
    create_table_safe,
    ensure_catalog_and_schema_exist,
)
from src.controller.self_service_manager import (
    SandboxLocationNotAllowedError,
    SelfServiceManager,
)
from src.db_models.compliance import CompliancePolicyDb
from src.repositories.teams_repository import team_repo
from src.repositories.projects_repository import project_repo
from src.db_models.teams import TeamDb
from src.db_models.projects import ProjectDb
from src.controller.catalog_commander_manager import CatalogCommanderManager
from src.controller.data_contracts_manager import DataContractsManager
from src.repositories.data_contracts_repository import data_contract_repo
from src.common.workflow_triggers import get_trigger_registry, TriggerEvent
from src.models.process_workflows import TriggerType, EntityType, ExecutionStatus


logger = get_logger(__name__)

router = APIRouter(prefix="/api", tags=["Self Service"])

FEATURE_ID = "data-contracts"  # Reuse data-contracts feature for RW permission

# Initialize manager
self_service_manager = SelfServiceManager()


def _username_slug(email: Optional[str]) -> str:
    if not email:
        return "user"
    local = email.split("@")[0].lower()
    # Allow only lowercase letters, digits and underscores
    safe = []
    for ch in local:
        if ch.isalnum() or ch == '_':
            safe.append(ch)
        elif ch in ('.', '-', ' '):
            safe.append('_')
    slug = ''.join(safe).strip('_')
    return slug or "user"


def _is_sandbox_allowed(settings, catalog: str, schema: str) -> bool:
    try:
        if not settings.sandbox_enforce_allowlist:
            return True
        # Exact allowlist
        if catalog in (settings.sandbox_allowed_catalogs or []):
            return (schema in (settings.sandbox_allowed_schemas or []))
        # Prefix allowlist
        if any(catalog.startswith(pfx) for pfx in (settings.sandbox_allowed_catalog_prefixes or [])):
            return (schema in (settings.sandbox_allowed_schemas or []))
        return False
    except Exception:
        return False


def _load_compliance_mapping() -> Dict[str, Any]:
    """Load compliance mapping from YAML via ConfigManager.

    Expected YAML structure (example):
      catalog:
        policies: ["naming-conventions"]
        auto_fix: true
        required_tags:
          owner: from_user
      schema:
        policies: ["naming-conventions"]
      table:
        policies: ["naming-conventions"]
        auto_fix: true
        required_tags:
          project: from_project
    """
    try:
        cfg = get_config_manager()
        return cfg.load_yaml('compliance_mapping.yaml')
    except Exception:
        return {}




@router.post('/self-service/bootstrap')
async def bootstrap_self_service(
    db: DBSessionDep,
    current_user: CurrentUserDep,
    _: bool = Depends(PermissionChecker(FEATURE_ID, FeatureAccessLevel.READ_WRITE)),
):
    """Ensure user's personal Team and Project exist and return defaults including sandbox names.

    - Creates a team and project if missing
    - Returns suggested default UC catalog/schema
    """
    try:
        username_slug = _username_slug(current_user.email if current_user else None)
        team_name = f"team_{username_slug}"
        project_name = f"project_{username_slug}"

        # Ensure Team
        team: Optional[TeamDb] = team_repo.get_by_name(db, name=team_name)
        if not team:
            team = team_repo.create(db=db, obj_in={
                'name': team_name,
                'title': f"Personal Team for {current_user.email}",
                'description': "Auto-created personal team",
                'created_by': current_user.email,
                'updated_by': current_user.email,
            })

        # Ensure Project
        project: Optional[ProjectDb] = project_repo.get_by_name(db, name=project_name)
        if not project:
            project = project_repo.create(db=db, obj_in={
                'name': project_name,
                'title': f"Personal Project for {current_user.email}",
                'description': "Auto-created personal project",
                'owner_team_id': team.id if team else None,
                'project_type': 'PERSONAL',
                'created_by': current_user.email,
                'updated_by': current_user.email,
            })

        # Suggest default UC sandbox names
        settings = get_settings()
        default_catalog = f"user_{username_slug}"
        default_schema = settings.sandbox_default_schema or "sandbox"

        return {
            'team': {'id': team.id, 'name': team.name} if team else None,
            'project': {'id': project.id, 'name': project.name} if project else None,
            'defaults': {
                'catalog': default_catalog,
                'schema': default_schema,
            }
        }
    except Exception as e:
        logger.exception("Failed bootstrapping self-service")
        raise HTTPException(status_code=500, detail="Failed to bootstrap self-service")


def get_data_contracts_manager(request: Request) -> DataContractsManager:
    """Retrieves the DataContractsManager singleton from app.state."""
    manager = getattr(request.app.state, 'data_contracts_manager', None)
    if manager is None:
        raise HTTPException(status_code=500, detail="DataContractsManager not initialized")
    return manager


@router.post('/self-service/create')
async def self_service_create(
    request: Request,
    db: DBSessionDep,
    current_user: CurrentUserDep,
    audit_manager: AuditManagerDep,
    audit_user: AuditCurrentUserDep,
    payload: Dict[str, Any] = Body(...),
    dc_manager: DataContractsManager = Depends(get_data_contracts_manager),
    _: bool = Depends(PermissionChecker(FEATURE_ID, FeatureAccessLevel.READ_WRITE)),
):
    """Create catalog/schema/table with parent auto-creation, apply compliance mapping, optionally create a contract and assign to project.

    Payload:
      type: 'catalog'|'schema'|'table'
      catalog: string (optional if type=catalog)
      schema: string (optional; defaults to 'sandbox')
      table: { name: string, columns?: [{ name, logicalType }], physicalType?: 'managed_table'|'streaming_table' }
      projectId: string (optional)
      autoFix: boolean (default true)
      createContract: boolean (default true when type='table')
      defaultToUserCatalog: boolean (default true)
    """
    success = False
    obj_type = (payload.get('type') or '').lower()
    details = {
        "params": {
            "type": obj_type,
            "catalog": payload.get('catalog'),
            "schema": payload.get('schema'),
            "autoFix": payload.get('autoFix', True),
            "createContract": payload.get('createContract', True)
        }
    }

    try:
        ws = get_workspace_client()
        # For self-service, use the same client for both SP and OBO operations
        catalog_manager = CatalogCommanderManager(sp_client=ws, obo_client=ws)

        if obj_type not in ('catalog', 'schema', 'table'):
            raise HTTPException(status_code=400, detail="Invalid type; expected catalog|schema|table")

        username_slug = _username_slug(current_user.email if current_user else None)
        mapping = _load_compliance_mapping()

        auto_fix = bool(payload.get('autoFix', True))
        default_to_user_catalog = bool(payload.get('defaultToUserCatalog', True))
        requested_catalog = (payload.get('catalog') or '').strip()
        requested_schema = (payload.get('schema') or '').strip() or (get_settings().sandbox_default_schema or 'sandbox')
        if not requested_catalog and default_to_user_catalog:
            requested_catalog = f"user_{username_slug}"

        project: Optional[ProjectDb] = None
        project_id = payload.get('projectId')
        if project_id:
            try:
                project = project_repo.get(db, id=project_id)
            except Exception:
                project = None

        # Prepare object skeleton for compliance
        compliance_results: List[Dict[str, Any]] = []

        if obj_type == 'catalog':
            # Sanitize catalog name
            try:
                requested_catalog = sanitize_uc_identifier(requested_catalog)
            except ValueError as e:
                raise HTTPException(status_code=400, detail=f"Invalid catalog name: {e}")
            
            obj: Dict[str, Any] = {'type': 'catalog', 'name': requested_catalog, 'tags': payload.get('tags') or {}}
            if auto_fix:
                obj = self_service_manager.apply_autofix('catalog', obj, mapping, getattr(current_user, 'email', None), project)
            all_passed, res = self_service_manager.evaluate_policies(db, obj, list(mapping.get('catalog', {}).get('policies', [])) if isinstance(mapping.get('catalog'), dict) else [])
            compliance_results.extend(res)
            # Enforce sandbox allowlist for catalog creation
            if not _is_sandbox_allowed(get_settings(), requested_catalog, requested_schema or (get_settings().sandbox_default_schema or 'sandbox')):
                raise HTTPException(status_code=403, detail="Catalog not allowed by sandbox policy")
            
            # Run pre-creation workflow validation (before_create trigger)
            workflow_results: List[Dict[str, Any]] = []
            try:
                trigger_registry = get_trigger_registry(db)
                pre_passed, pre_executions = trigger_registry.before_create(
                    entity_type=EntityType.CATALOG,
                    entity_id=requested_catalog,
                    entity_name=requested_catalog,
                    entity_data=obj,
                    user_email=getattr(current_user, 'email', None),
                )
                for exe in pre_executions:
                    workflow_results.append({
                        'workflow_name': exe.workflow_name,
                        'status': exe.status.value,
                        'success_count': exe.success_count,
                        'failure_count': exe.failure_count,
                        'error': exe.error_message,
                        'step_results': [
                            {
                                'step_id': se.step_id,
                                'passed': se.passed,
                                'message': se.result_data.get('message') if se.result_data else None,
                                'policy_name': se.result_data.get('policy_name') if se.result_data else None,
                            }
                            for se in exe.step_executions
                        ]
                    })
                
                # Block creation if pre-creation validation failed
                if not pre_passed:
                    raise HTTPException(
                        status_code=400,
                        detail={
                            'message': 'Pre-creation validation failed',
                            'workflows': workflow_results,
                        }
                    )
            except HTTPException:
                raise
            except Exception as e:
                logger.warning(f"Before-create trigger failed: {e}")
            
            # Create catalog (idempotent) using shared utility
            requested_catalog = ensure_catalog_exists(
                ws=ws,
                catalog_name=requested_catalog,
                comment=obj.get('tags', {}).get('description')
            )
            
            # Fire post-creation workflow triggers (on_create)
            try:
                trigger_registry = get_trigger_registry(db)
                executions = trigger_registry.on_create(
                    entity_type=EntityType.CATALOG,
                    entity_id=requested_catalog,
                    entity_name=requested_catalog,
                    entity_data=obj,
                    user_email=getattr(current_user, 'email', None),
                    blocking=True,
                )
                for exe in executions:
                    workflow_results.append({
                        'workflow_name': exe.workflow_name,
                        'status': exe.status.value,
                        'success_count': exe.success_count,
                        'failure_count': exe.failure_count,
                        'error': exe.error_message,
                    })
                    # Check if any workflow failed
                    if exe.status == ExecutionStatus.FAILED:
                        compliance_results.append({
                            'type': 'workflow',
                            'workflow': exe.workflow_name,
                            'passed': False,
                            'message': exe.error_message or 'Workflow validation failed',
                        })
            except Exception as e:
                logger.warning(f"Workflow trigger failed: {e}")
            
            success = True
            details["created_catalog"] = requested_catalog
            details["compliance_count"] = len(compliance_results)
            details["workflow_results"] = workflow_results
            return { 'created': {'catalog': requested_catalog}, 'compliance': compliance_results, 'workflows': workflow_results }

        if obj_type == 'schema':
            if not requested_catalog:
                raise HTTPException(status_code=400, detail="catalog is required for schema creation")
            
            # Sanitize catalog and schema names
            try:
                requested_catalog = sanitize_uc_identifier(requested_catalog)
                requested_schema = sanitize_uc_identifier(requested_schema)
            except ValueError as e:
                raise HTTPException(status_code=400, detail=f"Invalid identifier: {e}")
            
            obj = {'type': 'schema', 'name': requested_schema, 'catalog': requested_catalog, 'tags': payload.get('tags') or {}}
            if auto_fix:
                obj = self_service_manager.apply_autofix('schema', obj, mapping, getattr(current_user, 'email', None), project)
            all_passed, res = self_service_manager.evaluate_policies(db, obj, list(mapping.get('schema', {}).get('policies', [])) if isinstance(mapping.get('schema'), dict) else [])
            compliance_results.extend(res)
            # Enforce sandbox allowlist for schema creation
            if not _is_sandbox_allowed(get_settings(), requested_catalog, requested_schema):
                raise HTTPException(status_code=403, detail="Schema not allowed by sandbox policy")
            
            # Run pre-creation workflow validation (before_create trigger)
            workflow_results: List[Dict[str, Any]] = []
            full_schema_name = f"{requested_catalog}.{requested_schema}"
            try:
                trigger_registry = get_trigger_registry(db)
                pre_passed, pre_executions = trigger_registry.before_create(
                    entity_type=EntityType.SCHEMA,
                    entity_id=full_schema_name,
                    entity_name=requested_schema,
                    entity_data=obj,
                    user_email=getattr(current_user, 'email', None),
                )
                for exe in pre_executions:
                    workflow_results.append({
                        'workflow_name': exe.workflow_name,
                        'status': exe.status.value,
                        'success_count': exe.success_count,
                        'failure_count': exe.failure_count,
                        'error': exe.error_message,
                        'step_results': [
                            {
                                'step_id': se.step_id,
                                'passed': se.passed,
                                'message': se.result_data.get('message') if se.result_data else None,
                                'policy_name': se.result_data.get('policy_name') if se.result_data else None,
                            }
                            for se in exe.step_executions
                        ]
                    })
                
                # Block creation if pre-creation validation failed
                if not pre_passed:
                    raise HTTPException(
                        status_code=400,
                        detail={
                            'message': 'Pre-creation validation failed',
                            'workflows': workflow_results,
                        }
                    )
            except HTTPException:
                raise
            except Exception as e:
                logger.warning(f"Before-create trigger failed: {e}")
            
            # Ensure catalog and schema exist using shared utility
            requested_catalog, full_schema_name = ensure_catalog_and_schema_exist(
                ws=ws,
                catalog_name=requested_catalog,
                schema_name=requested_schema
            )
            
            # Fire post-creation workflow triggers (on_create)
            try:
                trigger_registry = get_trigger_registry(db)
                executions = trigger_registry.on_create(
                    entity_type=EntityType.SCHEMA,
                    entity_id=full_schema_name,
                    entity_name=requested_schema,
                    entity_data=obj,
                    user_email=getattr(current_user, 'email', None),
                    blocking=True,
                )
                for exe in executions:
                    workflow_results.append({
                        'workflow_name': exe.workflow_name,
                        'status': exe.status.value,
                        'success_count': exe.success_count,
                        'failure_count': exe.failure_count,
                        'error': exe.error_message,
                    })
                    if exe.status == ExecutionStatus.FAILED:
                        compliance_results.append({
                            'type': 'workflow',
                            'workflow': exe.workflow_name,
                            'passed': False,
                            'message': exe.error_message or 'Workflow validation failed',
                        })
            except Exception as e:
                logger.warning(f"Workflow trigger failed: {e}")
            
            success = True
            details["created_catalog"] = requested_catalog
            details["created_schema"] = requested_schema
            details["compliance_count"] = len(compliance_results)
            details["workflow_results"] = workflow_results
            return { 'created': {'catalog': requested_catalog, 'schema': requested_schema}, 'compliance': compliance_results, 'workflows': workflow_results }

        # table
        table_spec = payload.get('table') or {}
        table_name = (table_spec.get('name') or '').strip()
        if not requested_catalog or not requested_schema or not table_name:
            raise HTTPException(status_code=400, detail="catalog, schema, and table.name are required for table creation")

        # Sanitize all identifiers
        try:
            requested_catalog = sanitize_uc_identifier(requested_catalog)
            requested_schema = sanitize_uc_identifier(requested_schema)
            table_name = sanitize_uc_identifier(table_name)
        except ValueError as e:
            raise HTTPException(status_code=400, detail=f"Invalid identifier: {e}")

        # Compliance for table
        obj = {'type': 'table', 'name': table_name, 'catalog': requested_catalog, 'schema': requested_schema, 'tags': (table_spec.get('tags') or {})}
        if auto_fix:
            obj = self_service_manager.apply_autofix('table', obj, mapping, getattr(current_user, 'email', None), project)
        all_passed, res = self_service_manager.evaluate_policies(db, obj, list(mapping.get('table', {}).get('policies', [])) if isinstance(mapping.get('table'), dict) else [])
        compliance_results.extend(res)

        # Enforce sandbox allowlist for table creation
        if not _is_sandbox_allowed(get_settings(), requested_catalog, requested_schema):
            raise HTTPException(status_code=403, detail="Table location not allowed by sandbox policy")
        
        # Run pre-creation workflow validation (before_create trigger)
        workflow_results: List[Dict[str, Any]] = []
        full_name = f"{requested_catalog}.{requested_schema}.{table_name}"
        try:
            trigger_registry = get_trigger_registry(db)
            pre_passed, pre_executions = trigger_registry.before_create(
                entity_type=EntityType.TABLE,
                entity_id=full_name,
                entity_name=table_name,
                entity_data=obj,
                user_email=getattr(current_user, 'email', None),
            )
            for exe in pre_executions:
                workflow_results.append({
                    'workflow_name': exe.workflow_name,
                    'status': exe.status.value,
                    'success_count': exe.success_count,
                    'failure_count': exe.failure_count,
                    'error': exe.error_message,
                    'step_results': [
                        {
                            'step_id': se.step_id,
                            'passed': se.passed,
                            'message': se.result_data.get('message') if se.result_data else None,
                            'policy_name': se.result_data.get('policy_name') if se.result_data else None,
                        }
                        for se in exe.step_executions
                    ]
                })
            
            # Block creation if pre-creation validation failed
            if not pre_passed:
                raise HTTPException(
                    status_code=400,
                    detail={
                        'message': 'Pre-creation validation failed',
                        'workflows': workflow_results,
                    }
                )
        except HTTPException:
            raise
        except Exception as e:
            logger.warning(f"Before-create trigger failed: {e}")

        # Ensure parent catalog and schema exist using shared utility
        requested_catalog, full_schema_name = ensure_catalog_and_schema_exist(
            ws=ws,
            catalog_name=requested_catalog,
            schema_name=requested_schema
        )

        # Create table using shared utility (prevents SQL injection)
        columns: List[Dict[str, Any]] = table_spec.get('columns') or []
        full_name = create_table_safe(
            ws=ws,
            catalog_name=requested_catalog,
            schema_name=requested_schema,
            table_name=table_name,
            columns=columns
        )

        created_contract_id: Optional[str] = None
        if bool(payload.get('createContract', True)):
            # Build minimal ODCS contract dict and create
            odcs = {
                'name': table_name,
                'version': '1.0.0',
                'status': 'draft',
                'owner': getattr(current_user, 'username', None) or getattr(current_user, 'email', None),
                'schema': [
                    {
                        'name': table_name,
                        'physicalName': full_name,
                        'physicalType': 'managed_table',
                        'properties': [
                            {
                                'name': c.get('name'),
                                'logicalType': c.get('logicalType') or c.get('logical_type') or 'string',
                                'required': False,
                            } for c in columns if c.get('name')
                        ]
                    }
                ]
            }
            try:
                created_db = dc_manager.create_from_odcs_dict(db, odcs, getattr(current_user, 'username', None))
                created_contract_id = created_db.id
                # Assign to project if provided
                if project_id and created_db:
                    try:
                        created_db.project_id = project_id
                        db.add(created_db)
                        db.flush()
                    except Exception:
                        logger.warning("Failed to assign project_id to created contract", exc_info=True)
                db.commit()
            except Exception as e:
                logger.warning(f"Failed to create data contract for table: {e}", exc_info=True)

        # Fire post-creation workflow triggers (on_create)
        try:
            trigger_registry = get_trigger_registry(db)
            executions = trigger_registry.on_create(
                entity_type=EntityType.TABLE,
                entity_id=full_name,
                entity_name=table_name,
                entity_data=obj,
                user_email=getattr(current_user, 'email', None),
                blocking=True,
            )
            for exe in executions:
                workflow_results.append({
                    'workflow_name': exe.workflow_name,
                    'status': exe.status.value,
                    'success_count': exe.success_count,
                    'failure_count': exe.failure_count,
                    'error': exe.error_message,
                })
                if exe.status == ExecutionStatus.FAILED:
                    compliance_results.append({
                        'type': 'workflow',
                        'workflow': exe.workflow_name,
                        'passed': False,
                        'message': exe.error_message or 'Workflow validation failed',
                    })
        except Exception as e:
            logger.warning(f"Workflow trigger failed: {e}")
        
        success = True
        details["created_catalog"] = requested_catalog
        details["created_schema"] = requested_schema
        details["created_table"] = table_name
        details["full_name"] = full_name
        details["contract_id"] = created_contract_id
        details["compliance_count"] = len(compliance_results)
        details["workflow_results"] = workflow_results

        return {
            'created': {
                'catalog': requested_catalog,
                'schema': requested_schema,
                'table': table_name,
                'full_name': full_name,
            },
            'contractId': created_contract_id,
            'compliance': compliance_results,
            'workflows': workflow_results,
        }
    except HTTPException as e:
        details["exception"] = {"type": "HTTPException", "status_code": e.status_code, "detail": e.detail}
        raise
    except Exception as e:
        logger.exception("Self-service create failed")
        details["exception"] = {"type": type(e).__name__, "message": str(e)}
        raise HTTPException(status_code=500, detail="Failed to create self-service resource")
    finally:
        audit_manager.log_action(
            db=db,
            username=audit_user.username,
            ip_address=request.client.host if request.client else None,
            feature="self-service",
            action="CREATE",
            success=success,
            details=details
        )


def register_routes(app):
    app.include_router(router)
    logger.info("Self-service routes registered")


@router.post('/self-service/deploy/{contract_id}')
async def deploy_contract(
    contract_id: str,
    request: Request,
    db: DBSessionDep,
    current_user: CurrentUserDep,
    audit_manager: AuditManagerDep,
    audit_user: AuditCurrentUserDep,
    body: Dict[str, Any] = Body(default={}),
    _: bool = Depends(PermissionChecker(FEATURE_ID, FeatureAccessLevel.READ_WRITE)),
):
    """Deploy a data contract to Unity Catalog by creating its physical dataset(s).

    Every target catalog/schema must pass the sandbox allowlist (as for
    /self-service/create); otherwise nothing is created and the answer is 403
    with the code ``sandbox_location_not_allowed``.

    Optional body keys:
      defaultCatalog: string
      defaultSchema: string
    """
    success = False
    details = {
        "params": {
            "contract_id": contract_id,
            "defaultCatalog": body.get('defaultCatalog'),
            "defaultSchema": body.get('defaultSchema')
        }
    }

    try:
        ws = get_workspace_client()
        contract = data_contract_repo.get_with_all(db, id=contract_id)
        if not contract:
            raise HTTPException(status_code=404, detail="Contract not found")

        default_catalog = (body.get('defaultCatalog') or '').strip()
        default_schema = (body.get('defaultSchema') or '').strip()

        # Resolve and validate every target first, so a refused object stops the
        # whole deploy before anything is created.
        targets: List[Tuple[Any, str, str, str]] = []
        for sobj in (contract.schema_objects or []):
            # Resolve physical name or build from defaults
            physical_name = getattr(sobj, 'physical_name', None) or ''
            if not physical_name:
                if not default_catalog or not default_schema:
                    # Cannot build full name
                    raise HTTPException(status_code=400, detail="Missing physicalName and defaults for deployment")
                physical_name = f"{default_catalog}.{default_schema}.{sobj.name}"

            parts = physical_name.split('.')
            if len(parts) != 3:
                raise HTTPException(status_code=400, detail=f"Invalid physical name: {physical_name}")
            catalog_name, schema_name, table_name = parts

            # Sanitize all identifiers
            try:
                catalog_name = sanitize_uc_identifier(catalog_name)
                schema_name = sanitize_uc_identifier(schema_name)
                table_name = sanitize_uc_identifier(table_name)
            except ValueError as e:
                raise HTTPException(status_code=400, detail=f"Invalid identifier in physical name: {e}")
            targets.append((sobj, catalog_name, schema_name, table_name))

        # Same sandbox allowlist as the other self-service creation paths
        settings = get_settings()
        for _, catalog_name, schema_name, _ in targets:
            if not _is_sandbox_allowed(settings, catalog_name, schema_name):
                err = SandboxLocationNotAllowedError(catalog_name, schema_name)
                raise HTTPException(status_code=403, detail=str(err)) from err

        created: List[str] = []
        for sobj, catalog_name, schema_name, table_name in targets:
            # Ensure parent catalog and schema exist using shared utility
            catalog_name, full_schema_name = ensure_catalog_and_schema_exist(
                ws=ws,
                catalog_name=catalog_name,
                schema_name=schema_name
            )

            # Prepare column definitions from properties
            props = getattr(sobj, 'properties', []) or []
            columns_for_create: List[Dict[str, Any]] = []
            for p in props:
                try:
                    pname = getattr(p, 'name', None) or (p.get('name') if hasattr(p, 'get') else None)
                    ltype = (
                        getattr(p, 'logical_type', None) or 
                        getattr(p, 'logicalType', None) or 
                        (p.get('logicalType') if hasattr(p, 'get') else None) or 
                        'string'
                    )
                except Exception:
                    pname = None
                    ltype = 'string'
                if pname:
                    columns_for_create.append({
                        'name': str(pname),
                        'logicalType': str(ltype)
                    })

            # Create table using shared utility (prevents SQL injection)
            try:
                table_full_name = create_table_safe(
                    ws=ws,
                    catalog_name=catalog_name,
                    schema_name=schema_name,
                    table_name=table_name,
                    columns=columns_for_create
                )
                created.append(table_full_name)
            except HTTPException:
                raise
            except Exception as e:
                raise HTTPException(status_code=500, detail=f"Failed creating table {table_name}: {e}")

        success = True
        details["created_tables"] = created
        details["table_count"] = len(created)
        return { 'created': created }
    except HTTPException as e:
        details["exception"] = {"type": "HTTPException", "status_code": e.status_code, "detail": e.detail}
        raise
    except Exception as e:
        logger.exception("Deploy contract failed")
        details["exception"] = {"type": type(e).__name__, "message": str(e)}
        raise HTTPException(status_code=500, detail="Failed to deploy contract")
    finally:
        audit_manager.log_action(
            db=db,
            username=audit_user.username,
            ip_address=request.client.host if request.client else None,
            feature="self-service",
            action="DEPLOY",
            success=success,
            details=details
        )


