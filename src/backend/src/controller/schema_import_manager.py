"""
Schema Import Manager

Bridges external connectors with persisted Ontos assets.  Provides browse,
preview, and import operations.
"""

import threading
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Optional, Set
from uuid import UUID

from sqlalchemy import func
from sqlalchemy.orm import Session
from sqlalchemy.orm.attributes import flag_modified

from src.common.logging import get_logger
from src.connectors.base import AssetConnector, LineageLink, ListAssetsOptions
from src.models.assets import AssetInfo
from src.controller.connections_manager import ConnectionsManager
from src.controller.assets_manager import AssetsManager
from src.controller.metric_view_consistency_manager import (
    STORE_KEY as METRIC_VIEW_PROPERTY, build_stored_metric_view, store_metric_view,
)
from src.db_models.assets import AssetDb, AssetTypeDb
from src.db_models.connections import ConnectionDb
from src.models.assets import (
    IMPORTED_KEYS_PROPERTY,
    METRIC_VIEW_ASSET_TYPE,
    AssetCreate,
    AssetRelationshipCreate,
    AssetStatus,
    UnifiedAssetType,
)
from src.models.schema_import import (
    BrowseNode,
    BrowseResponse,
    ImportDepth,
    ImportMode,
    ImportPreviewItem,
    ImportRequest,
    ImportResult,
    ImportResultItem,
)
from src.db_models.entity_relationships import EntityRelationshipDb
from src.repositories.assets_repository import asset_repo, asset_type_repo
from src.repositories.connections_repository import connections_repo
from src.repositories.app_settings_repository import app_settings_repo

logger = get_logger(__name__)

# Persisted app_settings key (and bounds) for the per-path child fetch limit.
# The bounds mirror the connector contract (ListAssetsOptions: 1..10000).
# The default matches Settings.SCHEMA_IMPORT_CHILD_LIMIT and preserves the
# historic hardcoded value; the runtime source of truth is the persisted
# app_settings row (written by SettingsManager), read here per request.
_CHILD_LIMIT_SETTING_KEY = "SCHEMA_IMPORT_CHILD_LIMIT"
_CHILD_LIMIT_DEFAULT = 500
_CHILD_LIMIT_MIN = 1
_CHILD_LIMIT_MAX = 10000


# ---------------------------------------------------------------------------
# UnifiedAssetType  ->  (Ontos AssetType name, relationship from parent)
# ---------------------------------------------------------------------------

_TYPE_MAP: Dict[str, tuple] = {
    # Databricks / Unity Catalog — structural containers
    UnifiedAssetType.UC_CATALOG.value: ("Catalog", "hasCatalog"),
    UnifiedAssetType.UC_SCHEMA.value: ("Schema", "hasSchema"),
    # Databricks / Unity Catalog — leaf assets
    UnifiedAssetType.UC_TABLE.value: ("Table", "hasTable"),
    UnifiedAssetType.UC_VIEW.value: ("View", "hasView"),
    UnifiedAssetType.UC_MATERIALIZED_VIEW.value: ("View", "hasView"),
    UnifiedAssetType.UC_METRIC.value: (METRIC_VIEW_ASSET_TYPE, "hasView"),
    UnifiedAssetType.UC_STREAMING_TABLE.value: ("Table", "hasTable"),
    UnifiedAssetType.UC_FUNCTION.value: ("System", "hasPart"),
    UnifiedAssetType.UC_MODEL.value: ("ML Model", "hasPart"),
    UnifiedAssetType.UC_VOLUME.value: ("System", "hasPart"),
    # BigQuery — structural containers
    UnifiedAssetType.BQ_PROJECT.value: ("Catalog", "hasCatalog"),
    UnifiedAssetType.BQ_DATASET.value: ("Schema", "hasSchema"),
    # BigQuery — leaf assets
    UnifiedAssetType.BQ_TABLE.value: ("Table", "hasTable"),
    UnifiedAssetType.BQ_VIEW.value: ("View", "hasView"),
    UnifiedAssetType.BQ_MATERIALIZED_VIEW.value: ("View", "hasView"),
    UnifiedAssetType.BQ_EXTERNAL_TABLE.value: ("Table", "hasTable"),
    UnifiedAssetType.BQ_ROUTINE.value: ("System", "hasPart"),
    UnifiedAssetType.BQ_MODEL.value: ("ML Model", "hasPart"),
    # Snowflake — structural containers
    UnifiedAssetType.SNOWFLAKE_DATABASE.value: ("Catalog", "hasCatalog"),
    UnifiedAssetType.SNOWFLAKE_SCHEMA.value: ("Schema", "hasSchema"),
    # Snowflake — leaf assets
    UnifiedAssetType.SNOWFLAKE_TABLE.value: ("Table", "hasTable"),
    UnifiedAssetType.SNOWFLAKE_VIEW.value: ("View", "hasView"),
    UnifiedAssetType.SNOWFLAKE_MATERIALIZED_VIEW.value: ("View", "hasView"),
    UnifiedAssetType.SNOWFLAKE_FUNCTION.value: ("System", "hasPart"),
    UnifiedAssetType.SNOWFLAKE_PROCEDURE.value: ("System", "hasPart"),
    # Kafka
    UnifiedAssetType.KAFKA_TOPIC.value: ("Dataset", "hasDataset"),
    UnifiedAssetType.KAFKA_SCHEMA.value: ("Dataset", "hasDataset"),
    # Power BI
    UnifiedAssetType.POWERBI_DATASET.value: ("Dataset", "hasDataset"),
    UnifiedAssetType.POWERBI_DASHBOARD.value: ("Dashboard", "hasPart"),
    UnifiedAssetType.POWERBI_REPORT.value: ("Dashboard", "hasPart"),
    # Tableau
    UnifiedAssetType.TABLEAU_PROJECT.value: ("Folder", "hasPart"),
    UnifiedAssetType.TABLEAU_WORKBOOK.value: ("Report", "hasPart"),
    UnifiedAssetType.TABLEAU_DASHBOARD.value: ("Dashboard", "hasPart"),
    UnifiedAssetType.TABLEAU_SHEET.value: ("Dashboard", "hasPart"),
    UnifiedAssetType.TABLEAU_DATASOURCE.value: ("Semantic Model", "hasPart"),
}

# Container node types used for recursive browsing (list_containers returns
# these types). They are now also importable via _TYPE_MAP above.
_CONTAINER_TYPES = {"catalog", "schema", "dataset", "database", "project"}

