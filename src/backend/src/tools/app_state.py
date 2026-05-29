"""
App-state snapshot tool for the Ask Ontos copilot.

Computes a small, cheap "is this workspace empty or active?" snapshot
that drives two things at runtime:

1. **Tool-callable introspection.** The LLM can invoke
   ``get_app_state`` when a user asks "how many data products do we
   have?", "is this a fresh install?", "what's our adoption?" etc.
2. **System-prompt adoption-mode preamble.** ``LlmSearchManager``
   calls :func:`get_adoption_snapshot` ONCE per chat request and feeds
   the derived ``adoption_mode`` into ``get_system_prompt``. That makes
   every conceptual answer mode-aware (onboarding tone vs operational
   tone) without requiring the LLM to call the tool explicitly.

Both call sites share :func:`get_adoption_snapshot` so the tool result
and the prompt preamble can never disagree. The snapshot is built with
direct SQLAlchemy ``count()`` queries against the entity tables — no
manager indirection (managers fetch full rows, expand relationships,
and apply permission cascades; we just want counts).

The binary `adoption_mode` (`blank` vs `active`) intentionally hinges
on *published* data products, not draft ones. A workspace with 30
draft contracts and zero published products is still "blank" from the
end-user perspective: nothing's been released to consumers yet.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict

from sqlalchemy import func
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from src.common.logging import get_logger
from src.db_models.data_contracts import DataContractDb
from src.db_models.data_domains import DataDomain
from src.db_models.data_products import DataProductDb
from src.db_models.projects import ProjectDb
from src.db_models.settings import AppRoleDb
from src.db_models.teams import TeamDb
from src.tools.base import BaseTool, ToolContext, ToolResult

logger = get_logger(__name__)


# Adoption-mode literals — string constants rather than an Enum so the
# values flow straight through Pydantic / JSON without conversion.
ADOPTION_MODE_BLANK = "blank"
ADOPTION_MODE_ACTIVE = "active"


def _count(db: Session, model_cls) -> int:
    """Run ``SELECT count(*) FROM <model.__table__>`` and return an int.

    Wrapped so a single table's count error doesn't bring down the whole
    snapshot — adoption mode is best-effort, not load-bearing for auth.
    """
    try:
        # ``func.count()`` against the PK column is the dialect-portable
        # cheap form (vs ``SELECT *`` which fetches rows).
        pk_col = list(model_cls.__table__.primary_key.columns)[0]
        return int(db.query(func.count(pk_col)).scalar() or 0)
    except SQLAlchemyError as e:
        logger.warning(
            f"[get_app_state] count({model_cls.__tablename__}) failed: {e}; "
            "returning 0"
        )
        return 0


def _count_published_products(db: Session) -> int:
    """Count data products that are visible to consumers.

    Publication state is encoded in ``DataProductDb.publication_scope``
    — a string column where ``None`` / ``'none'`` means "not published"
    and any other value (e.g. ``'organization'``, ``'public'``) means
    "published with that scope". This mirrors the marketplace filter in
    ``DataProductsManager.get_published_products``.
    """
    try:
        return int(
            db.query(func.count(DataProductDb.id))
            .filter(
                DataProductDb.publication_scope.isnot(None),
                func.lower(DataProductDb.publication_scope) != "none",
            )
            .scalar()
            or 0
        )
    except SQLAlchemyError as e:
        logger.warning(
            f"[get_app_state] count(published data_products) failed: {e}; "
            "returning 0"
        )
        return 0


def get_adoption_snapshot(db: Session) -> Dict[str, Any]:
    """Compute the shared app-state snapshot.

    Returns a dict with two top-level keys:

    - ``adoption_mode`` (str) — ``"blank"`` when no products are
      published, ``"active"`` otherwise.
    - ``counts`` (dict) — per-entity counts. Counts are non-negative
      ints (best-effort: a query error yields 0 for that one entity,
      not a raised exception).
    - ``computed_at`` (str) — ISO-8601 UTC timestamp for cache-busting
      and audit. Not used by the prompt path; surfaced via the tool.
    """
    counts: Dict[str, int] = {
        "data_products_total": _count(db, DataProductDb),
        "data_products_published": _count_published_products(db),
        "data_contracts_total": _count(db, DataContractDb),
        "domains_total": _count(db, DataDomain),
        "teams_total": _count(db, TeamDb),
        "projects_total": _count(db, ProjectDb),
        "roles_total": _count(db, AppRoleDb),
    }

    adoption_mode = (
        ADOPTION_MODE_BLANK
        if counts["data_products_published"] == 0
        else ADOPTION_MODE_ACTIVE
    )

    return {
        "adoption_mode": adoption_mode,
        "counts": counts,
        "computed_at": datetime.now(timezone.utc).isoformat(),
    }


class GetAppStateTool(BaseTool):
    """Introspect the current workspace's adoption state.

    Returns total / published counts for the headline entities and a
    binary ``adoption_mode`` flag (``blank`` if no products are
    published, otherwise ``active``). Useful for questions like
    "how many data products do we have?", "is anyone using Ontos
    yet?", "what's our adoption?".

    No parameters. No scope gate — counts are not sensitive.
    """

    name = "get_app_state"
    category = "app_state"
    description = (
        "Get a snapshot of the current Ontos workspace's adoption "
        "state: total and published counts of data products, data "
        "contracts, domains, teams, projects, and roles. Also returns "
        "a binary 'adoption_mode' ('blank' if no data products are "
        "published, 'active' otherwise) — use this to tailor your "
        "framing (onboarding vs operational). Takes no parameters."
    )
    parameters: Dict[str, Any] = {}
    required_params: list = []
    required_scope = None  # type: ignore[assignment]

    async def execute(self, ctx: ToolContext, **kwargs) -> ToolResult:
        # No params; ignore kwargs (the LLM occasionally passes empty
        # dicts or unrelated keys, which we want to tolerate silently).
        logger.info("[get_app_state] computing adoption snapshot")
        try:
            snapshot = get_adoption_snapshot(ctx.db)
        except Exception as e:
            logger.error(f"[get_app_state] snapshot failed: {e}", exc_info=True)
            return ToolResult(
                success=False,
                error=f"failed to compute app-state snapshot: {type(e).__name__}: {e}",
            )

        logger.info(
            f"[get_app_state] mode={snapshot['adoption_mode']} "
            f"counts={snapshot['counts']}"
        )
        return ToolResult(success=True, data=snapshot)
