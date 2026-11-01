"""A Unity Catalog metric view behind an Ontos asset: its definition and concept links."""
from typing import Optional
from uuid import UUID

from databricks.sdk import WorkspaceClient
from databricks.sdk.errors import BadRequest, NotFound, PermissionDenied, Unauthenticated
from databricks.sdk.service.catalog import TableType
from sqlalchemy.orm import Session

from src.common.api_errors import CodedValueError
from src.common.logging import get_logger
from src.common.metric_views import parse_metric_view_definition
from src.controller.semantic_links_manager import SemanticLinksManager
from src.models.metric_views import MetricViewRead
from src.repositories.assets_repository import asset_repo

logger = get_logger(__name__)


class MetricViewNotFoundError(CodedValueError):
    """The asset is not a Unity Catalog metric view the app can read."""

    code = 'metric_view_not_found'


class UserTokenRequiredError(CodedValueError):
    """The request has no user (OBO) token to read Unity Catalog with."""

    code = 'user_token_required'


class UserClientUnavailableError(CodedValueError):
    """The user's workspace client could not be built from their token."""

    code = 'user_client_unavailable'


def _uc_fqn(location: Optional[str]) -> Optional[str]:
    """``catalog.schema.name`` from an asset's location, or None when it isn't one."""
    parts = (location or '').strip().split('.')
    if len(parts) != 3 or not all(p.strip() for p in parts):
        return None
    return '.'.join(p.strip() for p in parts)


class MetricViewsManager:
    def __init__(self, db: Session, links_manager: SemanticLinksManager):
        self._db = db
        self._links = links_manager

    def get_for_asset(self, asset_id: UUID, ws_client: Optional[WorkspaceClient]) -> MetricViewRead:
        """The metric view an asset points at (its ``location`` is the view's FQN).

        ``ws_client`` is the requesting user's client, so Unity Catalog decides
        whether they may read the definition.

        Raises ``MetricViewNotFoundError`` when the asset doesn't exist, isn't a
        Databricks asset with a ``catalog.schema.name`` location, or Unity
        Catalog doesn't return a ``METRIC_VIEW`` for it (not found, no access,
        a name it refuses, or another kind of table), and
        ``UserTokenRequiredError`` when Unity Catalog doesn't accept the user's
        token (expired or revoked).
        """
        asset = asset_repo.get(self._db, id=asset_id)
        fqn = _uc_fqn(asset.location) if asset is not None else None
        if asset is None or fqn is None or (asset.platform or '').lower() != 'databricks':
            raise MetricViewNotFoundError(
                'This asset is not a Unity Catalog metric view.', assetId=str(asset_id)
            )
        if ws_client is None:
            raise MetricViewNotFoundError(
                'The workspace client is not available.', assetId=str(asset_id)
            )
        try:
            table = ws_client.tables.get(full_name=fqn)
        except Unauthenticated:
            logger.info("Unity Catalog refused the user's token reading %s (asset %s)",
                        fqn, asset_id)
            raise UserTokenRequiredError(
                "Unity Catalog didn't accept the user's Databricks token. Sign in again."
            )
        except (NotFound, PermissionDenied, BadRequest):
            logger.info("Metric view %s of asset %s not found, not accessible or refused",
                        fqn, asset_id)
            raise MetricViewNotFoundError(
                'The metric view was not found in Unity Catalog, or access was denied.',
                assetId=str(asset_id),
            )
        if getattr(table, 'table_type', None) != TableType.METRIC_VIEW:
            raise MetricViewNotFoundError(
                'This asset is not a Unity Catalog metric view.', assetId=str(asset_id)
            )
        definition = getattr(table, 'view_definition', None) or ''
        spec = parse_metric_view_definition(definition)
        return MetricViewRead(
            definition=definition,
            metric_view=spec,
            links=self._links.list_for_metric_view(fqn, spec),
        )