# Leaf asset types whose children (columns) come from schema_info, not from
# list_assets / list_containers.  Recursing further would re-list siblings.
_LEAF_ASSET_TYPES = {
    UnifiedAssetType.UC_TABLE.value,
    UnifiedAssetType.UC_VIEW.value,
    UnifiedAssetType.UC_MATERIALIZED_VIEW.value,
    UnifiedAssetType.UC_METRIC.value,
    UnifiedAssetType.UC_STREAMING_TABLE.value,
    UnifiedAssetType.BQ_TABLE.value,
    UnifiedAssetType.BQ_VIEW.value,
    UnifiedAssetType.BQ_MATERIALIZED_VIEW.value,
    UnifiedAssetType.BQ_EXTERNAL_TABLE.value,
    UnifiedAssetType.SNOWFLAKE_TABLE.value,
    UnifiedAssetType.SNOWFLAKE_VIEW.value,
    UnifiedAssetType.SNOWFLAKE_MATERIALIZED_VIEW.value,
    UnifiedAssetType.BQ_ROUTINE.value,
    UnifiedAssetType.BQ_MODEL.value,
    UnifiedAssetType.UC_FUNCTION.value,
    UnifiedAssetType.UC_MODEL.value,
    UnifiedAssetType.SNOWFLAKE_FUNCTION.value,
    UnifiedAssetType.SNOWFLAKE_PROCEDURE.value,
    UnifiedAssetType.TABLEAU_DASHBOARD.value,
    UnifiedAssetType.TABLEAU_SHEET.value,
    UnifiedAssetType.TABLEAU_DATASOURCE.value,
}


@dataclass
class _SyncWalk:
    """What a sync-mode walk found beyond the preview items."""
    # Existing assets in unchanged subtrees: seen in the source, nothing to fetch
    seen_ids: Set[UUID] = field(default_factory=set)
    # Why the walk may have missed source items
    incomplete_reasons: List[str] = field(default_factory=list)


def _as_utc(value: Any) -> Optional[datetime]:
    if isinstance(value, str):
        try:
            value = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
    if not isinstance(value, datetime):
        return None
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)


