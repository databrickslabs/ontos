import hashlib
import uuid
from io import BytesIO
from typing import Annotated, List, Optional

from fastapi import APIRouter, Depends, HTTPException, status, UploadFile, File, Body, Request, Query
from fastapi.responses import StreamingResponse
from fastapi import Response
from sqlalchemy.orm import Session
from pydantic import ValidationError

from src.common.dependencies import DBSessionDep, CurrentUserDep, AuditManagerDep, AuditCurrentUserDep
from src.common.features import FeatureAccessLevel
from src.common.authorization import (
    EntityTypePermissionChecker,
    PermissionChecker,
    check_entity_permission,
    check_feature_permission,
    get_user_details_from_sdk,
)
from src.common.logging import get_logger
from src.common.file_security import sanitize_filename, sanitize_filename_for_header, is_safe_path_component
from src.controller.metadata_manager import MetadataManager, NotSharedAssetError, SHARED_ENTITY_ID, SharedScopeNotAllowedError
from src.common.manager_dependencies import get_auth_manager, get_metadata_manager
from src.models.metadata import (
    METADATA_ENTITY_FEATURES,
    RichText, RichTextCreate, RichTextUpdate,
    Link, LinkCreate, LinkUpdate,
    Document, DocumentCreate,
    MetadataAttachment, MetadataAttachmentCreate,
    SharedAssetListResponse, MergedMetadataResponse,
)
from src.common.config import get_settings, Settings
from src.common.workspace_client import get_workspace_client
from src.controller.authorization_manager import AuthorizationManager
from src.models.users import UserInfo
from databricks.sdk import WorkspaceClient

logger = get_logger(__name__)

router = APIRouter(prefix="/api", tags=["Metadata"])

# Shared library assets (/metadata/shared..., and records flagged shared) keep the
# domain feature. Routes on one entity's metadata check the feature that owns that
# entity's kind (METADATA_ENTITY_FEATURES).
FEATURE_ID = "data-domains"


def _is_uuid(value: str) -> bool:
    try:
        uuid.UUID(value)
    except (ValueError, TypeError):
        return False
    return True


def _storage_segment(entity_id: str) -> str:
    """Volume path segment for an entity id. IRIs (concepts, collections) contain '/', so they're hashed."""
    if is_safe_path_component(entity_id):
        return entity_id
    return "iri-" + hashlib.sha256(entity_id.encode("utf-8")).hexdigest()[:32]


def _refuse_shared_scope(is_shared: bool, entity_id: str) -> None:
    """Entity-scoped creates never make library records; those are created on /metadata/shared."""
    if is_shared or entity_id == SHARED_ENTITY_ID:
        err = SharedScopeNotAllowedError("Shared library records are created on the shared metadata routes.")
        raise HTTPException(status_code=400, detail=str(err)) from err


def _record_permission(kind: str, required_level: FeatureAccessLevel, not_found_detail: str):
    """Dependency for routes addressed by record id: check the feature of the record's entity kind.

    Shared library records are checked against the library's feature, whatever
    entity kind they were created from.
    """
    async def dependency(
        id: str,
        request: Request,
        db: DBSessionDep,
        user_details: UserInfo = Depends(get_user_details_from_sdk),
        auth_manager: AuthorizationManager = Depends(get_auth_manager),
        manager: MetadataManager = Depends(get_metadata_manager),
    ) -> None:
        scope = manager.get_record_scope(db, kind=kind, id=id) if _is_uuid(id) else None
        if scope is None:
            raise HTTPException(status_code=404, detail=not_found_detail)
        entity_type, is_shared = scope
        if is_shared:
            await check_feature_permission(request, user_details, auth_manager, FEATURE_ID, required_level)
            return
        await check_entity_permission(
            request, user_details, auth_manager, METADATA_ENTITY_FEATURES, entity_type, required_level,
        )
    return dependency


