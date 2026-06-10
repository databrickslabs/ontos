"""
Data Catalog Manager

Provides functionality for the Data Dictionary feature:
- Browse columns from Data Contracts AND imported Assets (Table/View/Dataset)
- Server-side pagination with offset/limit
- Faceted filtering by asset type, system, catalog, schema
- Full-field search across column name, description, business terms, parents
- Table details and lineage

Data sources are merged and deduplicated: Asset (physical) metadata is the base,
Contract metadata enriches with business context.
"""

from typing import List, Optional, Dict, Any, Tuple
from sqlalchemy.orm import Session, selectinload

from databricks.sdk import WorkspaceClient

from src.common.logging import get_logger
from src.common.config import Settings
from src.db_models.assets import AssetDb, AssetTypeDb, AssetRelationshipDb
from src.db_models.data_contracts import DataContractDb, SchemaObjectDb, SchemaPropertyDb
from src.models.data_catalog import (
    ColumnDictionaryEntry,
    ColumnInfo,
    TableInfo,
    TableListItem,
    ColumnSearchResponse,
    DataDictionaryResponse,
    TableListResponse,
    HierarchyFilters,
    LineageGraph,
    LineageDirection,
    ImpactAnalysis,
)
from src.controller.lineage_service import LineageService
from src.controller.data_contracts_manager import DataContractsManager

logger = get_logger(__name__)

# Asset types that represent table-like containers with columns
_TABLE_LIKE_TYPES = {"Table", "View", "Dataset"}
_HIERARCHICAL_RELS = {"hasColumn", "hasTable", "hasView", "hasDataset", "hasPart",
                      "contains", "hasCatalog", "hasSchema"}


