"""API routes for data product production readiness checks."""

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.orm import Session

from src.models.entity_relationships import ReadinessCheck, ReadinessReport
from src.common.authorization import PermissionChecker
from src.common.features import FeatureAccessLevel
from src.common.dependencies import DBSessionDep
from src.common.logging import get_logger

logger = get_logger(__name__)

router = APIRouter(prefix="/api/data-products", tags=["Data Product Readiness"])
FEATURE_ID = "data-products"


def _get_managers(request: Request):
    """Get required managers from app state."""
    from src.controller.data_products_manager import DataProductsManager
    from src.controller.entity_relationships_manager import EntityRelationshipsManager
    from src.repositories.entity_relationships_repository import entity_relationship_repo

    dp_mgr: DataProductsManager = getattr(request.app.state, "data_products_manager", None)
    er_mgr: EntityRelationshipsManager = getattr(request.app.state, "entity_relationships_manager", None)
    if not dp_mgr or not er_mgr:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Required managers not configured.",
        )
    return dp_mgr, er_mgr, entity_relationship_repo


@router.get(
    "/{product_id}/readiness",
    response_model=ReadinessReport,
    dependencies=[Depends(PermissionChecker(FEATURE_ID, FeatureAccessLevel.READ_ONLY))],
)
def get_readiness_report(
    product_id: str,
    db: DBSessionDep,
    request: Request,
):
    """Check production readiness of a data product.

    Evaluates: ODPS metadata, output contracts, logical attribute mappings,
    business term linkages, upstream systems, and downstream delivery channels.
    """
    dp_mgr, er_mgr, er_repo = _get_managers(request)

    product = dp_mgr.get_product(product_id)
    if not product:
        raise HTTPException(status_code=404, detail=f"Data product {product_id} not found")

    checks = []
    product_name = product.name or product_id

    # 1. ODPS metadata present (name, description, owner)
    has_name = bool(product.name)
    has_desc = product.description and (product.description.purpose or product.description.usage)
    has_owner = bool(getattr(product, "owner_team_id", None) or getattr(product, "owner_team_name", None))
    odps_ok = has_name and has_desc and has_owner
    missing = [x for x, v in [("name", has_name), ("description", has_desc), ("owner_team", has_owner)] if not v]
    checks.append(ReadinessCheck(
        name="ODPS metadata present",
        status="pass" if odps_ok else "fail",
        detail="All required fields present" if odps_ok else f"Missing: {', '.join(missing)}",
    ))

    # 2. At least one output port / contract
    output_ports = product.outputPorts or []
    has_output = len(output_ports) > 0
    contract_count = sum(
        1 for op in output_ports
        if getattr(op, "contractId", None)
    )
    checks.append(ReadinessCheck(
        name="At least one output contract",
        status="pass" if contract_count > 0 else ("warn" if has_output else "fail"),
        detail=f"{contract_count} contract(s) linked via {len(output_ports)} output port(s)" if has_output
               else "No output ports defined",
    ))

    # 3. Key fields mapped to LogicalAttributes (via entity relationships)
    rels = er_repo.get_for_entity(db, entity_type="DataProduct", entity_id=product_id)
    dataset_rels = [r for r in rels if r.relationship_type == "hasDataset" and r.source_id == product_id]

    logical_attr_count = 0
    for dr in dataset_rels:
        ds_rels = er_repo.get_for_entity(db, entity_type="Dataset", entity_id=dr.target_id)
        for dsr in ds_rels:
            if dsr.relationship_type == "implementedBy" and dsr.source_type == "LogicalAttribute":
                logical_attr_count += 1

    dataset_count = len(dataset_rels)
    checks.append(ReadinessCheck(
        name="Key fields mapped to logical attributes",
        status="pass" if logical_attr_count >= 3 else ("warn" if logical_attr_count > 0 else "fail"),
        detail=f"{logical_attr_count} logical attribute mapping(s) across {dataset_count} dataset(s)",
    ))

    # 4. Linked to Business Terms
    term_rels = [r for r in rels if r.relationship_type == "hasTerm" and r.source_id == product_id]
    term_count = len(term_rels)
    bt_incoming = [r for r in rels
                   if r.relationship_type in ("relatesTo", "hasTerm") and r.target_id == product_id]
    total_bt = term_count + len(bt_incoming)
    checks.append(ReadinessCheck(
        name="Linked to business terms",
        status="pass" if total_bt > 0 else "warn",
        detail=f"{total_bt} business term linkage(s)",
    ))

    # 5. Upstream system defined
    system_rels = [r for r in rels if r.relationship_type == "deployedOnSystem" and r.source_id == product_id]
    depends_rels = [r for r in rels if r.relationship_type == "dependsOn" and r.source_id == product_id]
    upstream_count = len(system_rels) + len(depends_rels)
    checks.append(ReadinessCheck(
        name="Business lineage defined (upstream)",
        status="pass" if upstream_count > 0 else "fail",
        detail=f"{len(system_rels)} system(s), {len(depends_rels)} upstream product(s)",
    ))

    # 6. Downstream delivery channels
    channel_rels = [r for r in rels if r.relationship_type == "exposes" and r.source_id == product_id]
    checks.append(ReadinessCheck(
        name="Delivery channels defined",
        status="pass" if len(channel_rels) > 0 else "warn",
        detail=f"{len(channel_rels)} delivery channel(s)",
    ))

    # Overall status
    statuses = [c.status for c in checks]
    if all(s == "pass" for s in statuses):
        overall = "ready"
    elif any(s == "fail" for s in statuses):
        overall = "not_ready"
    else:
        overall = "partial"

    return ReadinessReport(
        product_id=product_id,
        product_name=product_name,
        checks=checks,
        overall=overall,
    )


def register_routes(app):
    app.include_router(router)
    logger.info("Readiness routes registered with prefix /api/data-products/{id}/readiness")