# --- Rich Text ---
@router.post("/entities/{entity_type}/rich-texts", response_model=RichText, status_code=status.HTTP_201_CREATED)
async def create_rich_text(
    entity_type: str,
    entity_id: Annotated[str, Query(min_length=1, description='Entity id (may be an IRI)')],
    request: Request,
    payload: RichTextCreate,
    db: DBSessionDep,
    audit_manager: AuditManagerDep,
    current_user: AuditCurrentUserDep,
    manager: MetadataManager = Depends(get_metadata_manager),
    _: None = Depends(EntityTypePermissionChecker(METADATA_ENTITY_FEATURES, FeatureAccessLevel.READ_WRITE)),
):
    try:
        if payload.entity_type != entity_type or payload.entity_id != entity_id:
            raise HTTPException(status_code=400, detail="Entity path does not match body")
        _refuse_shared_scope(payload.is_shared, payload.entity_id)
        result = manager.create_rich_text(db, data=payload, user_email=current_user.email if current_user else None)
        
        audit_manager.log_action(
            db=db,
            username=current_user.username if current_user else 'unknown',
            ip_address=request.client.host if request.client else None,
            feature=FEATURE_ID,
            action='CREATE_RICH_TEXT',
            success=True,
            details={'entity_type': entity_type, 'entity_id': entity_id}
        )
        
        return result
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Failed creating rich text for %s/%s", entity_type, entity_id)
        raise HTTPException(status_code=500, detail="Failed to create rich text")


@router.get("/entities/{entity_type}/rich-texts", response_model=List[RichText])
async def list_rich_texts(
    entity_type: str,
    entity_id: Annotated[str, Query(min_length=1, description='Entity id (may be an IRI)')],
    db: DBSessionDep,
    manager: MetadataManager = Depends(get_metadata_manager),
    _: None = Depends(EntityTypePermissionChecker(METADATA_ENTITY_FEATURES, FeatureAccessLevel.READ_ONLY)),
):
    return manager.list_rich_texts(db, entity_type=entity_type, entity_id=entity_id)


@router.put("/rich-texts/{id}", response_model=RichText)
async def update_rich_text(
    id: str,
    request: Request,
    payload: RichTextUpdate,
    db: DBSessionDep,
    audit_manager: AuditManagerDep,
    current_user: AuditCurrentUserDep,
    manager: MetadataManager = Depends(get_metadata_manager),
    _: None = Depends(_record_permission("rich_text", FeatureAccessLevel.READ_WRITE, "Rich text not found")),
):
    updated = manager.update_rich_text(db, id=id, data=payload, user_email=current_user.email if current_user else None)
    if not updated:
        raise HTTPException(status_code=404, detail="Rich text not found")
    
    audit_manager.log_action(
        db=db,
        username=current_user.username if current_user else 'unknown',
        ip_address=request.client.host if request.client else None,
        feature=FEATURE_ID,
        action='UPDATE_RICH_TEXT',
        success=True,
        details={'rich_text_id': id}
    )
    
    return updated


@router.delete("/rich-texts/{id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_rich_text(
    id: str,
    request: Request,
    db: DBSessionDep,
    audit_manager: AuditManagerDep,
    current_user: AuditCurrentUserDep,
    manager: MetadataManager = Depends(get_metadata_manager),
    _: None = Depends(_record_permission("rich_text", FeatureAccessLevel.READ_WRITE, "Rich text not found")),
):
    ok = manager.delete_rich_text(db, id=id, user_email=current_user.email if current_user else None)
    if not ok:
        raise HTTPException(status_code=404, detail="Rich text not found")
    
    audit_manager.log_action(
        db=db,
        username=current_user.username if current_user else 'unknown',
        ip_address=request.client.host if request.client else None,
        feature=FEATURE_ID,
        action='DELETE_RICH_TEXT',
        success=True,
        details={'rich_text_id': id}
    )
    
    return


# --- Links ---
@router.post("/entities/{entity_type}/links", response_model=Link, status_code=status.HTTP_201_CREATED)
async def create_link(
    entity_type: str,
    entity_id: Annotated[str, Query(min_length=1, description='Entity id (may be an IRI)')],
    request: Request,
    payload: LinkCreate,
    db: DBSessionDep,
    audit_manager: AuditManagerDep,
    current_user: AuditCurrentUserDep,
    manager: MetadataManager = Depends(get_metadata_manager),
    _: None = Depends(EntityTypePermissionChecker(METADATA_ENTITY_FEATURES, FeatureAccessLevel.READ_WRITE)),
):
    try:
        if payload.entity_type != entity_type or payload.entity_id != entity_id:
            raise HTTPException(status_code=400, detail="Entity path does not match body")
        _refuse_shared_scope(payload.is_shared, payload.entity_id)
        result = manager.create_link(db, data=payload, user_email=current_user.email if current_user else None)
        
        audit_manager.log_action(
            db=db,
            username=current_user.username if current_user else 'unknown',
            ip_address=request.client.host if request.client else None,
            feature=FEATURE_ID,
            action='CREATE_LINK',
            success=True,
            details={'entity_type': entity_type, 'entity_id': entity_id}
        )
        
        return result
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Failed creating link for %s/%s", entity_type, entity_id)
        raise HTTPException(status_code=500, detail="Failed to create link")