class DataCatalogManager:
    """
    Manager for Data Dictionary / Data Catalog operations.

    Merges columns from two sources:
    1. Data Contracts (schema objects with properties)
    2. Asset DB (Table/View/Dataset assets with Column children)

    Supports server-side pagination, faceted filtering, and full-field search.
    """

    def __init__(
        self,
        obo_client: WorkspaceClient,
        db_session: Session,
        contracts_manager: Optional[DataContractsManager] = None,
        settings: Optional[Settings] = None
    ):
        self.client = obo_client
        self.db = db_session
        self.contracts_manager = contracts_manager
        self.settings = settings
        self.lineage_service = LineageService(obo_client)

        logger.debug("DataCatalogManager initialized")

    # =========================================================================
    # Column Extraction: Contracts
    # =========================================================================

    def _get_columns_from_contracts(self) -> List[ColumnDictionaryEntry]:
        """
        Extract columns from Data Contract schema definitions.
        Deduplicated by (table_full_name, column_name).
        """
        columns_map: Dict[Tuple[str, str], ColumnDictionaryEntry] = {}

        if not self.db:
            logger.warning("Database session not available")
            return []

        try:
            db_contracts = (
                self.db.query(DataContractDb)
                .options(
                    selectinload(DataContractDb.schema_objects)
                    .selectinload(SchemaObjectDb.properties)
                    .selectinload(SchemaPropertyDb.authoritative_definitions)
                )
                .all()
            )
            logger.info(f"Processing {len(db_contracts)} contracts for column extraction")

            for db_contract in db_contracts:
                contract_id = str(db_contract.id)
                contract_name = db_contract.name
                contract_version = db_contract.version or "1.0"
                contract_status = db_contract.status

                schema_objects = getattr(db_contract, 'schema_objects', []) or []

                for schema_obj in schema_objects:
                    schema_name = getattr(schema_obj, 'name', 'unknown')

                    properties = getattr(schema_obj, 'properties', []) or []

                    for idx, prop in enumerate(properties):
                        col_name = getattr(prop, 'name', 'unknown')
                        logical_type = getattr(prop, 'logical_type', 'unknown')
                        physical_type = getattr(prop, 'physical_type', None)
                        description = getattr(prop, 'transform_description', None) or getattr(prop, 'description', None)
                        required = getattr(prop, 'required', False)
                        pk_position = getattr(prop, 'primary_key_position', -1)
                        is_pk = pk_position is not None and pk_position >= 0
                        classification = getattr(prop, 'classification', None)
                        business_name = getattr(prop, 'business_name', None)

                        business_terms: List[Dict[str, str]] = []
                        auth_defs = getattr(prop, 'authoritative_definitions', []) or []
                        for auth_def in auth_defs:
                            url = getattr(auth_def, 'url', None)
                            def_type = getattr(auth_def, 'type', None)
                            if url:
                                label = url.split('#')[-1].split('/')[-1] if url else None
                                business_terms.append({
                                    "iri": url,
                                    "label": label or url,
                                    "type": def_type or "businessTerm"
                                })

                        table_full_name = f"{contract_name}.{schema_name}"
                        dedup_key = (table_full_name, col_name)

                        if dedup_key in columns_map:
                            existing = columns_map[dedup_key]
                            existing_iris = {t.get("iri") for t in existing.business_terms}
                            for term in business_terms:
                                if term.get("iri") not in existing_iris:
                                    existing.business_terms.append(term)
                        else:
                            columns_map[dedup_key] = ColumnDictionaryEntry(
                                column_name=col_name,
                                column_label=business_name,
                                column_type=physical_type or logical_type,
                                description=description,
                                nullable=not required,
                                position=idx,
                                table_name=schema_name,
                                table_full_name=table_full_name,
                                schema_name=contract_name,
                                catalog_name=contract_version,
                                table_type="CONTRACT",
                                source="contract",
                                is_primary_key=is_pk,
                                classification=classification,
                                contract_id=contract_id,
                                contract_name=contract_name,
                                contract_version=contract_version,
                                contract_status=contract_status,
                                business_terms=business_terms,
                            )

            columns = list(columns_map.values())
            logger.info(f"Extracted {len(columns)} unique columns from {len(db_contracts)} contracts")

        except Exception as e:
            logger.error(f"Error extracting columns from contracts: {e}", exc_info=True)
            return []

        return columns

    # =========================================================================
    # Column Extraction: Assets
    # =========================================================================

    def _get_columns_from_assets(self) -> List[ColumnDictionaryEntry]:
        """
        Extract columns from Asset DB (Table/View/Dataset assets with Column children).

        Walks the asset hierarchy to resolve parent System/Catalog/Schema names.
        """
        columns: List[ColumnDictionaryEntry] = []

        if not self.db:
            logger.warning("Database session not available")
            return []

        try:
            # Get all table-like assets with their relationships eager-loaded
            table_like_assets = (
                self.db.query(AssetDb)
                .join(AssetTypeDb, AssetDb.asset_type_id == AssetTypeDb.id)
                .filter(AssetTypeDb.name.in_(_TABLE_LIKE_TYPES))
                .options(
                    selectinload(AssetDb.asset_type),
                    # Eager-load child column assets (avoids N+1 in _get_asset_child_columns)
                    selectinload(AssetDb.source_relationships)
                    .selectinload(AssetRelationshipDb.target_asset),
                    selectinload(AssetDb.target_relationships)
                    .selectinload(AssetRelationshipDb.source_asset)
                    .selectinload(AssetDb.asset_type),
                )
                .all()
            )
            logger.info(f"Processing {len(table_like_assets)} table-like assets for column extraction")

            for asset in table_like_assets:
                asset_type_name = asset.asset_type.name if asset.asset_type else "Table"

                # Resolve hierarchy: walk target_relationships to find parent Schema/Catalog/System
                parent_info = self._resolve_asset_parents(asset)
                system_name = parent_info.get("system")
                catalog_name = parent_info.get("catalog", "")
                schema_name = parent_info.get("schema", "")

                # Build the FQN
                if asset.location:
                    table_full_name = asset.location
                else:
                    parts = [p for p in [catalog_name, schema_name, asset.name] if p]
                    table_full_name = ".".join(parts) if parts else asset.name

                table_name = asset.name

                # Get columns from hasColumn children
                child_columns = self._get_asset_child_columns(asset)

                # Fallback: check properties.schema.columns
                if not child_columns and asset.properties and "schema" in asset.properties:
                    stored = asset.properties["schema"]
                    if isinstance(stored, dict) and "columns" in stored:
                        for idx, c in enumerate(stored["columns"]):
                            child_columns.append({
                                "name": c.get("name", ""),
                                "data_type": c.get("data_type", ""),
                                "logical_type": c.get("logical_type", "string"),
                                "nullable": c.get("nullable", True),
                                "description": c.get("description", ""),
                                "is_partition_key": c.get("is_partition_key", False),
                                "position": idx,
                            })

                for idx, col_data in enumerate(child_columns):
                    columns.append(ColumnDictionaryEntry(
                        column_name=col_data.get("name", "unknown"),
                        column_label=None,
                        column_type=col_data.get("data_type", "") or col_data.get("logical_type", "unknown"),
                        description=col_data.get("description"),
                        nullable=col_data.get("nullable", True),
                        position=col_data.get("position", idx),
                        table_name=table_name,
                        table_full_name=table_full_name,
                        schema_name=schema_name,
                        catalog_name=catalog_name,
                        table_type=asset_type_name.upper(),
                        source="asset",
                        asset_id=str(asset.id),
                        system_name=system_name,
                        is_primary_key=col_data.get("is_partition_key", False),
                    ))

            logger.info(f"Extracted {len(columns)} columns from {len(table_like_assets)} assets")

        except Exception as e:
            logger.error(f"Error extracting columns from assets: {e}", exc_info=True)
            return []

        return columns

    def _get_asset_child_columns(self, asset: AssetDb) -> List[Dict[str, Any]]:
        """Get Column children of a table-like asset via hasColumn relationships.

        Relies on `source_relationships.target_asset` being eager-loaded by the
        caller (see `_get_columns_from_assets`) — accessing `rel.target_asset`
        here would otherwise trigger an N+1 lazy-load per child column.
        """
        columns: List[Dict[str, Any]] = []
        if not asset.source_relationships:
            return columns

        for rel in asset.source_relationships:
            if rel.relationship_type != "hasColumn":
                continue
            child = rel.target_asset
            if not child:
                continue
            props = child.properties or {}
            columns.append({
                "name": child.name,
                "data_type": props.get("data_type", ""),
                "logical_type": props.get("logical_type", "string"),
                "nullable": props.get("nullable", True),
                "description": child.description or "",
                "is_partition_key": props.get("is_partition_key", False),
                "position": props.get("position", 0),
            })
        return columns

    def _resolve_asset_parents(
        self,
        asset: AssetDb,
        _visited: Optional[set] = None,
    ) -> Dict[str, Optional[str]]:
        """Walk up the hierarchy to find parent System/Catalog/Schema names.

        Guards against cyclic asset graphs via a visited-set keyed on asset id.
        """
        result: Dict[str, Optional[str]] = {"system": None, "catalog": None, "schema": None}

        if not asset.target_relationships:
            return result

        if _visited is None:
            _visited = set()
        if asset.id in _visited:
            return result
        _visited.add(asset.id)

        # target_relationships: this asset is the target (child); source is the parent
        for rel in asset.target_relationships:
            if rel.relationship_type not in _HIERARCHICAL_RELS:
                continue
            parent = rel.source_asset
            if not parent or not parent.asset_type:
                continue
            parent_type = parent.asset_type.name
            if parent_type == "System":
                result["system"] = parent.name
            elif parent_type == "Catalog":
                result["catalog"] = parent.name
                # Also try to get system from catalog's parent
                catalog_parents = self._resolve_asset_parents(parent, _visited)
                if catalog_parents.get("system"):
                    result["system"] = catalog_parents["system"]
            elif parent_type == "Schema":
                result["schema"] = parent.name
                # Walk up from schema
                schema_parents = self._resolve_asset_parents(parent, _visited)
                if schema_parents.get("catalog"):
                    result["catalog"] = schema_parents["catalog"]
                if schema_parents.get("system"):
                    result["system"] = schema_parents["system"]

        return result

    # =========================================================================
    # Merge and Deduplication
    # =========================================================================

    def _merge_columns(
        self,
        contract_columns: List[ColumnDictionaryEntry],
        asset_columns: List[ColumnDictionaryEntry],
    ) -> List[ColumnDictionaryEntry]:
        """
        Merge columns from contracts and assets.

        Asset metadata is the base (physical truth); Contract enriches with
        business context. Deduplicate by (table_full_name, column_name).
        """
        # Index asset columns by dedup key
        merged: Dict[Tuple[str, str], ColumnDictionaryEntry] = {}

        for col in asset_columns:
            key = (col.table_full_name.lower(), col.column_name.lower())
            merged[key] = col

        for col in contract_columns:
            key = (col.table_full_name.lower(), col.column_name.lower())
            if key in merged:
                # Enrich existing asset entry with contract context
                existing = merged[key]
                existing.source = "both"
                existing.contract_id = col.contract_id
                existing.contract_name = col.contract_name
                existing.contract_version = col.contract_version
                existing.contract_status = col.contract_status
                if col.column_label:
                    existing.column_label = col.column_label
                if col.description and not existing.description:
                    existing.description = col.description
                if col.classification:
                    existing.classification = col.classification
                # Merge business terms
                existing_iris = {t.get("iri") for t in existing.business_terms}
                for term in col.business_terms:
                    if term.get("iri") not in existing_iris:
                        existing.business_terms.append(term)
            else:
                merged[key] = col

        return list(merged.values())

    # =========================================================================
    # Column Dictionary: Paginated + Filtered
    # =========================================================================

    def get_all_columns(
        self,
        catalog_filter: Optional[str] = None,
        schema_filter: Optional[str] = None,
        table_filter: Optional[str] = None,
        asset_type_filter: Optional[str] = None,
        system_filter: Optional[str] = None,
        offset: int = 0,
        limit: int = 50,
    ) -> DataDictionaryResponse:
        """
        Get paginated columns from both Data Contracts and Assets.

        Args:
            catalog_filter: Filter to specific catalog
            schema_filter: Filter to specific schema
            table_filter: Filter to specific table (FQN or name)
            asset_type_filter: Filter to specific asset type (Table, View, Dataset, CONTRACT)
            system_filter: Filter to columns under a specific System
            offset: Pagination offset
            limit: Page size
        """
        logger.info(
            f"Fetching columns (catalog={catalog_filter}, schema={schema_filter}, "
            f"table={table_filter}, asset_type={asset_type_filter}, system={system_filter}, "
            f"offset={offset}, limit={limit})"
        )

        try:
            contract_columns = self._get_columns_from_contracts()
            asset_columns = self._get_columns_from_assets()

            all_columns = self._merge_columns(contract_columns, asset_columns)

            # Apply filters
            filtered = self._apply_filters(
                all_columns,
                catalog_filter=catalog_filter,
                schema_filter=schema_filter,
                table_filter=table_filter,
                asset_type_filter=asset_type_filter,
                system_filter=system_filter,
            )

            unique_tables = set(col.table_full_name for col in filtered)
            total_count = len(filtered)
            has_more = (offset + limit) < total_count
            page = filtered[offset:offset + limit]

            return DataDictionaryResponse(
                table_count=len(unique_tables),
                column_count=total_count,
                columns=page,
                offset=offset,
                limit=limit,
                has_more=has_more,
                table_filter=table_filter,
            )

        except Exception as e:
            logger.error(f"Error fetching columns: {e}", exc_info=True)
            return DataDictionaryResponse(
                table_count=0,
                column_count=0,
                columns=[],
                offset=offset,
                limit=limit,
                has_more=False,
                table_filter=table_filter,
            )

    def _apply_filters(
        self,
        columns: List[ColumnDictionaryEntry],
        catalog_filter: Optional[str] = None,
        schema_filter: Optional[str] = None,
        table_filter: Optional[str] = None,
        asset_type_filter: Optional[str] = None,
        system_filter: Optional[str] = None,
    ) -> List[ColumnDictionaryEntry]:
        """Apply faceted filters to a column list."""
        filtered = []
        for col in columns:
            if catalog_filter and col.catalog_name.lower() != catalog_filter.lower():
                continue
            if schema_filter and col.schema_name.lower() != schema_filter.lower():
                continue
            if table_filter:
                if (col.table_full_name.lower() != table_filter.lower()
                        and col.table_name.lower() != table_filter.lower()):
                    continue
            if asset_type_filter:
                if col.table_type.lower() != asset_type_filter.lower():
                    continue
            if system_filter:
                if not col.system_name or col.system_name.lower() != system_filter.lower():
                    continue
            filtered.append(col)
        return filtered

    # =========================================================================
    # Search: Full-Field, Uncapped
    # =========================================================================

    def search_columns(
        self,
        query: str,
        catalog_filter: Optional[str] = None,
        schema_filter: Optional[str] = None,
        table_filter: Optional[str] = None,
        asset_type_filter: Optional[str] = None,
        system_filter: Optional[str] = None,
        offset: int = 0,
        limit: int = 50,
    ) -> ColumnSearchResponse:
        """
        Search columns across all fields from both Contracts and Assets.

        Searches: column_name, description, column_label, business_terms,
        table_name, contract_name, system_name, catalog_name, schema_name.
        """
        logger.info(f"Searching columns: query='{query}', offset={offset}, limit={limit}")

        query_lower = query.lower().strip()

        if not query_lower:
            return ColumnSearchResponse(
                query=query, total_count=0, columns=[],
                has_more=False, offset=offset, limit=limit,
                filters_applied={}
            )

        try:
            contract_columns = self._get_columns_from_contracts()
            asset_columns = self._get_columns_from_assets()
            all_columns = self._merge_columns(contract_columns, asset_columns)

            # Apply faceted filters first
            filtered = self._apply_filters(
                all_columns,
                catalog_filter=catalog_filter,
                schema_filter=schema_filter,
                table_filter=table_filter,
                asset_type_filter=asset_type_filter,
                system_filter=system_filter,
            )

            # Full-field search
            matching = [col for col in filtered if self._matches_search(col, query_lower)]

            total_count = len(matching)
            has_more = (offset + limit) < total_count
            page = matching[offset:offset + limit]

            return ColumnSearchResponse(
                query=query,
                total_count=total_count,
                columns=page,
                has_more=has_more,
                offset=offset,
                limit=limit,
                filters_applied={
                    "catalog": catalog_filter,
                    "schema": schema_filter,
                    "table": table_filter,
                    "asset_type": asset_type_filter,
                    "system": system_filter,
                }
            )

        except Exception as e:
            logger.error(f"Error searching columns: {e}", exc_info=True)
            return ColumnSearchResponse(
                query=query, total_count=0, columns=[],
                has_more=False, offset=offset, limit=limit,
                filters_applied={}
            )

    def _matches_search(self, col: ColumnDictionaryEntry, query_lower: str) -> bool:
        """Check if a column matches a search query across all relevant fields."""
        if query_lower in col.column_name.lower():
            return True
        if col.description and query_lower in col.description.lower():
            return True
        if col.column_label and query_lower in col.column_label.lower():
            return True
        if col.table_name and query_lower in col.table_name.lower():
            return True
        if col.contract_name and query_lower in col.contract_name.lower():
            return True
        if col.system_name and query_lower in col.system_name.lower():
            return True
        if col.catalog_name and query_lower in col.catalog_name.lower():
            return True
        if col.schema_name and query_lower in col.schema_name.lower():
            return True
        # Business terms
        for term in col.business_terms:
            if query_lower in term.get("iri", "").lower():
                return True
            if query_lower in term.get("label", "").lower():
                return True
        return False

    # =========================================================================
    # Hierarchy Filters
    # =========================================================================

    def get_hierarchy_filters(self) -> HierarchyFilters:
        """
        Return available faceted filter values from both Contracts and Assets.
        Used to populate the UI filter dropdowns.
        """
        asset_types: set = set()
        systems: set = set()
        catalogs: set = set()
        schemas: set = set()

        try:
            contract_columns = self._get_columns_from_contracts()
            asset_columns = self._get_columns_from_assets()
            all_columns = self._merge_columns(contract_columns, asset_columns)

            for col in all_columns:
                if col.table_type:
                    asset_types.add(col.table_type)
                if col.system_name:
                    systems.add(col.system_name)
                if col.catalog_name:
                    catalogs.add(col.catalog_name)
                if col.schema_name:
                    schemas.add(col.schema_name)

        except Exception as e:
            logger.error(f"Error computing hierarchy filters: {e}", exc_info=True)

        return HierarchyFilters(
            asset_types=sorted(asset_types),
            systems=sorted(systems),
            catalogs=sorted(catalogs),
            schemas=sorted(schemas),
        )

    # =========================================================================
    # Table Methods
    # =========================================================================

    def get_table_list(
        self,
        catalog_filter: Optional[str] = None,
        schema_filter: Optional[str] = None,
    ) -> TableListResponse:
        """Get list of tables/schema objects for the filter dropdown."""
        logger.info(f"Getting table list (catalog={catalog_filter}, schema={schema_filter})")

        # Build (table_columns count, first-row metadata) in a single pass; the
        # final list is materialised after counting completes so column_count
        # reflects the full filtered total.
        table_columns: Dict[str, int] = {}
        table_meta: Dict[str, ColumnDictionaryEntry] = {}

        try:
            contract_columns = self._get_columns_from_contracts()
            asset_columns = self._get_columns_from_assets()
            all_columns = self._merge_columns(contract_columns, asset_columns)

            for col in all_columns:
                if catalog_filter and col.catalog_name.lower() != catalog_filter.lower():
                    continue
                if schema_filter and col.schema_name.lower() != schema_filter.lower():
                    continue
                full_name = col.table_full_name
                table_columns[full_name] = table_columns.get(full_name, 0) + 1
                table_meta.setdefault(full_name, col)

            tables: List[TableListItem] = [
                TableListItem(
                    full_name=full_name,
                    name=meta.table_name,
                    schema_name=meta.schema_name,
                    catalog_name=meta.catalog_name,
                    table_type=meta.table_type,
                    column_count=table_columns[full_name],
                    comment=None,
                    contract_id=meta.contract_id,
                    contract_name=meta.contract_name,
                    contract_version=meta.contract_version,
                    contract_status=meta.contract_status,
                )
                for full_name, meta in table_meta.items()
            ]

        except Exception as e:
            logger.error(f"Error getting table list: {e}", exc_info=True)
            tables = []

        total_columns = sum(table_columns.values())

        return TableListResponse(
            tables=tables,
            total_count=len(tables),
            total_column_count=total_columns,
        )

    def get_table_details(self, full_name: str) -> Optional[TableInfo]:
        """Get full table details including all columns from Unity Catalog."""
        logger.info(f"Getting table details: {full_name}")

        try:
            table = self.client.tables.get(full_name=full_name)

            parts = full_name.split(".")
            catalog_name = parts[0] if len(parts) >= 1 else ""
            schema_name = parts[1] if len(parts) >= 2 else ""
            table_name = parts[2] if len(parts) >= 3 else full_name

            columns = []
            if table.columns:
                for idx, col in enumerate(table.columns):
                    type_name_value = col.type_name.value if col.type_name else None
                    columns.append(ColumnInfo(
                        name=col.name,
                        type_text=col.type_text or type_name_value or "UNKNOWN",
                        type_name=type_name_value,
                        position=idx,
                        nullable=col.nullable if col.nullable is not None else True,
                        comment=col.comment,
                        partition_index=col.partition_index
                    ))

            tags = None
            if hasattr(table, 'tags') and table.tags:
                tags = {t.key: t.value for t in table.tags}

            return TableInfo(
                full_name=full_name,
                name=table_name,
                schema_name=schema_name,
                catalog_name=catalog_name,
                table_type=str(table.table_type).replace("TableType.", "") if table.table_type else "TABLE",
                owner=table.owner,
                comment=table.comment,
                created_at=table.created_at if hasattr(table, 'created_at') else None,
                updated_at=table.updated_at if hasattr(table, 'updated_at') else None,
                created_by=table.created_by if hasattr(table, 'created_by') else None,
                updated_by=table.updated_by if hasattr(table, 'updated_by') else None,
                storage_location=table.storage_location if hasattr(table, 'storage_location') else None,
                data_source_format=str(table.data_source_format) if hasattr(table, 'data_source_format') and table.data_source_format else None,
                columns=columns,
                tags=tags,
            )

        except Exception as e:
            logger.error(f"Error getting table details for {full_name}: {e}", exc_info=True)
            return None

    # =========================================================================
    # Lineage Methods (delegated to LineageService)
    # =========================================================================

    def get_table_lineage(self, table_fqn: str, direction: str = "both") -> LineageGraph:
        """Get lineage graph for a table."""
        dir_enum = LineageDirection(direction.lower())
        return self.lineage_service.get_table_lineage(table_fqn, dir_enum)

    def get_column_lineage(self, table_fqn: str, column_name: str, direction: str = "both") -> LineageGraph:
        """Get column-level lineage."""
        dir_enum = LineageDirection(direction.lower())
        return self.lineage_service.get_column_lineage(table_fqn, column_name, dir_enum)

    def get_impact_analysis(self, table_fqn: str, column_name: Optional[str] = None) -> ImpactAnalysis:
        """Get impact analysis for table or column change."""
        return self.lineage_service.get_impact_analysis(table_fqn, column_name)
