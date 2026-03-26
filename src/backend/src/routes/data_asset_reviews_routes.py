from typing import List, Optional, Dict, Any, Annotated

from fastapi import APIRouter, Depends, HTTPException, status, Query, Request
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

# Import API models
from src.models.data_asset_reviews import (
    DataAssetReviewRequest as DataAssetReviewRequestApi,
    DataAssetReviewRequestCreate,
    DataAssetReviewRequestUpdateStatus,
    ReviewedAsset as ReviewedAssetApi,
    ReviewedAssetUpdate,
    AssetType,
    AssetAnalysisRequest,
    AssetAnalysisResponse
)

# Import Manager and other dependencies
from src.controller.data_asset_reviews_manager import DataAssetReviewManager
from src.controller.notifications_manager import NotificationsManager # Assuming manager is here
from src.common.database import get_db
from src.common.workspace_client import get_workspace_client_dependency
from databricks.sdk import WorkspaceClient

from src.common.authorization import PermissionChecker
from src.common.features import FeatureAccessLevel
from src.common.dependencies import (
    DBSessionDep,
    DataAssetReviewManagerDep,
    NotificationsManagerDep,
    WorkspaceClientDep,
    AuditManagerDep,
    AuditCurrentUserDep,
)

from src.common.logging import get_logger
logger = get_logger(__name__)

router = APIRouter(prefix="/api", tags=["Data Asset Reviews"])

# --- Routes (using Annotated Types directly) --- #

@router.post("/data-asset-reviews", response_model=DataAssetReviewRequestApi, status_code=status.HTTP_201_CREATED)
def create_review_request(
    request: Request,
    request_data: DataAssetReviewRequestCreate,
    db: DBSessionDep,
    audit_manager: AuditManagerDep,
    audit_user: AuditCurrentUserDep,
    manager: DataAssetReviewManagerDep,
    _: bool = Depends(PermissionChecker('data-asset-reviews', FeatureAccessLevel.READ_WRITE))
):
    """Create a new data asset review request."""
    success = False
    details = {
        "params": {
            "requester_email": request_data.requester_email,
            "reviewer_email": request_data.reviewer_email,
            "asset_count": len(request_data.asset_fqns)
        }
    }

    try:
        logger.info(f"Received request to create data asset review from {request_data.requester_email} for {request_data.reviewer_email}")
        created_request = manager.create_review_request(request_data=request_data)
        success = True
        details["request_id"] = created_request.id
        return created_request
    except ValueError as e:
        logger.warning("Value error creating review request: %s", e)
        details["exception"] = {"type": "ValueError", "message": str(e)}
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid review request")
    except HTTPException as e:
        details["exception"] = {"type": "HTTPException", "status_code": e.status_code, "detail": e.detail}
        raise
    except Exception as e:
        logger.exception("Unexpected error creating review request")
        details["exception"] = {"type": type(e).__name__, "message": str(e)}
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Internal server error creating review request.")
    finally:
        audit_manager.log_action(
            db=db,
            username=audit_user.username,
            ip_address=request.client.host if request.client else None,
            feature="data-asset-reviews",
            action="CREATE",
            success=success,
            details=details
        )

@router.get("/data-asset-reviews")
def list_review_requests(
    db: DBSessionDep,
    manager: DataAssetReviewManagerDep,
    skip: int = 0,
    limit: int = 100,
    _: bool = Depends(PermissionChecker('data-asset-reviews', FeatureAccessLevel.READ_ONLY))
):
    """Retrieve a list of data asset review requests."""
    logger.info(f"Listing data asset review requests (skip={skip}, limit={limit})")
    try:
        requests = manager.list_review_requests(skip=skip, limit=limit)
        if not requests:
            return JSONResponse(content={"items": []})
        else:
            return requests
            
    except HTTPException as http_exc:
        logger.warning(f"HTTPException caught in list_review_requests: {http_exc.status_code} - {http_exc.detail}")
        raise http_exc
    except Exception as e:
        # Catch any other exception, log it clearly, and raise a standard 500
        logger.exception(f"Unexpected error in list_review_requests: {e}") # Use logger.exception to include traceback
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, 
            detail=f"Internal server error processing request: {e}"
        )

