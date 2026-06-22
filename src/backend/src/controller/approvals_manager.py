from typing import Any, Dict, List
from sqlalchemy.orm import Session

from src.common.logging import get_logger

logger = get_logger(__name__)


class ApprovalsManager:
    """Manager for approvals queue and approval-related operations."""
    
    def get_approvals_queue(self, db: Session) -> Dict[str, List[Dict[str, Any]]]:
        """Get items awaiting approval across different entity types.
        
        Returns a dict with keys for each entity type (contracts, products)
        containing lists of items pending approval.
        
        Args:
            db: Database session
            
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
            q = db.query(DataContractDb).filter(
                DataContractDb.status.in_(['proposed', 'under_review'])
            )
            for c in q.all():
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
            q = db.query(DataProductDb).filter(
                DataProductDb.status.in_(['proposed', 'under_review'])
            )
            for p in q.all():
                items['products'].append({
                    'id': p.id,
                    'title': p.name,
                    'status': p.status
                })
        except Exception as e:
            logger.debug(f"Approvals queue: products query failed: {e}", exc_info=True)
        
        return items