@router.get("/entities/{entity_type}/links", response_model=List[Link])
async def list_links(
    entity_type: str,
    entity_id: Annotated[str, Query(min_length=1, description='Entity id (may be an IRI)')],
    db: DBSessionDep,
    manager: MetadataManager = Depends(get_metadata_manager),
    _: None = Depends(EntityTypePermissionChecker(METADATA_ENTITY_FEATURES, FeatureAccessLevel.READ_ONLY)),
):
    return manager.list_links(db, entity_type=entity_type, entity_id=entity_id)


@router.put("/links/{id}", response_model=Link)
async def update_link(
    id: str,
    request: Request,
    payload: LinkUpdate,
    db: DBSessionDep,
    audit_manager: AuditManagerDep,
    current_user: AuditCurrentUserDep,
    manager: MetadataManager = Depends(get_metadata_manager),
    _: None = Depends(_record_permission("link", FeatureAccessLevel.READ_WRITE, "Link not found")),
):
    updated = manager.update_link(db, id=id, data=payload, user_email=current_user.email if current_user else None)
    if not updated:
        raise HTTPException(status_code=404, detail="Link not found")
    
    audit_manager.log_action(
        db=db,
        username=current_user.username if current_user else 'unknown',
        ip_address=request.client.host if request.client else None,
        feature=FEATURE_ID,
        action='UPDATE_LINK',
        success=True,
        details={'link_id': id}
    )
    
    return updated


@router.delete("/links/{id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_link(
    id: str,
    request: Request,
    db: DBSessionDep,
    audit_manager: AuditManagerDep,
    current_user: AuditCurrentUserDep,
    manager: MetadataManager = Depends(get_metadata_manager),
    _: None = Depends(_record_permission("link", FeatureAccessLevel.READ_WRITE, "Link not found")),
):
    ok = manager.delete_link(db, id=id, user_email=current_user.email if current_user else None)
    if not ok:
        raise HTTPException(status_code=404, detail="Link not found")
    
    audit_manager.log_action(
        db=db,
        username=current_user.username if current_user else 'unknown',
        ip_address=request.client.host if request.client else None,
        feature=FEATURE_ID,
        action='DELETE_LINK',
        success=True,
        details={'link_id': id}
    )
    
    return