@router.get("/data-asset-reviews/{request_id}", response_model=DataAssetReviewRequestApi)
def get_review_request(
    request_id: str,
    manager: DataAssetReviewManagerDep,
    db: DBSessionDep,
    _: bool = Depends(PermissionChecker('data-asset-reviews', FeatureAccessLevel.READ_ONLY))
):
    """Get a specific data asset review request by its ID."""
    logger.info(f"Fetching data asset review request ID: {request_id}")
    try:
        request = manager.get_review_request(request_id=request_id)
        if request is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Review request not found")
        return request
    except ValueError as e: # Catch mapping errors
         logger.error(f"Mapping error retrieving request {request_id}: {e}")
         raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"Internal data error: {e}")
    except HTTPException:
        raise
    except Exception as e:
        logger.exception(f"Error getting review request {request_id}: {e}")
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Internal server error getting review request.")

@router.put("/data-asset-reviews/{request_id}/status", response_model=DataAssetReviewRequestApi)
def update_review_request_status(
    request: Request,
    request_id: str,
    status_update: DataAssetReviewRequestUpdateStatus,
    db: DBSessionDep,
    audit_manager: AuditManagerDep,
    audit_user: AuditCurrentUserDep,
    manager: DataAssetReviewManagerDep,
    _: bool = Depends(PermissionChecker('data-asset-reviews', FeatureAccessLevel.READ_WRITE))
):
    """Update the overall status of a data asset review request."""
    success = False
    details = {
        "params": {
            "request_id": request_id,
            "new_status": status_update.status
        }
    }

    try:
        logger.info(f"Updating status for review request ID: {request_id} to {status_update.status}")
        updated_request = manager.update_review_request_status(request_id=request_id, status_update=status_update)
        if updated_request is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Review request not found")
        success = True
        return updated_request
    except ValueError as e:
        logger.warning("Value error updating status for request %s: %s", request_id, e)
        details["exception"] = {"type": "ValueError", "message": str(e)}
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid status update")
    except HTTPException as e:
        details["exception"] = {"type": "HTTPException", "status_code": e.status_code, "detail": e.detail}
        raise
    except Exception as e:
        logger.exception("Error updating status for request %s", request_id)
        details["exception"] = {"type": type(e).__name__, "message": str(e)}
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Internal server error updating request status.")
    finally:
        audit_manager.log_action(
            db=db,
            username=audit_user.username,
            ip_address=request.client.host if request.client else None,
            feature="data-asset-reviews",
            action="UPDATE",
            success=success,
            details=details
        )

@router.put("/data-asset-reviews/{request_id}/assets/{asset_id}/status", response_model=ReviewedAssetApi)
def update_reviewed_asset_status(
    request: Request,
    request_id: str,
    asset_id: str,
    asset_update: ReviewedAssetUpdate,
    db: DBSessionDep,
    audit_manager: AuditManagerDep,
    audit_user: AuditCurrentUserDep,
    manager: DataAssetReviewManagerDep,
    _: bool = Depends(PermissionChecker('data-asset-reviews', FeatureAccessLevel.READ_WRITE))
):
    """Update the status and comments of a specific asset within a review request."""
    success = False
    details = {
        "params": {
            "request_id": request_id,
            "asset_id": asset_id,
            "new_status": asset_update.status,
            "comments": asset_update.comments
        }
    }

    try:
        logger.info(f"Updating status for asset ID: {asset_id} in request {request_id} to {asset_update.status}")
        updated_asset = manager.update_reviewed_asset_status(request_id=request_id, asset_id=asset_id, asset_update=asset_update)
        if updated_asset is None:
            # Distinguish between request not found and asset not found in request
            request_exists = manager.get_review_request(request_id=request_id)
            if not request_exists:
                 raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Review request not found")
            else:
                 raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Asset not found within the specified review request")

        success = True
        return updated_asset
    except ValueError as e:
        logger.warning("Value error updating status for asset %s: %s", asset_id, e)
        details["exception"] = {"type": "ValueError", "message": str(e)}
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid status update")
    except HTTPException as e:
        details["exception"] = {"type": "HTTPException", "status_code": e.status_code, "detail": e.detail}
        raise
    except Exception as e:
        logger.exception("Error updating status for asset %s", asset_id)
        details["exception"] = {"type": type(e).__name__, "message": str(e)}
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Internal server error updating asset status.")
    finally:
        audit_manager.log_action(
            db=db,
            username=audit_user.username,
            ip_address=request.client.host if request.client else None,
            feature="data-asset-reviews",
            action="UPDATE",
            success=success,
            details=details
        )

