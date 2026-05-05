"""
Schema Import Manager

Bridges external connectors with persisted Ontos assets.  Provides browse,
preview, and import operations.
"""

from typing import Any, Dict, List, Optional
from uuid import UUID

from sqlalchemy.orm import Session

from src.common.logging import get_logger
from src.connectors.base import AssetConnector, ListAssetsOptions
from src.controller.connections_manager import ConnectionsManager
from src.controller.assets_manager import AssetsManager
from src.db_models.assets import AssetDb
from src.db_models.connections import ConnectionDb
from src.models.assets import (
    AssetCreate,
    AssetRelationshipCreate,
    AssetStatus,
    UnifiedAssetType,
)
from src.models.schema_import import (
    BrowseNode,
    BrowseResponse,
    ImportDepth,
    ImportPreviewItem,
    ImportRequest,
    ImportResult,
    ImportResultItem,
)
from src.db_models.entity_relationships import EntityRelationshipDb
from src.repositories.assets_repository import asset_repo, asset_type_repo
from src.repositories.connections_repository import connections_repo

logger = get_logger(__name__)


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
}


class SchemaImportManager:
    """Manages browsing remote systems and importing their structure as Ontos assets."""

    def __init__(
        self,
        connections_manager: ConnectionsManager,
        assets_manager: AssetsManager,
    ):
        self._connections = connections_manager
        self._assets = assets_manager

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
        try:
            options = ListAssetsOptions(path=path or "", limit=500)
            assets = connector.list_assets(options=options)
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
    ) -> ImportResult:
        """Import selected resources (and nested children) as Ontos assets."""
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
            )

        result = ImportResult()
        result.system_asset_id = system_asset_id

        # path -> created asset UUID (used for relationship wiring)
        created_assets: Dict[str, UUID] = {}
        type_cache: Dict[str, Any] = {}
        metadata_cache: Dict[str, Any] = {}

        # 2. Create assets (parents before children — items are in BFS order)
        for item in preview_items:
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
                result.skipped += 1
                result.items.append(ImportResultItem(
                    path=item.path,
                    name=item.name,
                    asset_type=item.asset_type,
                    action="skipped",
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

        # 3. Wire relationships (both asset_relationships and entity_relationships)
        # Build a lookup from path -> (asset_type_name, asset_id) for entity relationships
        path_to_type: Dict[str, str] = {}
        for item in preview_items:
            if item.path in created_assets:
                path_to_type[item.path] = item.asset_type

        for item in preview_items:
            if item.parent_path and item.parent_path in created_assets and item.path in created_assets:
                rel_type = self._relationship_type_for(item.asset_type)
                source_id = created_assets[item.parent_path]
                target_id = created_assets[item.path]
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
                    logger.debug(f"Relationship {item.parent_path} -> {item.path}: {exc}")

                # Also write to entity_relationships so the detail page shows them
                source_type = path_to_type.get(item.parent_path, "Asset")
                target_type = path_to_type.get(item.path, "Asset")
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
                    logger.debug(f"Entity relationship {item.parent_path} -> {item.path}: {exc}")

        # 4. Wire System -> top-level Catalog/Schema assets
        if system_asset_id:
            for item in preview_items:
                if item.parent_path is None and item.path in created_assets:
                    rel_type = self._relationship_type_for(item.asset_type)
                    target_id = created_assets[item.path]
                    try:
                        self._assets.add_relationship(
                            db,
                            rel_in=AssetRelationshipCreate(
                                source_asset_id=system_asset_id,
                                target_asset_id=target_id,
                                relationship_type=rel_type,
                            ),
                            current_user_id=current_user_id,
                        )
                    except Exception as exc:
                        logger.debug(f"System -> {item.path} relationship: {exc}")

                    try:
                        existing = db.query(EntityRelationshipDb).filter(
                            EntityRelationshipDb.source_type == "System",
                            EntityRelationshipDb.source_id == str(system_asset_id),
                            EntityRelationshipDb.target_type == item.asset_type,
                            EntityRelationshipDb.target_id == str(target_id),
                            EntityRelationshipDb.relationship_type == rel_type,
                        ).first()
                        if not existing:
                            db.add(EntityRelationshipDb(
                                source_type="System",
                                source_id=str(system_asset_id),
                                target_type=item.asset_type,
                                target_id=str(target_id),
                                relationship_type=rel_type,
                                created_by=current_user_id,
                            ))
                            db.flush()
                    except Exception as exc:
                        logger.debug(f"Entity relationship System -> {item.path}: {exc}")

        return result

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
    ) -> None:
        """Recursively collect ImportPreviewItem entries for a given path."""
        seen_paths = {i.path for i in items}

        if _type_cache is None:
            _type_cache = {}

        def _get_asset_type_db(type_name: str):
            if type_name not in _type_cache:
                _type_cache[type_name] = asset_type_repo.get_by_name(db, name=type_name)
            return _type_cache[type_name]

        metadata = None
        try:
            metadata = connector.get_asset_metadata(path)
        except Exception:
            pass

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

                items.append(ImportPreviewItem(
                    path=path,
                    name=metadata.name,
                    asset_type=ontos_type_name,
                    will_create=existing is None,
                    existing_asset_id=existing.id if existing else None,
                    parent_path=parent_path,
                    is_ancestor=_is_ancestor,
                ))
                seen_paths.add(path)

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
                options = ListAssetsOptions(path=path, limit=500)
                children = connector.list_assets(options=options)
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
                        )
            except Exception as exc:
                logger.debug(f"Cannot list children at '{path}': {exc}")

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
                        )
            except Exception as exc:
                logger.debug(f"Cannot list containers at '{path}': {exc}")

    def _create_asset_from_item(
        self,
        db: Session,
        connector: AssetConnector,
        item: ImportPreviewItem,
        current_user_id: str,
        _type_cache: Optional[Dict[str, Any]] = None,
        _metadata_cache: Optional[Dict[str, Any]] = None,
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
        else:
            try:
                meta = connector.get_asset_metadata(item.path)
                if meta:
                    if _metadata_cache is not None:
                        _metadata_cache[item.path] = meta
                    description = meta.description
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
            except Exception as exc:
                logger.debug(f"Could not fetch metadata for '{item.path}': {exc}")

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

def _display_type(asset_type: Optional[UnifiedAssetType]) -> str:
    """Human-friendly type label for browse nodes."""
    if asset_type is None:
        return "unknown"
    mapping = _TYPE_MAP.get(asset_type.value)
    if mapping:
        return mapping[0].lower()
    return asset_type.value.split("_")[-1].lower()


def _has_children(asset_type: Optional[UnifiedAssetType]) -> bool:
    """Whether an asset type may have child nodes (e.g., columns)."""
    if asset_type is None:
        return False
    return asset_type.value in {
        UnifiedAssetType.UC_CATALOG.value,
        UnifiedAssetType.UC_SCHEMA.value,
        UnifiedAssetType.UC_TABLE.value,
        UnifiedAssetType.UC_VIEW.value,
        UnifiedAssetType.BQ_PROJECT.value,
        UnifiedAssetType.BQ_DATASET.value,
        UnifiedAssetType.BQ_TABLE.value,
        UnifiedAssetType.BQ_VIEW.value,
        UnifiedAssetType.SNOWFLAKE_DATABASE.value,
        UnifiedAssetType.SNOWFLAKE_SCHEMA.value,
        UnifiedAssetType.SNOWFLAKE_TABLE.value,
        UnifiedAssetType.SNOWFLAKE_VIEW.value,
    }