class SchemaImportManager:
    """Manages browsing remote systems and importing their structure as Ontos assets."""

    def __init__(
        self,
        connections_manager: ConnectionsManager,
        assets_manager: AssetsManager,
        snapshot_manager: Optional[Any] = None,
    ):
        self._connections = connections_manager
        self._assets = assets_manager
        self._snapshot_manager = snapshot_manager

    @property
    def _snapshots(self):
        if self._snapshot_manager is None:
            from src.controller.dashboard_snapshot_manager import DashboardSnapshotManager
            self._snapshot_manager = DashboardSnapshotManager()
        return self._snapshot_manager

    def _child_limit(self, db: Session) -> int:
        """Resolve the per-path child fetch limit.

        Precedence: persisted General Setting (SCHEMA_IMPORT_CHILD_LIMIT) →
        module default (500, matching Settings.SCHEMA_IMPORT_CHILD_LIMIT). The
        value is clamped to the connector contract's 1..10000 range so a
        stale/invalid persisted value can never violate ListAssetsOptions.
        """
        raw = app_settings_repo.get_by_key(db, _CHILD_LIMIT_SETTING_KEY)
        if raw is None:
            limit = _CHILD_LIMIT_DEFAULT
        else:
            try:
                limit = int(raw)
            except (ValueError, TypeError):
                logger.warning(
                    f"Invalid {_CHILD_LIMIT_SETTING_KEY} value '{raw}'; falling back to {_CHILD_LIMIT_DEFAULT}"
                )
                limit = _CHILD_LIMIT_DEFAULT
        return max(_CHILD_LIMIT_MIN, min(_CHILD_LIMIT_MAX, limit))

    # ------------------------------------------------------------------
    # Browse
    # ------------------------------------------------------------------

    def browse(
        self,
        db: Session,
        connection_id: UUID,
        path: Optional[str] = None,
    ) -> BrowseResponse:
        """Browse the remote system hierarchy for a given connection."""
        connector = self._connections.get_connector_for_connection(connection_id)
        if connector is None:
            raise ValueError(f"Connection '{connection_id}' not found or connector unavailable")

        nodes: List[BrowseNode] = []
        browse_error = None
        browse_error_detail = None

        # Use list_containers for top-level / container navigation
        try:
            containers = connector.list_containers(parent_path=path)
        except Exception as exc:
            logger.warning(f"Connector error browsing {connection_id}: {exc}")
            browse_error = "Connection error"
            browse_error_detail = str(exc)
            containers = []

        # Sort containers alphabetically (case-insensitive) so the tree is
        # scannable regardless of the order the connector/API returns them.
        containers = sorted(containers, key=lambda c: (c.get("name") or "").lower())

        for c in containers:
            nodes.append(BrowseNode(
                name=c.get("name", ""),
                node_type=c.get("type", "unknown").lower(),
                path=c.get("path", ""),
                has_children=c.get("has_children", False),
                description=c.get("comment"),
                connector_type=connector.connector_type,
            ))

        # Also list leaf assets at this path
        child_limit = self._child_limit(db)
        truncated = False
        try:
            options = ListAssetsOptions(path=path or "", limit=child_limit)
            assets = connector.list_assets(options=options)
            # A full page back from the connector means there may be more leaf
            # assets than the configured limit — signal truncation to the UI.
            # Only when this level is a *leaf-asset* level, though: at container
            # levels (catalogs → schemas) list_containers already returned the
            # complete, unbounded set and this list_assets call just re-lists the
            # same containers (deduped below), so a full page here is not real
            # truncation. Guarding on `not containers` avoids that false positive.
            if not containers and len(assets) >= child_limit:
                truncated = True
            # Sort leaf assets alphabetically within their group; container
            # nodes stay first (above), columns keep metadata order (below).
            assets = sorted(assets, key=lambda a: (a.name or "").lower())
            container_paths = {n.path for n in nodes}
            for asset in assets:
                if asset.identifier in container_paths:
                    continue
                nodes.append(BrowseNode(
                    name=asset.name,
                    node_type=_display_type(asset.asset_type),
                    path=asset.identifier,
                    has_children=_has_children(asset.asset_type),
                    description=asset.description,
                    asset_type=asset.asset_type.value if asset.asset_type else None,
                    connector_type=connector.connector_type,
                ))
        except Exception as exc:
            logger.debug(f"list_assets at path '{path}' failed (OK for top-level): {exc}")

        # Enrich with column nodes when the current path identifies a leaf asset
        # whose metadata exposes a column schema. Columns are not "listable"
        # siblings — they live inside the asset's metadata. Failures here must
        # degrade silently to listing-only nodes (see PRD: Failure model).
        if path:
            try:
                metadata = connector.get_asset_metadata(path)
                schema_info = getattr(metadata, "schema_info", None) if metadata else None
                columns = getattr(schema_info, "columns", None) if schema_info else None
                if columns:
                    existing_paths = {n.path for n in nodes}
                    for col in columns:
                        col_path = f"{path}.{col.name}"
                        if col_path in existing_paths:
                            continue
                        nodes.append(BrowseNode(
                            name=col.name,
                            node_type="column",
                            path=col_path,
                            has_children=False,
                            description=getattr(col, "description", None),
                            connector_type=connector.connector_type,
                        ))
                        existing_paths.add(col_path)
            except Exception as exc:
                logger.debug(f"Column enrichment for path '{path}' failed: {exc}")

        return BrowseResponse(
            connection_id=connection_id,
            path=path,
            nodes=nodes,
            error=browse_error,
            error_detail=browse_error_detail,
            truncated=truncated,
            truncated_at=child_limit if truncated else None,
        )

    # ------------------------------------------------------------------
    # Preview
    # ------------------------------------------------------------------

    def preview_import(
        self,
        db: Session,
        request: ImportRequest,
    ) -> List[ImportPreviewItem]:
        """Dry-run: compute what assets would be created or skipped."""
        connector = self._connections.get_connector_for_connection(request.connection_id)
        if connector is None:
            raise ValueError(f"Connection '{request.connection_id}' not found or connector unavailable")

        items: List[ImportPreviewItem] = []
        selected_set = set(request.selected_paths)
        expanded = self._expand_with_ancestors(request.selected_paths)

        # Prepend System preview item
        system_item = self._build_system_preview_item(db, request.connection_id, connector)
        if system_item:
            items.append(system_item)

        for path, parent_path, is_selected in expanded:
            self._collect_items(
                db=db,
                connector=connector,
                path=path,
                depth=request.depth if is_selected else ImportDepth.SELECTED_ONLY,
                items=items,
                parent_path=parent_path,
                current_depth=0,
                _is_ancestor=not is_selected,
            )

        return items

    # ------------------------------------------------------------------
    # Execute import
    # ------------------------------------------------------------------

    def execute_import(
        self,
        db: Session,
        request: ImportRequest,
        current_user_id: str,
        progress_callback: Optional[Callable[[int, int, "ImportResult"], None]] = None,
        cancel_event: Optional["threading.Event"] = None,
    ) -> ImportResult:
        """Import selected resources (and nested children) as Ontos assets.

        Args:
            progress_callback: optional ``(processed, total, result)`` hook invoked
                as assets are created, so an async caller can persist live progress.
            cancel_event: optional ``threading.Event``; when set, the creation loop
                stops early and the (partial) result is returned. The caller inspects
                the event to record a ``cancelled`` status.
        """
        connector = self._connections.get_connector_for_connection(request.connection_id)
        if connector is None:
            raise ValueError(f"Connection '{request.connection_id}' not found or connector unavailable")

        excluded = set(request.excluded_paths)
        path_mappings = request.path_mappings or {}

        # 0. Resolve System: use mapped asset if provided, otherwise auto-resolve
        system_path = f"__system__{request.connection_id}"
        if system_path in path_mappings:
            system_asset_id = path_mappings[system_path]
        elif system_path not in excluded:
            system_asset_id = self._resolve_system_asset(
                db, request.connection_id, connector, current_user_id,
            )
        else:
            system_asset_id = None

        # 1. Collect all items to import (ancestors first so parents exist)
        sync = request.mode == ImportMode.SYNC
        walk = _SyncWalk() if sync else None
        preview_items: List[ImportPreviewItem] = []
        expanded = self._expand_with_ancestors(request.selected_paths)
        for path, parent_path, is_selected in expanded:
            self._collect_items(
                db=db,
                connector=connector,
                path=path,
                depth=request.depth if is_selected else ImportDepth.SELECTED_ONLY,
                items=preview_items,
                parent_path=parent_path,
                current_depth=0,
                walk=walk,
            )

        result = ImportResult()
        result.system_asset_id = system_asset_id
        if walk is not None:
            result.incomplete_reasons.extend(walk.incomplete_reasons)

        # path -> created asset UUID (used for relationship wiring)
        created_assets: Dict[str, UUID] = {}
        type_cache: Dict[str, Any] = {}
        metadata_cache: Dict[str, Any] = {}

        # 2. Create assets (parents before children — items are in BFS order)
        total_items = len(preview_items)
        processed = 0
        if progress_callback:
            progress_callback(0, total_items, result)

        for item in preview_items:
            # Cooperative cancellation: stop before starting the next item.
            if cancel_event is not None and cancel_event.is_set():
                logger.info("Import cancelled after %d/%d items", processed, total_items)
                break

            processed += 1
            if progress_callback:
                progress_callback(processed, total_items, result)

            # Skip items the user explicitly excluded
            if item.path in excluded:
                continue

            # Use mapped existing asset instead of creating
            if item.path in path_mappings:
                mapped_id = path_mappings[item.path]
                created_assets[item.path] = mapped_id
                result.skipped += 1
                result.items.append(ImportResultItem(
                    path=item.path,
                    name=item.name,
                    asset_type=item.asset_type,
                    action="skipped",
                    asset_id=mapped_id,
                    parent_path=item.parent_path,
                ))
                continue

            if not item.will_create:
                if item.asset_type == METRIC_VIEW_ASSET_TYPE and item.existing_asset_id:
                    # Unity Catalog reports a metric view here: convert a legacy View
                    # asset (no-op when it already is a Metric View). In a savepoint and
                    # without committing, so a failure drops only this conversion and the
                    # import goes on; the conversion is committed with the import.
                    try:
                        with db.begin_nested():
                            self._assets.retype_asset(
                                db, asset_id=item.existing_asset_id, from_type="View",
                                to_type=METRIC_VIEW_ASSET_TYPE, current_user_id=current_user_id,
                                commit=False,
                            )
                    except Exception:
                        logger.error("Failed to convert the View asset at %s to a Metric View",
                                     item.path, exc_info=True)
                        message = "The existing View asset could not be converted to a Metric View."
                        result.errors += 1
                        result.error_messages.append(f"{item.path}: {message}")
                        result.items.append(ImportResultItem(
                            path=item.path,
                            name=item.name,
                            asset_type=item.asset_type,
                            action="error",
                            asset_id=item.existing_asset_id,
                            error=message,
                            parent_path=item.parent_path,
                        ))
                        # Still a View: no relationships are wired to it as a Metric View
                        continue
                    self._refresh_metric_view(db, connector, item)
                action = "skipped"
                if sync and item.needs_refresh and item.existing_asset_id:
                    try:
                        with db.begin_nested():
                            self._refresh_existing(db, connector, item, metadata_cache, request.connection_id)
                        action = "refreshed"
                    except Exception as exc:
                        logger.error(f"Failed to refresh asset for '{item.path}': {exc}", exc_info=True)
                        result.errors += 1
                        result.error_messages.append(f"{item.path}: {exc}")
                        action = "error"
                if action == "refreshed":
                    result.refreshed += 1
                elif action == "skipped":
                    result.skipped += 1
                result.items.append(ImportResultItem(
                    path=item.path,
                    name=item.name,
                    asset_type=item.asset_type,
                    action=action,
                    asset_id=item.existing_asset_id,
                    parent_path=item.parent_path,
                ))
                if item.existing_asset_id:
                    created_assets[item.path] = item.existing_asset_id
                continue

            try:
                asset_read = self._create_asset_from_item(
                    db=db,
                    connector=connector,
                    item=item,
                    current_user_id=current_user_id,
                    _type_cache=type_cache,
                    _metadata_cache=metadata_cache,
                    connection_id=request.connection_id,
                )
                created_assets[item.path] = asset_read.id
                result.created += 1
                result.items.append(ImportResultItem(
                    path=item.path,
                    name=item.name,
                    asset_type=item.asset_type,
                    action="created",
                    asset_id=asset_read.id,
                    parent_path=item.parent_path,
                ))
            except Exception as exc:
                logger.error(f"Failed to create asset for '{item.path}': {exc}", exc_info=True)
                result.errors += 1
                result.error_messages.append(f"{item.path}: {exc}")
                result.items.append(ImportResultItem(
                    path=item.path,
                    name=item.name,
                    asset_type=item.asset_type,
                    action="error",
                    error=str(exc),
                    parent_path=item.parent_path,
                ))

        if sync:
            if cancel_event is not None and cancel_event.is_set():
                result.incomplete_reasons.append("cancelled")
            if result.errors:
                result.incomplete_reasons.append(f"{result.errors} item(s) failed")
            seen = set(walk.seen_ids) | {
                created_assets[i.path] for i in preview_items if i.path in created_assets
            }
            result.seen_asset_ids = sorted(seen, key=str)

        # 3. Wire relationships (both asset_relationships and entity_relationships)
        # Build a lookup from path -> (asset_type_name, asset_id) for entity relationships
        path_to_type: Dict[str, str] = {}
        for item in preview_items:
            if item.path in created_assets:
                path_to_type[item.path] = item.asset_type

        for item in preview_items:
            if item.parent_path and item.parent_path in created_assets and item.path in created_assets:
                self._write_relationship(
                    db,
                    source_id=created_assets[item.parent_path],
                    source_type=path_to_type.get(item.parent_path, "Asset"),
                    target_id=created_assets[item.path],
                    target_type=path_to_type.get(item.path, "Asset"),
                    rel_type=self._relationship_type_for(item.asset_type),
                    current_user_id=current_user_id,
                )

        # 4. Wire System -> top-level Catalog/Schema assets
        if system_asset_id:
            for item in preview_items:
                if item.parent_path is None and item.path in created_assets:
                    self._write_relationship(
                        db,
                        source_id=system_asset_id,
                        source_type="System",
                        target_id=created_assets[item.path],
                        target_type=item.asset_type,
                        rel_type=self._relationship_type_for(item.asset_type),
                        current_user_id=current_user_id,
                    )

        # A sync revisits only what is new or changed: lineage and snapshots of
        # unchanged assets are as they were (and fetching them is what a sync saves)
        touched = preview_items
        if sync:
            changed = {i.path for i in result.items if i.action in ("created", "refreshed")}
            touched = [i for i in preview_items if i.path in changed]

        # 5. Lineage the connector declares (e.g. BI data source -> warehouse table)
        self._wire_lineage(
            db, connector, touched, created_assets, path_to_type, metadata_cache, result, current_user_id,
        )

        # 6. Snapshots of the dashboards the connector renders
        self._capture_snapshots(
            db, connector, touched, created_assets, metadata_cache, result, current_user_id,
            connection_id=request.connection_id,
        )

        return result

    def _write_relationship(
        self,
        db: Session,
        *,
        source_id: UUID,
        source_type: str,
        target_id: UUID,
        target_type: str,
        rel_type: str,
        current_user_id: str,
    ) -> None:
        """Write an asset relationship and its entity-relationship mirror (shown on detail pages)."""
        try:
            self._assets.add_relationship(
                db,
                rel_in=AssetRelationshipCreate(
                    source_asset_id=source_id,
                    target_asset_id=target_id,
                    relationship_type=rel_type,
                ),
                current_user_id=current_user_id,
            )
        except Exception as exc:
            logger.debug(f"Relationship {source_id} -{rel_type}-> {target_id}: {exc}")

        try:
            existing = db.query(EntityRelationshipDb).filter(
                EntityRelationshipDb.source_type == source_type,
                EntityRelationshipDb.source_id == str(source_id),
                EntityRelationshipDb.target_type == target_type,
                EntityRelationshipDb.target_id == str(target_id),
                EntityRelationshipDb.relationship_type == rel_type,
            ).first()
            if not existing:
                db.add(EntityRelationshipDb(
                    source_type=source_type,
                    source_id=str(source_id),
                    target_type=target_type,
                    target_id=str(target_id),
                    relationship_type=rel_type,
                    created_by=current_user_id,
                ))
                db.flush()
        except Exception as exc:
            logger.debug(f"Entity relationship {source_id} -{rel_type}-> {target_id}: {exc}")

    def _wire_lineage(
        self,
        db: Session,
        connector: AssetConnector,
        preview_items: List[ImportPreviewItem],
        created_assets: Dict[str, UUID],
        path_to_type: Dict[str, str],
        metadata_cache: Dict[str, Any],
        result: ImportResult,
        current_user_id: str,
    ) -> None:
        """Resolve the connector's lineage links to Ontos assets and write them.

        Targets that are not in Ontos (e.g. a warehouse table that was never
        imported) are reported as import warnings, not errors.
        """
        for item in preview_items:
            if item.asset_type == "Column" or item.path not in created_assets:
                continue
            meta = metadata_cache.get(item.path)
            if meta is None:
                try:
                    meta = connector.get_asset_metadata(item.path)
                except Exception as exc:
                    logger.debug(f"No metadata for lineage of '{item.path}': {exc}")
                    continue
            if meta is None:
                continue
            try:
                links = _connector_hook(connector, "lineage_links", item.path, meta, default=[])
            except Exception as exc:
                logger.warning(f"Lineage for '{item.path}' failed: {exc}")
                continue

            for link in links:
                source_id = created_assets.get(link.source_path)
                if source_id is None:
                    continue
                target = self._resolve_lineage_target(db, connector, link, created_assets)
                if target is None:
                    reference = link.target_location or link.target_path
                    result.warnings.append(
                        f"{link.source_path}: {link.relationship_type} target '{reference}' is not in Ontos"
                    )
                    continue
                target_id, target_type = target
                self._write_relationship(
                    db,
                    source_id=source_id,
                    source_type=path_to_type.get(link.source_path, "Asset"),
                    target_id=target_id,
                    target_type=target_type,
                    rel_type=link.relationship_type,
                    current_user_id=current_user_id,
                )

    def _capture_snapshots(
        self,
        db: Session,
        connector: AssetConnector,
        preview_items: List[ImportPreviewItem],
        created_assets: Dict[str, UUID],
        metadata_cache: Dict[str, Any],
        result: ImportResult,
        current_user_id: str,
        connection_id: Optional[UUID] = None,
    ) -> None:
        """Capture snapshots of imported dashboards; failures are warnings and never stop the import."""
        for item in preview_items:
            if item.asset_type == "Column" or item.path not in created_assets:
                continue
            meta = metadata_cache.get(item.path)
            if meta is None and item.asset_type == "Dashboard":
                # Already imported earlier: its snapshot may still need a refresh
                try:
                    meta = connector.get_asset_metadata(item.path)
                except Exception as exc:
                    logger.debug(f"No metadata for snapshot of '{item.path}': {exc}")
            if meta is None or not _connector_hook(connector, "wants_snapshot", meta, default=False):
                continue
            asset = asset_repo.get(db, id=created_assets[item.path])
            if asset is None:
                continue
            # Assets imported earlier: current source timestamp (so changed dashboards
            # are re-rendered) and the connection (so they can be refreshed later)
            fresh = _connector_hook(connector, "import_properties", meta, default={}).get("source_updated_at")
            props = dict(asset.properties or {})
            if (fresh and props.get("source_updated_at") != fresh) or (connection_id and not props.get("connection_id")):
                props["source_updated_at"] = fresh or props.get("source_updated_at")
                props.setdefault("connection_id", str(connection_id) if connection_id else None)
                asset.properties = props
                flag_modified(asset, "properties")
                db.flush()
            try:
                with db.begin_nested():
                    state = self._snapshots.capture(db, asset=asset, connector=connector, current_user=current_user_id)
            except Exception as exc:
                logger.warning(f"Snapshot of '{item.path}' failed: {exc}", exc_info=True)
                result.warnings.append(f"{item.path}: snapshot failed ({exc})")
                continue
            status = state.get("status")
            if status not in ("ok", "opted_out"):
                detail = "; ".join(state.get("risks") or []) or state.get("error") or ""
                result.warnings.append(f"{item.path}: snapshot {status}" + (f" ({detail})" if detail else ""))

    @staticmethod
    def _resolve_lineage_target(
        db: Session,
        connector: AssetConnector,
        link: LineageLink,
        created_assets: Dict[str, UUID],
    ) -> Optional[tuple]:
        """(asset id, asset type name) of a link target, or None when it is not in Ontos."""
        query = db.query(AssetDb.id, AssetTypeDb.name).join(AssetTypeDb, AssetDb.asset_type_id == AssetTypeDb.id)
        if link.target_path:
            if link.target_path in created_assets:
                row = query.filter(AssetDb.id == created_assets[link.target_path]).first()
            else:
                row = query.filter(
                    AssetDb.platform == connector.connector_type, AssetDb.location == link.target_path,
                ).first()
        elif link.target_location:
            query = query.filter(
                func.lower(AssetDb.location) == link.target_location.lower(),
                AssetDb.platform != connector.connector_type,
            )
            if link.target_asset_types:
                query = query.filter(AssetTypeDb.name.in_(link.target_asset_types))
            row = query.first()
        else:
            row = None
        return (row[0], row[1]) if row else None

    def _refresh_metric_view(
        self, db: Session, connector: AssetConnector, item: ImportPreviewItem,
    ) -> None:
        """Store the current spec and fingerprints on a re-imported Metric View (#1263).

        In a savepoint: a failure is logged and leaves the stored ones as they were.
        """
        try:
            meta = connector.get_asset_metadata(item.path)
            spec = (meta.properties or {}).get(METRIC_VIEW_PROPERTY) if meta else None
            asset = asset_repo.get(db, id=item.existing_asset_id)
            if spec and asset is not None:
                with db.begin_nested():
                    store_metric_view(db, asset, spec)
        except Exception:
            logger.warning("Could not refresh the metric view fingerprints of %s",
                           item.path, exc_info=True)

    # ------------------------------------------------------------------
    # Ancestor expansion
    # ------------------------------------------------------------------

    @staticmethod
    def _expand_with_ancestors(
        selected_paths: List[str],
    ) -> List[tuple]:
        """Expand selected paths to include ancestor paths (catalog, schema).

        Returns a list of ``(path, parent_path, is_selected)`` tuples ordered
        so that ancestors are processed before their descendants.  Duplicates
        are removed so each path appears at most once.  ``is_selected`` is
        *True* only for paths that were in the original *selected_paths* list;
        auto-added ancestors are marked *False*.

        Example:
          Input:  ["cat.sch.table1", "cat.sch.table2"]
          Output: [("cat", None, False),
                   ("cat.sch", "cat", False),
                   ("cat.sch.table1", "cat.sch", True),
                   ("cat.sch.table2", "cat.sch", True)]
        """
        seen: set = set()
        selected_set: set = set(selected_paths)
        result: List[tuple] = []

        for selected in selected_paths:
            parts = selected.split(".")
            for i in range(1, len(parts) + 1):
                path = ".".join(parts[:i])
                if path in seen:
                    continue
                seen.add(path)
                parent = ".".join(parts[: i - 1]) if i > 1 else None
                result.append((path, parent, path in selected_set))

        return result

    # ------------------------------------------------------------------
    # System asset resolution
    # ------------------------------------------------------------------

    def _resolve_system_asset(
        self,
        db: Session,
        connection_id: UUID,
        connector: AssetConnector,
        current_user_id: str,
    ) -> Optional[UUID]:
        """Return the System asset id for a connection, creating one if needed."""
        conn_db = connections_repo.get(db, connection_id)
        if conn_db is None:
            return None

        if conn_db.system_asset_id:
            existing = asset_repo.get(db, conn_db.system_asset_id)
            if existing:
                return existing.id

        system_type_db = asset_type_repo.get_by_name(db, name="System")
        if not system_type_db:
            logger.warning("Ontos asset type 'System' not found — skipping System creation")
            return None

        # Check if a System asset already exists for this platform + connection name
        existing = asset_repo.get_by_identity(
            db,
            name=conn_db.name,
            asset_type_id=system_type_db.id,
            platform=connector.connector_type,
            location=connector.connector_type,
        )
        if existing:
            conn_db.system_asset_id = existing.id
            db.flush()
            return existing.id

        system_asset = self._assets.create_asset(
            db,
            asset_in=AssetCreate(
                name=conn_db.name,
                description=f"Auto-created system for connection '{conn_db.name}'",
                asset_type_id=system_type_db.id,
                platform=connector.connector_type,
                location=connector.connector_type,
                properties={"connector_type": connector.connector_type},
                status=AssetStatus.ACTIVE,
            ),
            current_user_id=current_user_id,
        )
        conn_db.system_asset_id = system_asset.id
        db.flush()
        logger.info(f"Created System asset '{conn_db.name}' (id={system_asset.id}) for connection {connection_id}")
        return system_asset.id

    def _build_system_preview_item(
        self,
        db: Session,
        connection_id: UUID,
        connector: AssetConnector,
    ) -> Optional[ImportPreviewItem]:
        """Build a read-only preview item for the System asset (no creation)."""
        conn_db = connections_repo.get(db, connection_id)
        if conn_db is None:
            return None

        system_type_db = asset_type_repo.get_by_name(db, name="System")
        if not system_type_db:
            return None

        # Check if already linked or exists by identity
        existing_id: Optional[UUID] = None
        if conn_db.system_asset_id:
            existing = asset_repo.get(db, conn_db.system_asset_id)
            if existing:
                existing_id = existing.id
        if not existing_id:
            existing = asset_repo.get_by_identity(
                db,
                name=conn_db.name,
                asset_type_id=system_type_db.id,
                platform=connector.connector_type,
                location=connector.connector_type,
            )
            if existing:
                existing_id = existing.id

        system_path = f"__system__{connection_id}"
        return ImportPreviewItem(
            path=system_path,
            name=conn_db.name,
            asset_type="System",
            will_create=existing_id is None,
            existing_asset_id=existing_id,
            parent_path=None,
            is_ancestor=True,
        )

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _collect_items(
        self,
        db: Session,
        connector: AssetConnector,
        path: str,
        depth: ImportDepth,
        items: List[ImportPreviewItem],
        parent_path: Optional[str],
        current_depth: int,
        _type_cache: Optional[Dict[str, Any]] = None,
        _is_ancestor: bool = False,
        walk: Optional[_SyncWalk] = None,
        listed: Optional[AssetInfo] = None,
    ) -> None:
        """Recursively collect ImportPreviewItem entries for a given path.

        With ``walk`` (sync mode), an existing asset whose listing entry shows no
        change since it was imported is not fetched again, and neither is anything
        below it: its existing descendants are only recorded as seen. Existing
        assets that did change are collected with ``needs_refresh``.
        """
        seen_paths = {i.path for i in items}

        if _type_cache is None:
            _type_cache = {}

        def _get_asset_type_db(type_name: str):
            if type_name not in _type_cache:
                _type_cache[type_name] = asset_type_repo.get_by_name(db, name=type_name)
            return _type_cache[type_name]

        if walk is not None and listed is not None and self._unchanged_subtree(
            db, connector, path, listed, walk, _get_asset_type_db,
        ):
            return

        metadata = None
        try:
            metadata = connector.get_asset_metadata(path)
        except Exception as exc:
            if walk is not None:
                walk.incomplete_reasons.append(f"{path}: metadata unavailable ({type(exc).__name__})")
        if walk is not None and metadata is not None:
            incomplete = (metadata.properties or {}).get("metadata_incomplete") or (
                (metadata.properties or {}).get("metadata_api_error")
            )
            if incomplete:
                walk.incomplete_reasons.append(f"{path}: source metadata incomplete")

        is_leaf = False

        platform = connector.connector_type

        if metadata and metadata.asset_type:
            is_leaf = metadata.asset_type.value in _LEAF_ASSET_TYPES
            mapped = _TYPE_MAP.get(metadata.asset_type.value)
            if mapped and path not in seen_paths:
                ontos_type_name = mapped[0]
                at_db = _get_asset_type_db(ontos_type_name)
                existing = None
                if at_db:
                    existing = asset_repo.get_by_identity(
                        db, name=metadata.name, asset_type_id=at_db.id,
                        platform=platform, location=path,
                    )
                if existing is None and ontos_type_name == METRIC_VIEW_ASSET_TYPE:
                    # A metric view imported as a View before the Metric View type
                    # existed is reused, and execute_import converts it. Without the
                    # seeded Metric View type it stays (or is imported as) a View.
                    view_db = _get_asset_type_db("View")
                    legacy = view_db and asset_repo.get_by_identity(
                        db, name=metadata.name, asset_type_id=view_db.id,
                        platform=platform, location=path,
                    )
                    existing = legacy or None
                    if not at_db:
                        ontos_type_name = "View"

                items.append(ImportPreviewItem(
                    path=path,
                    name=metadata.name,
                    asset_type=ontos_type_name,
                    will_create=existing is None,
                    existing_asset_id=existing.id if existing else None,
                    parent_path=parent_path,
                    is_ancestor=_is_ancestor,
                    needs_refresh=walk is not None and existing is not None
                    and self._changed_since_import(existing, metadata.updated_at),
                ))
                seen_paths.add(path)

                parent_refresh = items[-1].needs_refresh
                if metadata.schema_info and depth != ImportDepth.SELECTED_ONLY:
                    col_type_db = _get_asset_type_db("Column")
                    for col in metadata.schema_info.columns:
                        col_path = f"{path}.{col.name}"
                        if col_path in seen_paths:
                            continue
                        col_existing = None
                        if col_type_db:
                            col_existing = asset_repo.get_by_identity(
                                db, name=col.name, asset_type_id=col_type_db.id,
                                platform=platform, location=col_path,
                            )
                        items.append(ImportPreviewItem(
                            path=col_path,
                            name=col.name,
                            asset_type="Column",
                            will_create=col_existing is None,
                            existing_asset_id=col_existing.id if col_existing else None,
                            parent_path=path,
                            needs_refresh=parent_refresh and col_existing is not None,
                        ))
                        seen_paths.add(col_path)

        # Leaf assets (tables, views, routines, models) have no structural
        # children beyond columns (already extracted from schema_info above).
        # Recursing via list_assets/list_containers would re-list all siblings
        # in the parent container, causing an explosion of redundant API calls.
        if is_leaf:
            return

        should_recurse = (
            (depth == ImportDepth.ONE_LEVEL and current_depth == 0)
            or depth == ImportDepth.FULL_RECURSIVE
        )

        if should_recurse:
            try:
                limit = self._child_limit(db)
                options = ListAssetsOptions(path=path, limit=limit)
                children = connector.list_assets(options=options)
                if walk is not None and len(children) >= limit:
                    walk.incomplete_reasons.append(f"{path}: more than {limit} children, the rest were not listed")
                for child in children:
                    if child.identifier in seen_paths or child.identifier == path:
                        continue
                    child_mapped = _TYPE_MAP.get(child.asset_type.value) if child.asset_type else None
                    if child_mapped:
                        self._collect_items(
                            db=db,
                            connector=connector,
                            path=child.identifier,
                            depth=depth,
                            items=items,
                            parent_path=path,
                            current_depth=current_depth + 1,
                            _type_cache=_type_cache,
                            walk=walk,
                            listed=child,
                        )
            except Exception as exc:
                logger.debug(f"Cannot list children at '{path}': {exc}")
                if walk is not None:
                    walk.incomplete_reasons.append(f"{path}: children could not be listed ({type(exc).__name__})")

            try:
                containers = connector.list_containers(parent_path=path)
                for c in containers:
                    c_path = c.get("path", "")
                    if c_path in seen_paths or c_path == path:
                        continue
                    c_type = c.get("type", "").lower()
                    if c_type in _CONTAINER_TYPES:
                        self._collect_items(
                            db=db,
                            connector=connector,
                            path=c_path,
                            depth=depth,
                            items=items,
                            parent_path=path,
                            current_depth=current_depth + 1,
                            _type_cache=_type_cache,
                            walk=walk,
                        )
            except Exception as exc:
                logger.debug(f"Cannot list containers at '{path}': {exc}")
                if walk is not None:
                    walk.incomplete_reasons.append(f"{path}: containers could not be listed ({type(exc).__name__})")

    @staticmethod
    def _changed_since_import(existing: AssetDb, source_updated_at: Any) -> bool:
        """Whether the source changed an existing asset after it was imported (unknown: changed)."""
        current = _as_utc(source_updated_at)
        stored = _as_utc((existing.properties or {}).get("source_updated_at"))
        return current is None or stored is None or current > stored

    def _unchanged_subtree(
        self,
        db: Session,
        connector: AssetConnector,
        path: str,
        listed: AssetInfo,
        walk: _SyncWalk,
        get_asset_type_db: Callable[[str], Any],
    ) -> bool:
        """Record an unchanged existing asset and its descendants as seen (sync mode).

        Unchanged means the listing reports a change time no later than the one
        stored at the last import. A connector that sets ``AssetInfo.updated_at``
        promises the time changes whenever anything below the asset does (Tableau
        bumps it when a workbook or data source is published again).
        """
        listed_at = _as_utc(listed.updated_at)
        mapped = _TYPE_MAP.get(listed.asset_type.value) if listed.asset_type else None
        if listed_at is None or not mapped:
            return False
        type_db = get_asset_type_db(mapped[0])
        existing = type_db and asset_repo.get_by_identity(
            db, name=listed.name, asset_type_id=type_db.id, platform=connector.connector_type, location=path,
        )
        if not existing:
            return False
        stored_at = _as_utc((existing.properties or {}).get("source_updated_at"))
        if stored_at is None or listed_at > stored_at:
            return False
        walk.seen_ids.add(existing.id)
        descendants = db.query(AssetDb.id).filter(
            AssetDb.platform == connector.connector_type,
            AssetDb.location.startswith(f"{path}.", autoescape=True),
        )
        walk.seen_ids.update(row.id for row in descendants)
        return True

    def _create_asset_from_item(
        self,
        db: Session,
        connector: AssetConnector,
        item: ImportPreviewItem,
        current_user_id: str,
        _type_cache: Optional[Dict[str, Any]] = None,
        _metadata_cache: Optional[Dict[str, Any]] = None,
        connection_id: Optional[UUID] = None,
    ):
        """Create a single Ontos asset from a preview item."""
        if _type_cache is not None and item.asset_type in _type_cache:
            asset_type_db = _type_cache[item.asset_type]
        else:
            asset_type_db = asset_type_repo.get_by_name(db, name=item.asset_type)
            if _type_cache is not None:
                _type_cache[item.asset_type] = asset_type_db
        if not asset_type_db:
            raise ValueError(f"Ontos asset type '{item.asset_type}' not found in database")

        description, properties = self._source_properties(
            connector, item, _metadata_cache, connection_id=connection_id,
        )
        if properties:
            properties[IMPORTED_KEYS_PROPERTY] = sorted(properties)

        asset_in = AssetCreate(
            name=item.name,
            description=description,
            asset_type_id=asset_type_db.id,
            platform=connector.connector_type,
            location=item.path,
            properties=properties or None,
            status=AssetStatus.ACTIVE,
        )

        return self._assets.create_asset(db, asset_in=asset_in, current_user_id=current_user_id)

    def _source_properties(
        self,
        connector: AssetConnector,
        item: ImportPreviewItem,
        _metadata_cache: Optional[Dict[str, Any]],
        connection_id: Optional[UUID] = None,
    ) -> tuple:
        """(description, properties) of an item, as read from the source now."""
        properties: Dict[str, Any] = {}
        description = None

        if item.asset_type == "Column":
            parent_path = item.parent_path or ".".join(item.path.split(".")[:-1])
            col_info = self._find_column_in_cache(
                _metadata_cache, parent_path, item.name, connector,
            )
            if col_info:
                description = col_info.description
                properties = {
                    **_connector_hook(connector, "import_column_properties", col_info, default={}),
                    "data_type": col_info.data_type,
                    "logical_type": col_info.logical_type,
                    "nullable": col_info.nullable,
                    "is_primary_key": col_info.is_primary_key,
                    "is_partition_key": col_info.is_partition_key,
                    "source_path": item.path,
                }
                if col_info.tags:
                    properties["source_tags"] = col_info.tags
            else:
                properties = {"source_path": item.path}
            if connection_id:
                # A connector sync retires columns its connection no longer has
                properties["connection_id"] = str(connection_id)
        else:
            try:
                meta = connector.get_asset_metadata(item.path)
                if meta:
                    if _metadata_cache is not None:
                        _metadata_cache[item.path] = meta
                    description = meta.description
                    properties.update(_connector_hook(connector, "import_properties", meta, default={}))
                    if meta.schema_info:
                        properties["schema"] = {
                            "column_count": meta.schema_info.column_count,
                            "columns": [
                                {
                                    "name": c.name,
                                    "data_type": c.data_type,
                                    "logical_type": c.logical_type,
                                    "nullable": c.nullable,
                                    "description": c.description,
                                    "is_partition_key": c.is_partition_key,
                                }
                                for c in (meta.schema_info.columns or [])
                            ],
                        }
                    if meta.statistics:
                        properties["statistics"] = meta.statistics.model_dump(exclude_none=True)
                    if meta.ownership:
                        properties["ownership"] = meta.ownership.model_dump(exclude_none=True)
                    if meta.tags:
                        properties["source_tags"] = meta.tags
                    properties["source_path"] = item.path
                    properties["connector_type"] = connector.connector_type
                    if connection_id:
                        # Lets later actions (e.g. snapshot refresh) reach the source again
                        properties["connection_id"] = str(connection_id)
                    if item.asset_type == METRIC_VIEW_ASSET_TYPE:
                        # The parsed spec and its measure fingerprints (#1263)
                        stored = build_stored_metric_view(
                            (meta.properties or {}).get(METRIC_VIEW_PROPERTY))
                        if stored:
                            properties[METRIC_VIEW_PROPERTY] = stored
            except Exception as exc:
                logger.debug(f"Could not fetch metadata for '{item.path}': {exc}")

        return description, properties

    def _refresh_existing(
        self,
        db: Session,
        connector: AssetConnector,
        item: ImportPreviewItem,
        metadata_cache: Dict[str, Any],
        connection_id: Optional[UUID],
    ) -> None:
        """Update an existing asset from the source (sync mode).

        Properties the previous import wrote are replaced by the current ones;
        everything else (snapshot state, sync counters, properties users added)
        is kept.
        """
        asset = asset_repo.get(db, id=item.existing_asset_id)
        if asset is None:
            raise ValueError(f"Asset {item.existing_asset_id} no longer exists")
        description, fresh = self._source_properties(connector, item, metadata_cache, connection_id=connection_id)
        current = dict(asset.properties or {})
        kept = {k: v for k, v in current.items() if k not in set(current.get(IMPORTED_KEYS_PROPERTY) or [])}
        kept.pop(IMPORTED_KEYS_PROPERTY, None)
        asset.properties = {**kept, **fresh, IMPORTED_KEYS_PROPERTY: sorted(fresh)}
        flag_modified(asset, "properties")
        if description is not None:
            asset.description = description
        db.flush()

    @staticmethod
    def _find_column_in_cache(
        metadata_cache: Optional[Dict[str, Any]],
        parent_path: str,
        column_name: str,
        connector: AssetConnector,
    ):
        """Look up a ColumnInfo from the cached parent metadata, fetching if needed."""
        if metadata_cache is None:
            metadata_cache = {}
        meta = metadata_cache.get(parent_path)
        if meta is None:
            try:
                meta = connector.get_asset_metadata(parent_path)
                metadata_cache[parent_path] = meta
            except Exception:
                return None
        if meta and meta.schema_info and meta.schema_info.columns:
            for col in meta.schema_info.columns:
                if col.name == column_name:
                    return col
        return None

    @staticmethod
    def _relationship_type_for(asset_type_name: str) -> str:
        """Return the ontology relationship type for a given Ontos asset type."""
        mapping = {
            "Catalog": "hasCatalog",
            "Schema": "hasSchema",
            "Table": "hasTable",
            "View": "hasView",
            METRIC_VIEW_ASSET_TYPE: "hasView",
            "Column": "hasColumn",
            "Dataset": "hasDataset",
            "ML Model": "hasPart",
            "Dashboard": "hasPart",
            "System": "hasPart",
        }
        return mapping.get(asset_type_name, "hasPart")