@router.delete("/data-asset-reviews/{request_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_review_request(
    request: Request,
    request_id: str,
    db: DBSessionDep,
    audit_manager: AuditManagerDep,
    audit_user: AuditCurrentUserDep,
    manager: DataAssetReviewManagerDep,
    _: bool = Depends(PermissionChecker('data-asset-reviews', FeatureAccessLevel.ADMIN))
):
    """Delete a data asset review request."""
    success = False
    details = {
        "params": {
            "request_id": request_id
        }
    }

    try:
        logger.info(f"Deleting review request ID: {request_id}")
        deleted = manager.delete_review_request(request_id=request_id)
        if not deleted:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Review request not found")
        success = True
        return
    except HTTPException as e:
        details["exception"] = {"type": "HTTPException", "status_code": e.status_code, "detail": e.detail}
        raise
    except Exception as e:
        logger.exception(f"Error deleting review request {request_id}: {e}")
        details["exception"] = {"type": type(e).__name__, "message": str(e)}
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Internal server error deleting review request.")
    finally:
        audit_manager.log_action(
            db=db,
            username=audit_user.username,
            ip_address=request.client.host if request.client else None,
            feature="data-asset-reviews",
            action="DELETE",
            success=success,
            details=details
        )

# --- Routes for Asset Content/Preview --- #

@router.get("/data-asset-reviews/{request_id}/assets/{asset_id}/definition")
async def get_asset_definition(
    request_id: str,
    asset_id: str,
    manager: DataAssetReviewManagerDep,
    # db: DBSessionDep # No longer needed here
    _: bool = Depends(PermissionChecker('data-asset-reviews', FeatureAccessLevel.READ_ONLY))
):
    """Get the definition (e.g., SQL) for a view or function asset."""
    logger.info(f"Getting definition for asset {asset_id} in request {request_id}")
    try:
        reviewed_asset = manager.get_reviewed_asset(request_id=request_id, asset_id=asset_id)
        if not reviewed_asset:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Reviewed asset not found")

        if reviewed_asset.asset_type not in [AssetType.VIEW, AssetType.FUNCTION, AssetType.NOTEBOOK]:
             raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"Asset definition can only be fetched for VIEW, FUNCTION, or NOTEBOOK types, not {reviewed_asset.asset_type.value}")

        definition = await manager.get_asset_definition(
            asset_fqn=reviewed_asset.asset_fqn,
            asset_type=reviewed_asset.asset_type
        )

        if definition is None:
             # This might indicate asset not found by ws_client or permission issue, handled by manager logging
             raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Asset definition not found by the workspace client, or access denied.")
                 
        from fastapi.responses import PlainTextResponse
        return PlainTextResponse(content=definition)
        
    except HTTPException as e:
        raise e # Re-raise specific HTTP exceptions
    except Exception as e:
        logger.exception(f"Error getting definition for asset {asset_id}: {e}")
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Internal server error getting asset definition.")

@router.get("/data-asset-reviews/{request_id}/assets/{asset_id}/preview")
async def get_table_preview(
    request_id: str,
    asset_id: str,
    # db: DBSessionDep, # No longer needed here
    manager: DataAssetReviewManagerDep,
    limit: int = Query(25, ge=1, le=100, description="Number of rows to preview"),
    _: bool = Depends(PermissionChecker('data-asset-reviews', FeatureAccessLevel.READ_ONLY))
):
    """Get a preview of data for a table asset."""
    logger.info(f"Getting preview for asset {asset_id} (table) in request {request_id} (limit={limit})")
    try:
        reviewed_asset = manager.get_reviewed_asset(request_id=request_id, asset_id=asset_id)
        if not reviewed_asset:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Reviewed asset not found")

        if reviewed_asset.asset_type != AssetType.TABLE:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"Table preview can only be fetched for TABLE types, not {reviewed_asset.asset_type.value}")

        preview_data = await manager.get_table_preview(
            table_fqn=reviewed_asset.asset_fqn, 
            limit=limit
        )

        if preview_data is None:
             # This might indicate asset not found by ws_client or permission issue, handled by manager logging
             raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Table preview not available, or access denied by the workspace client.")
             
        return preview_data
        
    except HTTPException as e:
        raise e
    except Exception as e:
        logger.exception(f"Error getting preview for asset {asset_id}: {e}")
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Internal server error getting table preview.")