# --- Documents ---
@router.post("/entities/{entity_type}/documents", response_model=Document, status_code=status.HTTP_201_CREATED)
async def upload_document(
    entity_type: str,
    entity_id: Annotated[str, Query(min_length=1, description='Entity id (may be an IRI)')],
    request: Request,
    db: DBSessionDep,
    audit_manager: AuditManagerDep,
    current_user: AuditCurrentUserDep,
    title: str = Body(...),
    short_description: Optional[str] = Body(None),
    file: UploadFile = File(...),
    manager: MetadataManager = Depends(get_metadata_manager),
    settings: Settings = Depends(get_settings),
    ws: WorkspaceClient = Depends(get_workspace_client),
    _: None = Depends(EntityTypePermissionChecker(METADATA_ENTITY_FEATURES, FeatureAccessLevel.READ_WRITE)),
):
    try:
        # Validate path components to prevent directory traversal
        if not is_safe_path_component(entity_type):
            raise HTTPException(status_code=400, detail="Invalid entity_type or entity_id")
        _refuse_shared_scope(False, entity_id)

        # Validate the request before touching the volume, so a rejected
        # request never leaves an orphaned file behind.
        try:
            payload = DocumentCreate(
                entity_type=entity_type,
                entity_id=entity_id,
                title=title,
                short_description=short_description,
            )
        except ValidationError as e:
            raise HTTPException(status_code=422, detail=e.errors(include_url=False, include_context=False))
        
        # Ensure volume/path
        base_dir = f"uploads/{entity_type}/{_storage_segment(entity_id)}"
        volume_fs_base = manager.ensure_volume_path(ws, settings, base_dir)

        # Read file content
        content = await file.read()
        
        # SECURITY: Sanitize filename to prevent path traversal and other exploits
        raw_filename = file.filename or "document.bin"
        filename = sanitize_filename(raw_filename, default="document.bin")
        
        content_type = file.content_type
        size_bytes = len(content) if content else 0

        # Destination path (filename is now sanitized)
        dest_path = f"{volume_fs_base}/{base_dir}/{filename}"

        # Ensure directory exists in UC Volumes filesystem
        try:
            ws.files.create_directory(f"{volume_fs_base}/{base_dir}")
        except Exception:
            pass

        # Upload file bytes to the UC Volume path (path, file-like object, overwrite)
        ws.files.upload(dest_path, BytesIO(content))

        result = manager.create_document_record(
            db,
            data=payload,
            filename=filename,
            content_type=content_type,
            size_bytes=size_bytes,
            storage_path=dest_path,
            user_email=current_user.email if current_user else None,
        )
        
        audit_manager.log_action(
            db=db,
            username=current_user.username if current_user else 'unknown',
            ip_address=request.client.host if request.client else None,
            feature=FEATURE_ID,
            action='UPLOAD_DOCUMENT',
            success=True,
            details={'entity_type': entity_type, 'entity_id': entity_id, 'filename': filename}
        )
        
        return result
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Failed uploading document for %s/%s", entity_type, entity_id)
        raise HTTPException(status_code=500, detail="Failed to upload document")


@router.get("/entities/{entity_type}/documents", response_model=List[Document])
async def list_documents(
    entity_type: str,
    entity_id: Annotated[str, Query(min_length=1, description='Entity id (may be an IRI)')],
    db: DBSessionDep,
    manager: MetadataManager = Depends(get_metadata_manager),
    _: None = Depends(EntityTypePermissionChecker(METADATA_ENTITY_FEATURES, FeatureAccessLevel.READ_ONLY)),
):
    return manager.list_documents(db, entity_type=entity_type, entity_id=entity_id)


@router.get("/documents/{id}", response_model=Document)
async def get_document(
    id: str,
    db: DBSessionDep,
    manager: MetadataManager = Depends(get_metadata_manager),
    _: None = Depends(_record_permission("document", FeatureAccessLevel.READ_ONLY, "Document not found")),
):
    doc = manager.get_document(db, id=id)
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")
    return doc


@router.delete("/documents/{id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_document(
    id: str,
    request: Request,
    db: DBSessionDep,
    audit_manager: AuditManagerDep,
    current_user: AuditCurrentUserDep,
    manager: MetadataManager = Depends(get_metadata_manager),
    _: None = Depends(_record_permission("document", FeatureAccessLevel.READ_WRITE, "Document not found")),
):
    ok = manager.delete_document(db, id=id, user_email=current_user.email if current_user else None)
    if not ok:
        raise HTTPException(status_code=404, detail="Document not found")
    
    audit_manager.log_action(
        db=db,
        username=current_user.username if current_user else 'unknown',
        ip_address=request.client.host if request.client else None,
        feature=FEATURE_ID,
        action='DELETE_DOCUMENT',
        success=True,
        details={'document_id': id}
    )
    
    return


# =========================================================================
# Shared Assets Endpoints
# =========================================================================

@router.get("/metadata/shared", response_model=SharedAssetListResponse)
async def list_shared_assets(
    entity_type: Optional[str] = Query(None, description="Filter by entity type"),
    db: DBSessionDep = None,
    manager: MetadataManager = Depends(get_metadata_manager),
    _: bool = Depends(PermissionChecker(FEATURE_ID, FeatureAccessLevel.READ_ONLY)),
):
    """List all shared metadata assets."""
    return manager.list_shared_assets(db, entity_type=entity_type)


