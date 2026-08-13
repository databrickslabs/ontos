"""API routes for Compliance Templates.

Two RBAC surfaces:
- ``settings-compliance-templates`` gates admin template *definition* management.
- ``compliance-template-values`` gates per-entity value read (READ_ONLY) vs
  write (READ_WRITE).
"""
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status

from src.common.authorization import PermissionChecker
from src.common.dependencies import CurrentUserDep, DBSessionDep
from src.common.features import FeatureAccessLevel
from src.common.logging import get_logger
from src.controller.compliance_templates_manager import (
    ComplianceTemplateError,
    compliance_templates_manager,
)
from src.models.compliance_templates import (
    ComplianceCompletenessRead,
    ComplianceTemplateCreate,
    ComplianceTemplateRead,
    ComplianceTemplateUpdate,
    ComplianceValuesReplace,
    EntityComplianceRead,
)

logger = get_logger(__name__)

router = APIRouter(prefix="/api/compliance-templates", tags=["Compliance Templates"])

ADMIN_FEATURE_ID = "settings-compliance-templates"
VALUES_FEATURE_ID = "compliance-template-values"


# ----- Admin: template definitions ----------------------------------------

@router.get("", response_model=list[ComplianceTemplateRead])
async def list_templates(
    db: DBSessionDep,
    entity_type: str | None = None,
    _: None = Depends(PermissionChecker(ADMIN_FEATURE_ID, FeatureAccessLevel.READ_ONLY)),
):
    """List templates, optionally filtered by bound entity type. Admin surface."""
    return compliance_templates_manager.list_templates(db, entity_type=entity_type)


@router.post("", response_model=ComplianceTemplateRead, status_code=status.HTTP_201_CREATED)
async def create_template(
    body: ComplianceTemplateCreate,
    db: DBSessionDep,
    current_user: CurrentUserDep,
    _: None = Depends(PermissionChecker(ADMIN_FEATURE_ID, FeatureAccessLevel.READ_WRITE)),
):
    """Create a template (optionally with inline fields). Admin only."""
    try:
        return compliance_templates_manager.create_template(
            db, payload=body, user_email=current_user.email if current_user else None
        )
    except ComplianceTemplateError as e:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    except Exception as e:
        db.rollback()
        logger.error(f"Error creating compliance template: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to create compliance template")


@router.put("/{template_id}", response_model=ComplianceTemplateRead)
async def update_template(
    template_id: UUID,
    body: ComplianceTemplateUpdate,
    db: DBSessionDep,
    _: None = Depends(PermissionChecker(ADMIN_FEATURE_ID, FeatureAccessLevel.READ_WRITE)),
):
    """Update a template's safe attributes (name, description). Admin only."""
    update_data = body.model_dump(exclude_unset=True)
    try:
        return compliance_templates_manager.update_template(db, template_id=template_id, update_data=update_data)
    except ComplianceTemplateError as e:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))


@router.post("/{template_id}/activate", response_model=ComplianceTemplateRead)
async def activate_template(
    template_id: UUID,
    db: DBSessionDep,
    _: None = Depends(PermissionChecker(ADMIN_FEATURE_ID, FeatureAccessLevel.READ_WRITE)),
):
    """Activate a template, deactivating any currently-active one for its entity type."""
    try:
        return compliance_templates_manager.set_active(db, template_id=template_id, active=True)
    except ComplianceTemplateError as e:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))


@router.post("/{template_id}/deactivate", response_model=ComplianceTemplateRead)
async def deactivate_template(
    template_id: UUID,
    db: DBSessionDep,
    _: None = Depends(PermissionChecker(ADMIN_FEATURE_ID, FeatureAccessLevel.READ_WRITE)),
):
    """Deactivate a template."""
    try:
        return compliance_templates_manager.set_active(db, template_id=template_id, active=False)
    except ComplianceTemplateError as e:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))


@router.delete("/{template_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_template(
    template_id: UUID,
    db: DBSessionDep,
    _: None = Depends(PermissionChecker(ADMIN_FEATURE_ID, FeatureAccessLevel.READ_WRITE)),
):
    """Delete a template and its fields/values. Admin only."""
    try:
        compliance_templates_manager.delete_template(db, template_id=template_id)
    except ComplianceTemplateError as e:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))


# ----- Per-entity: composed read + replace-all write -----------------------

@router.get("/entities/{entity_type}/{entity_id}", response_model=EntityComplianceRead)
async def read_entity_compliance(
    entity_type: str,
    entity_id: str,
    db: DBSessionDep,
    _: None = Depends(PermissionChecker(VALUES_FEATURE_ID, FeatureAccessLevel.READ_ONLY)),
):
    """Composed read: { template, fields, values } for an entity. Read-only allowed."""
    return compliance_templates_manager.read_for_entity(db, entity_type=entity_type, entity_id=entity_id)


@router.get("/entities/{entity_type}/{entity_id}/completeness", response_model=ComplianceCompletenessRead)
async def entity_completeness(
    entity_type: str,
    entity_id: str,
    db: DBSessionDep,
    _: None = Depends(PermissionChecker(VALUES_FEATURE_ID, FeatureAccessLevel.READ_ONLY)),
):
    """Advisory completeness result for an entity. Never blocks; read-only allowed."""
    applicable = compliance_templates_manager.has_active_template(db, entity_type=entity_type)
    result = compliance_templates_manager.check_completeness(db, entity_type=entity_type, entity_id=entity_id)
    return ComplianceCompletenessRead(
        applicable=applicable,
        passed=result.passed,
        missing=result.missing,
        messages=result.messages,
    )


@router.put("/entities/{entity_type}/{entity_id}/values", response_model=EntityComplianceRead)
async def replace_entity_values(
    entity_type: str,
    entity_id: str,
    body: ComplianceValuesReplace,
    db: DBSessionDep,
    current_user: CurrentUserDep,
    _: None = Depends(PermissionChecker(VALUES_FEATURE_ID, FeatureAccessLevel.READ_WRITE)),
):
    """Replace-all write of an entity's values (the materialization event)."""
    try:
        return compliance_templates_manager.replace_values(
            db,
            entity_type=entity_type,
            entity_id=entity_id,
            writes=body.values,
            user_email=current_user.email if current_user else None,
        )
    except ComplianceTemplateError as e:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    except Exception as e:
        db.rollback()
        logger.error(f"Error writing compliance values: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to write compliance values")


def register_routes(app):
    app.include_router(router)
    logger.info("Compliance templates routes registered")
