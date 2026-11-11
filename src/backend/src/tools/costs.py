"""
Costs tools for LLM.

Tools for getting cost information for data products.
"""

from typing import Any, Dict, Optional

from src.common.logging import get_logger
from src.tools.base import BaseTool, ToolContext, ToolResult, tool_failure

logger = get_logger(__name__)


class GetDataProductCostsTool(BaseTool):
    """Get cost information for data products."""
    
    name = "get_data_product_costs"
    category = "costs"
    description = "Get cost information for data products including infrastructure, HR, storage costs."
    parameters = {
        "product_id": {
            "type": "string",
            "description": "Specific product ID, or omit for all products"
        },
        "aggregate": {
            "type": "boolean",
            "description": "If true, return totals; if false, return per-product breakdown",
            "default": False
        }
    }
    required_params = []
    required_scope = "costs:read"
    
    async def execute(
        self,
        ctx: ToolContext,
        product_id: Optional[str] = None,
        aggregate: bool = False
    ) -> ToolResult:
        """Get cost information for data products."""
        logger.info(f"[get_data_product_costs] Starting - product_id={product_id}, aggregate={aggregate}")
        
        try:
            from src.db_models.costs import CostItemDb
            
            query = ctx.db.query(CostItemDb).filter(CostItemDb.entity_type == "data_product")
            
            if product_id:
                query = query.filter(CostItemDb.entity_id == product_id)
            
            items = query.all()
            logger.debug(f"[get_data_product_costs] Found {len(items)} cost items in database")
            
            if not items:
                logger.info(f"[get_data_product_costs] No cost data found")
                return ToolResult(
                    success=True,
                    data={"message": "No cost data found", "total_usd": 0}
                )
            
            if aggregate:
                # Sum all costs
                total_cents = sum(item.amount_cents for item in items)
                by_center: Dict[str, float] = {}
                for item in items:
                    center = item.cost_center or "OTHER"
                    by_center[center] = by_center.get(center, 0) + item.amount_cents / 100
                
                logger.info(f"[get_data_product_costs] SUCCESS: Aggregated {len(items)} cost items, total=${total_cents/100:.2f}")
                return ToolResult(
                    success=True,
                    data={
                        "total_usd": total_cents / 100,
                        "by_cost_center": by_center,
                        "currency": "USD",
                        "product_count": len(set(item.entity_id for item in items))
                    }
                )
            else:
                # Group by product
                by_product: Dict[str, Dict[str, Any]] = {}
                for item in items:
                    pid = item.entity_id
                    if pid not in by_product:
                        # Get product name if available
                        product_name = pid
                        if ctx.data_products_manager:
                            try:
                                product = ctx.data_products_manager.get(pid)
                                if product:
                                    product_name = product.name or pid
                            except Exception:
                                pass
                        
                        by_product[pid] = {
                            "product_id": pid,
                            "product_name": product_name,
                            "total_usd": 0,
                            "items": []
                        }
                    
                    by_product[pid]["total_usd"] += item.amount_cents / 100
                    by_product[pid]["items"].append({
                        "title": item.title,
                        "cost_center": item.cost_center,
                        "amount_usd": item.amount_cents / 100,
                        "description": item.description
                    })
                
                logger.info(f"[get_data_product_costs] SUCCESS: Found costs for {len(by_product)} products")
                return ToolResult(
                    success=True,
                    data={
                        "products": list(by_product.values()),
                        "total_usd": sum(p["total_usd"] for p in by_product.values()),
                        "currency": "USD"
                    }
                )
                
        except Exception as e:
            return ToolResult(success=False, **tool_failure("get_data_product_costs", e))