# ---------------------------------------------------------------------------
# Module-level helpers
# ---------------------------------------------------------------------------

# Per-asset-type display labels for the browse tree (drives the
# `node_type` field on BrowseNode and the icon picked by the frontend).
#
# Distinct from `_TYPE_MAP` on purpose: `_TYPE_MAP` collapses source-system
# concepts to a smaller Ontos asset-type vocabulary used at *import* time
# (e.g. UC_FUNCTION/UC_VOLUME -> "System"), but at *browse* time we want
# to preserve the source label so users can tell a function from a volume.
_DISPLAY_TYPE_MAP: Dict[str, str] = {
    # Databricks / Unity Catalog
    UnifiedAssetType.UC_CATALOG.value: "catalog",
    UnifiedAssetType.UC_SCHEMA.value: "schema",
    UnifiedAssetType.UC_TABLE.value: "table",
    UnifiedAssetType.UC_VIEW.value: "view",
    UnifiedAssetType.UC_MATERIALIZED_VIEW.value: "view",
    UnifiedAssetType.UC_METRIC.value: "metric",
    UnifiedAssetType.UC_STREAMING_TABLE.value: "table",
    UnifiedAssetType.UC_FUNCTION.value: "function",
    UnifiedAssetType.UC_MODEL.value: "model",
    UnifiedAssetType.UC_VOLUME.value: "volume",
    # BigQuery
    UnifiedAssetType.BQ_PROJECT.value: "project",
    UnifiedAssetType.BQ_DATASET.value: "dataset",
    UnifiedAssetType.BQ_TABLE.value: "table",
    UnifiedAssetType.BQ_VIEW.value: "view",
    UnifiedAssetType.BQ_MATERIALIZED_VIEW.value: "view",
    UnifiedAssetType.BQ_EXTERNAL_TABLE.value: "table",
    UnifiedAssetType.BQ_ROUTINE.value: "routine",
    UnifiedAssetType.BQ_MODEL.value: "model",
    # Snowflake
    UnifiedAssetType.SNOWFLAKE_DATABASE.value: "database",
    UnifiedAssetType.SNOWFLAKE_SCHEMA.value: "schema",
    UnifiedAssetType.SNOWFLAKE_TABLE.value: "table",
    UnifiedAssetType.SNOWFLAKE_VIEW.value: "view",
    UnifiedAssetType.SNOWFLAKE_MATERIALIZED_VIEW.value: "view",
    UnifiedAssetType.SNOWFLAKE_FUNCTION.value: "function",
    UnifiedAssetType.SNOWFLAKE_PROCEDURE.value: "procedure",
    # Tableau
    UnifiedAssetType.TABLEAU_PROJECT.value: "project",
    UnifiedAssetType.TABLEAU_WORKBOOK.value: "workbook",
    UnifiedAssetType.TABLEAU_DASHBOARD.value: "dashboard",
    UnifiedAssetType.TABLEAU_SHEET.value: "sheet",
    UnifiedAssetType.TABLEAU_DATASOURCE.value: "datasource",
}