@router.post("/metadata/shared/rich-texts", response_model=RichText, status_code=status.HTTP_201_CREATED)
async def create_shared_rich_text(
    request: Request,
    payload: RichTextCreate,
    db: DBSessionDep,
    audit_manager: AuditManagerDep,
    current_user: AuditCurrentUserDep,
    manager: MetadataManager = Depends(get_metadata_manager),
    _: bool = Depends(PermissionChecker(FEATURE_ID, FeatureAccessLevel.READ_WRITE)),
):
    """Create a new shared rich text asset."""
    try:
        result = manager.create_shared_rich_text(db, data=payload, user_email=current_user.email if current_user else None)
        
        audit_manager.log_action(
            db=db,
            username=current_user.username if current_user else 'unknown',
            ip_address=request.client.host if request.client else None,
            feature=FEATURE_ID,
            action='CREATE_SHARED_RICH_TEXT',
            success=True,
            details={}
        )
        
        return result
    except Exception as e:
        logger.exception("Failed creating shared rich text")
        raise HTTPException(status_code=500, detail="Failed to create shared rich text")


@router.post("/metadata/shared/links", response_model=Link, status_code=status.HTTP_201_CREATED)
async def create_shared_link(
    request: Request,
    payload: LinkCreate,
    db: DBSessionDep,
    audit_manager: AuditManagerDep,
    current_user: AuditCurrentUserDep,
    manager: MetadataManager = Depends(get_metadata_manager),
    _: bool = Depends(PermissionChecker(FEATURE_ID, FeatureAccessLevel.READ_WRITE)),
):
    """Create a new shared link asset."""
    try:
        result = manager.create_shared_link(db, data=payload, user_email=current_user.email if current_user else None)
        
        audit_manager.log_action(
            db=db,
            username=current_user.username if current_user else 'unknown',
            ip_address=request.client.host if request.client else None,
            feature=FEATURE_ID,
            action='CREATE_SHARED_LINK',
            success=True,
            details={}
        )
        
        return result
    except Exception as e:
        logger.exception("Failed creating shared link")
        raise HTTPException(status_code=500, detail="Failed to create shared link")


@router.post("/metadata/shared/documents", response_model=Document, status_code=status.HTTP_201_CREATED)
async def upload_shared_document(
    request: Request,
    db: DBSessionDep,
    audit_manager: AuditManagerDep,
    current_user: AuditCurrentUserDep,
    title: str = Body(...),
    short_description: Optional[str] = Body(None),
    level: int = Body(50),
    inheritable: bool = Body(True),
    file: UploadFile = File(...),
    manager: MetadataManager = Depends(get_metadata_manager),
    settings: Settings = Depends(get_settings),
    ws: WorkspaceClient = Depends(get_workspace_client),
    _: bool = Depends(PermissionChecker(FEATURE_ID, FeatureAccessLevel.READ_WRITE)),
):
    """Upload a new shared document asset. Stored in shared folder."""
    try:
        # Use shared folder for shared documents
        base_dir = "uploads/__shared__"
        volume_fs_base = manager.ensure_volume_path(ws, settings, base_dir)

        content = await file.read()
        raw_filename = file.filename or "document.bin"
        filename = sanitize_filename(raw_filename, default="document.bin")
        content_type = file.content_type
        size_bytes = len(content) if content else 0

        dest_path = f"{volume_fs_base}/{base_dir}/{filename}"

        try:
            ws.files.create_directory(f"{volume_fs_base}/{base_dir}")
        except Exception:
            pass

        ws.files.upload(dest_path, BytesIO(content))

        payload = DocumentCreate(
            entity_type="data_domain",  # Shared assets use a generic type
            entity_id=SHARED_ENTITY_ID,
            title=title,
            short_description=short_description,
            is_shared=True,
            level=level,
            inheritable=inheritable,
        )
        result = manager.create_document_record(
            db,
            data=payload,
            filename=filename,
            content_type=content_type,
            size_bytes=size_bytes,
            storage_path=dest_path,
            user_email=current_user.email if current_user else None,
        )
        
        audit_manager.log_action(
            db=db,
            username=current_user.username if current_user else 'unknown',
            ip_address=request.client.host if request.client else None,
            feature=FEATURE_ID,
            action='UPLOAD_SHARED_DOCUMENT',
            success=True,
            details={'filename': filename}
        )
        
        return result
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Failed uploading shared document")
        raise HTTPException(status_code=500, detail="Failed to upload shared document")


# =========================================================================
# Metadata Attachments Endpoints
# =========================================================================

