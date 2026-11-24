"""The by-id read rules of data products and data contracts, applied to search hits.

``GET /api/search`` checked only the feature permission, so a Data Consumer
found unpublished products and contracts (drafts, proposed, ...) that the list
and the by-id reads hide. A hit for a product or contract is kept only when the
caller may read it by id:

* product: ``GET /api/data-products/{id}`` (``_caller_can_read_product``):
  published, data-products admin, owner (draft owner, owning team, project
  member), or a pending reviewer of it (#1117). Same helpers.
* contract: ``GET /api/data-contracts/{id}`` (``readable_contract``):
  ``DataContractsManager.readable_contracts`` with data-contracts admin and the
  caller's teams.

One batch per entity kind. Fails closed: on an error the hits of that kind are
left out.
"""
from typing import Any, Dict, List, Optional, Set

from src.common.features import FeatureAccessLevel
from src.common.logging import get_logger

logger = get_logger(__name__)

PRODUCT_PREFIX = "product::"
CONTRACT_PREFIX = "contract::"


def _ids_with_prefix(results: List[Any], prefix: str) -> List[str]:
    return [
        item.id[len(prefix):] for item in results
        if (getattr(item, "id", "") or "").startswith(prefix)
    ]


def _is_feature_admin(auth_manager, effective_permissions, feature_id: str) -> bool:
    try:
        return effective_permissions is not None and auth_manager.has_permission(
            effective_permissions, feature_id, FeatureAccessLevel.ADMIN,
        )
    except Exception:
        logger.exception("Admin check failed in search for %s", feature_id)
        return False


def _team_ids(db, user) -> Set[str]:
    from src.common.product_read_rule import lookup_team_ids

    try:
        with db.begin_nested():
            return lookup_team_ids(db, user.email, user.groups or [])
    except Exception:
        logger.exception("Team lookup failed in search for %s", user.email)
        return set()


def readable_product_ids(db, ids: List[str], user, notifications_manager=None) -> Set[str]:
    """The ids of ``ids`` a caller who is not a data-products admin may read."""
    from src.common import product_read_rule as rule
    from src.common.review_access import caller_is_pending_reviewer
    from src.db_models.data_products import DataProductDb

    rows = db.query(DataProductDb).filter(DataProductDb.id.in_(ids)).all()
    team_ids: Optional[Set[str]] = None
    project_ids: Any = rule.LOOKUP
    readable: Set[str] = set()
    for row in rows:
        if rule.is_published_product(row):
            readable.add(str(row.id))
            continue
        if team_ids is None:
            team_ids = _team_ids(db, user)
            try:
                with db.begin_nested():
                    project_ids = rule.lookup_member_project_ids(
                        db, user.email, user.groups or [],
                    )
            except Exception:
                logger.exception("Project lookup failed in search for %s", user.email)
                project_ids = set()
        if rule.caller_owns_product(
            db, row, caller_email=user.email, caller_groups=user.groups or [],
            caller_team_ids=team_ids, caller_project_ids=project_ids,
        ) or caller_is_pending_reviewer(
            db, user, "data_product", str(row.id), notifications_manager,
        ):
            readable.add(str(row.id))
    return readable


def readable_contract_ids(db, ids: List[str], user, contracts_manager) -> Set[str]:
    """The ids of ``ids`` a caller who is not a data-contracts admin may read."""
    from src.db_models.data_contracts import DataContractDb

    rows = db.query(DataContractDb).filter(DataContractDb.id.in_(ids)).all()
    kept = contracts_manager.readable_contracts(
        db, rows, is_admin=False, caller_email=user.email,
        caller_team_ids=_team_ids(db, user),
    )
    return {str(c.id) for c in kept}


def apply_entity_read_rules(
    results: List[Any],
    auth_manager,
    effective_permissions: Optional[Dict[str, FeatureAccessLevel]],
    user,
    *,
    contracts_manager=None,
    notifications_manager=None,
) -> List[Any]:
    """Leave out the product and contract hits the caller may not read by id."""
    product_ids = _ids_with_prefix(results, PRODUCT_PREFIX)
    contract_ids = _ids_with_prefix(results, CONTRACT_PREFIX)
    check_products = bool(product_ids) and not _is_feature_admin(
        auth_manager, effective_permissions, "data-products",
    )
    check_contracts = bool(contract_ids) and not _is_feature_admin(
        auth_manager, effective_permissions, "data-contracts",
    )
    if not check_products and not check_contracts:
        return results

    readable_products: Set[str] = set()
    readable_contracts: Set[str] = set()
    try:
        from src.common.database import get_session_factory

        session_factory = get_session_factory()
        if session_factory:
            with session_factory() as db:
                if check_products:
                    try:
                        readable_products = readable_product_ids(
                            db, product_ids, user, notifications_manager,
                        )
                    except Exception:
                        logger.exception("Product read rule failed in search; leaving them out")
                if check_contracts and contracts_manager is not None:
                    try:
                        readable_contracts = readable_contract_ids(
                            db, contract_ids, user, contracts_manager,
                        )
                    except Exception:
                        logger.exception("Contract read rule failed in search; leaving them out")
    except Exception:
        logger.exception("Read rules failed in search; leaving out products and contracts")

    def keep(item) -> bool:
        item_id = getattr(item, "id", "") or ""
        if check_products and item_id.startswith(PRODUCT_PREFIX):
            return item_id[len(PRODUCT_PREFIX):] in readable_products
        if check_contracts and item_id.startswith(CONTRACT_PREFIX):
            return item_id[len(CONTRACT_PREFIX):] in readable_contracts
        return True

    return [item for item in results if keep(item)]