@router.post("/data-asset-reviews/{request_id}/assets/{asset_id}/analyze", response_model=AssetAnalysisResponse)
async def analyze_asset_with_llm(
    request: Request,
    request_id: str,
    asset_id: str,
    db: DBSessionDep,
    audit_manager: AuditManagerDep,
    audit_user: AuditCurrentUserDep,
    manager: DataAssetReviewManagerDep,
    _: bool = Depends(PermissionChecker('data-asset-reviews', FeatureAccessLevel.READ_ONLY))
):
    """Triggers LLM analysis for a specific asset's content."""
    success = False
    details = {
        "params": {
            "request_id": request_id,
            "asset_id": asset_id
        }
    }

    try:
        logger.info(f"Received request to analyze asset {asset_id} in request {request_id} with LLM.")

        # Extract user token from request headers (Databricks Apps context)
        user_token = request.headers.get("x-forwarded-access-token")
        if user_token:
            logger.debug("Using user token from x-forwarded-access-token header")
        else:
            logger.debug("No user token in headers, will use DATABRICKS_TOKEN")

        # 1. Fetch the reviewed asset to get its FQN and type
        reviewed_asset_api = manager.get_reviewed_asset(request_id=request_id, asset_id=asset_id)
        if not reviewed_asset_api:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Reviewed asset not found")

        details["asset_fqn"] = reviewed_asset_api.asset_fqn
        details["asset_type"] = reviewed_asset_api.asset_type.value

        # 2. Fetch the asset's definition (content) - this is an async call
        asset_content = await manager.get_asset_definition(
            asset_fqn=reviewed_asset_api.asset_fqn,
            asset_type=reviewed_asset_api.asset_type
        )

        if asset_content is None:
            if reviewed_asset_api.asset_type not in [AssetType.VIEW, AssetType.FUNCTION, AssetType.NOTEBOOK]:
                 raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"LLM content analysis currently only supports VIEW, FUNCTION, or NOTEBOOK types, not {reviewed_asset_api.asset_type.value}. Content could not be retrieved.")
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Asset content not found or not available for analysis.")

        # 3. Call the manager's analysis method with user token
        analysis_result = manager.analyze_asset_content(
            request_id=request_id,
            asset_id=asset_id,
            asset_content=asset_content,
            asset_type=reviewed_asset_api.asset_type,
            user_token=user_token
        )

        if not analysis_result:
            raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="LLM analysis failed or returned no result. Check server logs.")

        success = True
        details["analysis_completed"] = True
        return analysis_result

    except HTTPException as http_exc:
        logger.error(f"HTTPException during LLM analysis for asset {asset_id}: {http_exc.detail}")
        details["exception"] = {"type": "HTTPException", "status_code": http_exc.status_code, "detail": http_exc.detail}
        raise http_exc
    except Exception as e:
        logger.exception(f"Unexpected error during LLM analysis for asset {asset_id} in request {request_id}: {e}")
        details["exception"] = {"type": type(e).__name__, "message": str(e)}
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"An unexpected error occurred: {str(e)}")
    finally:
        audit_manager.log_action(
            db=db,
            username=audit_user.username,
            ip_address=request.client.host if request.client else None,
            feature="data-asset-reviews",
            action="ANALYZE_ASSET",
            success=success,
            details=details
        )

# --- Register Routes (if using a central registration pattern) --- #
def register_routes(app):
    """Register Data Asset Review routes with the FastAPI app."""
    app.include_router(router)
    logger.info("Data Asset Review routes registered") 