@router.post("/entities/{entity_type}/attachments", response_model=MetadataAttachment, status_code=status.HTTP_201_CREATED)
async def attach_shared_asset(
    entity_type: str,
    entity_id: Annotated[str, Query(min_length=1, description='Entity id (may be an IRI)')],
    request: Request,
    payload: MetadataAttachmentCreate,
    db: DBSessionDep,
    audit_manager: AuditManagerDep,
    current_user: AuditCurrentUserDep,
    manager: MetadataManager = Depends(get_metadata_manager),
    user_details: UserInfo = Depends(get_user_details_from_sdk),
    auth_manager: AuthorizationManager = Depends(get_auth_manager),
    _: None = Depends(EntityTypePermissionChecker(METADATA_ENTITY_FEATURES, FeatureAccessLevel.READ_WRITE)),
):
    """Attach a shared metadata asset to an entity."""
    _refuse_shared_scope(False, entity_id)
    if not _is_uuid(payload.asset_id):
        err = NotSharedAssetError("Only shared library assets can be attached")
        raise HTTPException(status_code=400, detail=str(err)) from err
    scope = manager.get_record_scope(db, kind=payload.asset_type, id=payload.asset_id)
    if scope is not None and scope[1]:
        # An attached library note is readable on the entity, so attaching it needs library read access.
        await check_feature_permission(request, user_details, auth_manager, FEATURE_ID, FeatureAccessLevel.READ_ONLY)
    try:
        result = manager.attach_shared_asset(
            db, entity_type=entity_type, entity_id=entity_id,
            data=payload, user_email=current_user.email if current_user else None
        )
        
        audit_manager.log_action(
            db=db,
            username=current_user.username if current_user else 'unknown',
            ip_address=request.client.host if request.client else None,
            feature=FEATURE_ID,
            action='ATTACH_SHARED_ASSET',
            success=True,
            details={'entity_type': entity_type, 'entity_id': entity_id}
        )
        
        return result
    except NotSharedAssetError as err:
        raise HTTPException(status_code=400, detail=str(err)) from err
    except Exception as e:
        logger.exception("Failed attaching shared asset to %s/%s", entity_type, entity_id)
        raise HTTPException(status_code=500, detail="Failed to attach shared asset")


@router.get("/entities/{entity_type}/attachments", response_model=List[MetadataAttachment])
async def list_attachments(
    entity_type: str,
    entity_id: Annotated[str, Query(min_length=1, description='Entity id (may be an IRI)')],
    db: DBSessionDep,
    manager: MetadataManager = Depends(get_metadata_manager),
    _: None = Depends(EntityTypePermissionChecker(METADATA_ENTITY_FEATURES, FeatureAccessLevel.READ_ONLY)),
):
    """List all shared asset attachments for an entity."""
    return manager.list_attachments(db, entity_type=entity_type, entity_id=entity_id)


@router.delete("/entities/{entity_type}/attachments/{asset_type}/{asset_id}", status_code=status.HTTP_204_NO_CONTENT)
async def detach_shared_asset(
    entity_type: str,
    asset_type: str,
    asset_id: str,
    request: Request,
    entity_id: Annotated[str, Query(min_length=1, description='Entity id (may be an IRI)')],
    db: DBSessionDep,
    audit_manager: AuditManagerDep,
    current_user: AuditCurrentUserDep,
    manager: MetadataManager = Depends(get_metadata_manager),
    _: None = Depends(EntityTypePermissionChecker(METADATA_ENTITY_FEATURES, FeatureAccessLevel.READ_WRITE)),
):
    """Detach a shared metadata asset from an entity."""
    ok = manager.detach_shared_asset(
        db, entity_type=entity_type, entity_id=entity_id,
        asset_type=asset_type, asset_id=asset_id, user_email=current_user.email if current_user else None
    )
    if not ok:
        raise HTTPException(status_code=404, detail="Attachment not found")
    
    audit_manager.log_action(
        db=db,
        username=current_user.username if current_user else 'unknown',
        ip_address=request.client.host if request.client else None,
        feature=FEATURE_ID,
        action='DETACH_SHARED_ASSET',
        success=True,
        details={'entity_type': entity_type, 'entity_id': entity_id, 'asset_type': asset_type, 'asset_id': asset_id}
    )
    
    return


# =========================================================================
# Merged Metadata Endpoint (with inheritance)
# =========================================================================

