from typing import Any, Callable, Dict, List
from sqlalchemy.orm import Session

from src.common.logging import get_logger

logger = get_logger(__name__)


def _shown(db: Session, can_see: Callable[[Any], bool], row: Any) -> bool:
    """Whether the caller may see ``row``; an error hides it (fail closed).

    Each check runs in a savepoint: on Postgres a failed statement would
    otherwise abort the transaction, and every later row would be hidden.
    """
    try:
        with db.begin_nested():
            return bool(can_see(row))
    except Exception:
        logger.exception("Approvals queue: visibility check failed for %s; hiding it", row.id)
        return False


class ApprovalsManager:
    """Manager for approvals queue and approval-related operations."""
    
    def get_approvals_queue(
        self,
        db: Session,
        *,
        can_see_contract: Callable[[Any], bool],
        can_see_product: Callable[[Any], bool],
    ) -> Dict[str, List[Dict[str, Any]]]:
        """Get items awaiting approval across different entity types.
        
        Returns a dict with keys for each entity type (contracts, products)
        containing lists of items pending approval.

        The queue is per caller (#1117): an item is listed only when the
        caller's predicate allows it (the route passes the by-id read rule of
        the entity, which includes its pending reviewers), so the queue never
        discloses an entity its page would answer 404 for.
        
        Args:
            db: Database session
            can_see_contract: Whether the caller may see a contract row
            can_see_product: Whether the caller may see a product row
            
        Returns:
            Dict with 'contracts' and 'products' keys, each containing a list of items
        """
        items: Dict[str, List[Dict[str, Any]]] = {
            'contracts': [],
            'products': []
        }
        
        # Contracts awaiting approval (proposed or under_review)
        try:
            from src.db_models.data_contracts import DataContractDb
            # A review stage that can still be approved, in the contract's own
            # lifecycle stage group (proposed / under_review by default)
            from src.controller.lifecycle_service import lifecycle_service
            q = db.query(DataContractDb).filter(lifecycle_service.category_filter(
                db, DataContractDb, 'data_contract', ['review'],
            ))
            for c in q.all():
                if not lifecycle_service.awaits_review_decision(db, 'data_contract', c):
                    continue
                if not _shown(db, can_see_contract, c):
                    continue
                items['contracts'].append({
                    'id': c.id,
                    'name': c.name,
                    'status': c.status
                })
        except Exception as e:
            logger.debug(f"Approvals queue: contracts query failed: {e}", exc_info=True)
        
        # Products awaiting steward review (proposed or under_review)
        try:
            from src.db_models.data_products import DataProductDb
            # A product enters the steward review queue once it is submitted for
            # review: request-certify transitions a pre-review product
            # (draft/sandbox) to 'proposed' (see DataProductsManager.submit_for_review,
            # ONT-CUJ-019). Mirror the contracts filter so proposed/under_review
            # products surface to stewards. Filtering on 'draft' instead listed
            # not-yet-submitted products and hid the ones actually awaiting
            # review (ONT-CUJ-020).
            from src.controller.lifecycle_service import lifecycle_service
            q = db.query(DataProductDb).filter(lifecycle_service.category_filter(
                db, DataProductDb, 'data_product', ['review'],
            ))
            for p in q.all():
                if not lifecycle_service.awaits_review_decision(db, 'data_product', p):
                    continue
                if not _shown(db, can_see_product, p):
                    continue
                items['products'].append({
                    'id': p.id,
                    'title': p.name,
                    'status': p.status
                })
        except Exception as e:
            logger.debug(f"Approvals queue: products query failed: {e}", exc_info=True)
        
        return items