def _connector_hook(connector: Any, name: str, *args: Any, default: Any) -> Any:
    """Call an optional AssetConnector import hook; connectors without it get ``default``."""
    hook = getattr(connector, name, None)
    return hook(*args) if callable(hook) else default


def _display_type(asset_type: Optional[UnifiedAssetType]) -> str:
    """Human-friendly type label for browse nodes.

    Drives the `node_type` field returned to the UI, which selects the
    Lucide icon and the small label printed next to each node name.
    """
    if asset_type is None:
        return "unknown"
    label = _DISPLAY_TYPE_MAP.get(asset_type.value)
    if label:
        return label
    # Last-resort fallback for newly-added asset types: take the trailing
    # segment of the enum value (e.g. "powerbi_dashboard" -> "dashboard").
    return asset_type.value.split("_")[-1].lower()


def _has_children(asset_type: Optional[UnifiedAssetType]) -> bool:
    """Whether an asset type may have child nodes (e.g., columns).

    Used to set ``BrowseNode.has_children`` so the UI renders an expand
    chevron. The set must include every leaf type whose
    ``get_asset_metadata().schema_info`` is populated by the connector,
    otherwise the user has no way to drill into its columns/parameters.

    Excluded by design: models, volumes, datasets — they have no
    column-level schema, so an expand chevron would yield an empty list.
    """
    if asset_type is None:
        return False
    return asset_type.value in {
        # Containers
        UnifiedAssetType.UC_CATALOG.value,
        UnifiedAssetType.UC_SCHEMA.value,
        UnifiedAssetType.BQ_PROJECT.value,
        UnifiedAssetType.BQ_DATASET.value,
        UnifiedAssetType.SNOWFLAKE_DATABASE.value,
        UnifiedAssetType.SNOWFLAKE_SCHEMA.value,
        # UC leaves with column-bearing metadata
        UnifiedAssetType.UC_TABLE.value,
        UnifiedAssetType.UC_VIEW.value,
        UnifiedAssetType.UC_MATERIALIZED_VIEW.value,
        UnifiedAssetType.UC_METRIC.value,
        UnifiedAssetType.UC_STREAMING_TABLE.value,
        UnifiedAssetType.UC_FUNCTION.value,
        # BigQuery leaves with column-bearing metadata
        UnifiedAssetType.BQ_TABLE.value,
        UnifiedAssetType.BQ_VIEW.value,
        UnifiedAssetType.BQ_MATERIALIZED_VIEW.value,
        UnifiedAssetType.BQ_EXTERNAL_TABLE.value,
        UnifiedAssetType.BQ_ROUTINE.value,
        # Snowflake leaves with column-bearing metadata
        UnifiedAssetType.SNOWFLAKE_TABLE.value,
        UnifiedAssetType.SNOWFLAKE_VIEW.value,
        UnifiedAssetType.SNOWFLAKE_MATERIALIZED_VIEW.value,
        UnifiedAssetType.SNOWFLAKE_FUNCTION.value,
        UnifiedAssetType.SNOWFLAKE_PROCEDURE.value,
        # Tableau: workbooks hold views, published data sources hold fields
        UnifiedAssetType.TABLEAU_WORKBOOK.value,
        UnifiedAssetType.TABLEAU_DATASOURCE.value,
    }