@router.get("/entities/{entity_type}/metadata/merged", response_model=MergedMetadataResponse)
async def get_merged_metadata(
    entity_type: str,
    entity_id: Annotated[str, Query(min_length=1, description='Entity id (may be an IRI)')],
    contract_ids: Optional[str] = Query(None, description="Comma-separated contract IDs for inheritance"),
    max_level: int = Query(99, ge=0, le=999, description="Maximum inheritance level"),
    request: Request = None,
    db: DBSessionDep = None,
    manager: MetadataManager = Depends(get_metadata_manager),
    user_details: UserInfo = Depends(get_user_details_from_sdk),
    auth_manager: AuthorizationManager = Depends(get_auth_manager),
    _: None = Depends(EntityTypePermissionChecker(METADATA_ENTITY_FEATURES, FeatureAccessLevel.READ_ONLY)),
):
    """
    Get merged metadata for an entity, including inherited metadata from contracts.
    
    For Data Products and Datasets, pass contract_ids to include inherited metadata.
    Only metadata with level <= max_level and inheritable=True will be inherited.
    """
    contract_id_list = [cid.strip() for cid in contract_ids.split(",") if cid.strip()] if contract_ids else None
    _refuse_shared_scope(False, entity_id)
    for contract_id in contract_id_list or []:
        _refuse_shared_scope(False, contract_id)
    if contract_id_list:
        # Inherited metadata is the contracts' own, so reading it needs contract access too.
        await check_feature_permission(
            request, user_details, auth_manager,
            METADATA_ENTITY_FEATURES["data_contract"], FeatureAccessLevel.READ_ONLY,
        )
    return manager.get_merged_metadata(
        db, entity_type=entity_type, entity_id=entity_id,
        contract_ids=contract_id_list, max_level_inheritance=max_level
    )


def register_routes(app):
    app.include_router(router)
    logger.info("Metadata routes registered with prefix /api")


@router.get("/documents/{id}/content")
async def get_document_content(
    id: str,
    db: DBSessionDep,
    manager: MetadataManager = Depends(get_metadata_manager),
    ws: WorkspaceClient = Depends(get_workspace_client),
    _: None = Depends(_record_permission("document", FeatureAccessLevel.READ_ONLY, "Document not found")),
):
    doc = manager.get_document(db, id=id)
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")
    try:
        # Download file from UC Volumes. SDK returns a DownloadResponse with a generator method `.contents()`.
        downloaded = ws.files.download(doc.storage_path)

        # Log shape once to aid debugging if needed
        try:
            logger.debug(f"DownloadResponse type={type(downloaded)} attrs={dir(downloaded)}")
        except Exception:
            pass

        # SECURITY: Sanitize filename for header to prevent header injection
        safe_filename = sanitize_filename_for_header(doc.original_filename, default="document.bin")
        
        media_type = doc.content_type or "application/octet-stream"
        headers = {"Content-Disposition": f"inline; filename=\"{safe_filename}\""}

        # Preferred path: DownloadResponse.contents is a BinaryIO stream we can read in chunks
        try:
            stream = getattr(downloaded, "contents", None)
            if stream is not None and hasattr(stream, "read"):
                def chunk_iter():
                    while True:
                        chunk = stream.read(1024 * 1024)
                        if not chunk:
                            break
                        yield chunk
                media_type = doc.content_type or getattr(downloaded, "content_type", None) or "application/octet-stream"
                headers = {"Content-Disposition": f"inline; filename=\"{safe_filename}\""}
                return StreamingResponse(chunk_iter(), media_type=media_type, headers=headers)
        except Exception:
            pass

        # Fallbacks (safe_filename already defined above)
        media_type = doc.content_type or getattr(downloaded, "content_type", None) or "application/octet-stream"
        headers = {"Content-Disposition": f"inline; filename=\"{safe_filename}\""}

        if hasattr(downloaded, "read"):
            try:
                data = downloaded.read()
                return Response(content=data, media_type=media_type, headers=headers)
            except Exception:
                pass

        if isinstance(downloaded, (bytes, bytearray)):
            return Response(content=bytes(downloaded), media_type=media_type, headers=headers)

        # If all else fails, error with clear message
        raise HTTPException(status_code=500, detail="Unsupported Databricks download response; missing BinaryIO 'contents'")
    except Exception as e:
        logger.exception("Failed streaming document content for document %s", id)
        raise HTTPException(status_code=500, detail="Failed to stream document content")