"""Tests for the Schema Importer browse layer and the Databricks connector
listing contract that backs it.

These tests pin the path-depth contract documented in the Schema Importer PRD
([docs/prds/prd-schema-importer-table-expand-recursion.md]):

  * 0 segments -> catalogs
  * 1 segment  -> schemas
  * 2 segments -> assets in schema
  * 3+ segments -> empty list (leaf FQN; columns come from metadata)

…and that the browse layer enriches leaf-asset paths with column nodes sourced
from `get_asset_metadata().schema_info`.
"""

from typing import List, Optional
from unittest.mock import MagicMock
from uuid import uuid4

import pytest

from src.connectors.base import (
    AssetConnector,
    ConnectorCapabilities,
    ListAssetsOptions,
)
from src.connectors.databricks import (
    DatabricksConnector,
    DatabricksConnectorConfig,
)
from src.controller.schema_import_manager import (
    SchemaImportManager,
    _display_type,
    _has_children,
)
from src.models.assets import (
    AssetInfo,
    AssetMetadata,
    AssetValidationResult,
    ColumnInfo,
    SchemaInfo,
    UnifiedAssetType,
)


# ---------------------------------------------------------------------------
# Databricks connector path-depth contract
# ---------------------------------------------------------------------------


def _make_databricks_connector_with_listers() -> DatabricksConnector:
    """Build a DatabricksConnector wired to a mock WorkspaceClient.

    We patch the internal `_list_*` helpers per test so we never touch the
    SDK and so test failures are about behavior, not network mocks.
    """
    ws = MagicMock()
    connector = DatabricksConnector(
        config=DatabricksConnectorConfig(),
        workspace_client=ws,
    )
    return connector


class TestDatabricksListAssetsPathDepth:
    """The Databricks connector must respect the path-depth contract used by
    the Schema Importer tree, otherwise expanding a table re-lists schema
    siblings (the original recursion bug)."""

    def test_three_segment_path_returns_empty(self):
        """`catalog.schema.table` is a leaf FQN — listing must return []."""
        connector = _make_databricks_connector_with_listers()
        # Fail loudly if any listing helper is invoked at all.
        connector._list_catalogs = MagicMock(side_effect=AssertionError("must not list catalogs"))
        connector._list_schemas = MagicMock(side_effect=AssertionError("must not list schemas"))
        connector._list_tables = MagicMock(side_effect=AssertionError("must not list tables"))
        connector._list_functions = MagicMock(side_effect=AssertionError("must not list functions"))
        connector._list_models = MagicMock(side_effect=AssertionError("must not list models"))
        connector._list_volumes = MagicMock(side_effect=AssertionError("must not list volumes"))
        connector._list_metrics = MagicMock(side_effect=AssertionError("must not list metrics"))

        result = connector.list_assets(ListAssetsOptions(path="cat.sch.table"))

        assert result == []

    def test_four_segment_path_returns_empty(self):
        """A column-level FQN must also be treated as a leaf for listing."""
        connector = _make_databricks_connector_with_listers()
        connector._list_tables = MagicMock(side_effect=AssertionError("must not list tables"))

        result = connector.list_assets(ListAssetsOptions(path="cat.sch.table.col"))

        assert result == []

    def test_three_segment_path_ignores_asset_types_filter(self):
        """The leaf guard must trigger regardless of any asset-types filter."""
        connector = _make_databricks_connector_with_listers()
        connector._list_tables = MagicMock(side_effect=AssertionError("must not list tables"))

        result = connector.list_assets(
            ListAssetsOptions(
                path="cat.sch.table",
                asset_types=[UnifiedAssetType.UC_TABLE, UnifiedAssetType.UC_VIEW],
            )
        )

        assert result == []

    def test_two_segment_path_still_lists_schema_assets(self):
        """Regression guard: schema-level browsing must still work — we did
        not over-correct and break the normal expand-schema flow."""
        connector = _make_databricks_connector_with_listers()

        sample_table = AssetInfo(
            identifier="cat.sch.table_a",
            name="table_a",
            asset_type=UnifiedAssetType.UC_TABLE,
            connector_type="databricks",
            path="cat.sch.table_a",
            catalog="cat",
            schema_name="sch",
        )
        connector._list_tables = MagicMock(return_value=[sample_table])
        connector._list_functions = MagicMock(return_value=[])
        connector._list_models = MagicMock(return_value=[])
        connector._list_volumes = MagicMock(return_value=[])
        connector._list_metrics = MagicMock(return_value=[])

        result = connector.list_assets(ListAssetsOptions(path="cat.sch"))

        assert result == [sample_table]
        connector._list_tables.assert_called_once()

    def test_zero_segment_path_lists_catalogs(self):
        """Sanity check on the other end of the contract."""
        connector = _make_databricks_connector_with_listers()
        connector._list_catalogs = MagicMock(return_value=[])

        connector.list_assets(ListAssetsOptions(path=""))

        connector._list_catalogs.assert_called_once()


# ---------------------------------------------------------------------------
# Schema Importer browse: column enrichment
# ---------------------------------------------------------------------------


class _StubConnector(AssetConnector):
    """Minimal connector that returns canned listing + metadata for browse tests.

    Only the methods actually called by `SchemaImportManager.browse` are
    implemented; the abstract surface is satisfied with no-ops.
    """

    connector_type = "stub"
    display_name = "Stub Connector"

    def __init__(
        self,
        containers_by_path: Optional[dict] = None,
        assets_by_path: Optional[dict] = None,
        metadata_by_path: Optional[dict] = None,
        metadata_raises: bool = False,
    ):
        super().__init__()
        self._containers = containers_by_path or {}
        self._assets = assets_by_path or {}
        self._metadata = metadata_by_path or {}
        self._metadata_raises = metadata_raises

    def _get_capabilities(self) -> ConnectorCapabilities:
        return ConnectorCapabilities()

    def list_assets(self, options: Optional[ListAssetsOptions] = None) -> List[AssetInfo]:
        path = (options.path if options else "") or ""
        return list(self._assets.get(path, []))

    def list_containers(self, parent_path: Optional[str] = None) -> List[dict]:
        return list(self._containers.get(parent_path or "", []))

    def get_asset_metadata(self, identifier: str) -> Optional[AssetMetadata]:
        if self._metadata_raises:
            raise RuntimeError("simulated metadata failure")
        return self._metadata.get(identifier)

    def validate_asset_exists(self, identifier: str) -> AssetValidationResult:
        return AssetValidationResult(identifier=identifier, exists=True, validated=True)


def _make_manager_with_stub_connector(stub: _StubConnector) -> SchemaImportManager:
    """Wrap a stub connector so the manager can fetch it like a real one."""
    connections_manager = MagicMock()
    connections_manager.get_connector_for_connection.return_value = stub
    assets_manager = MagicMock()
    return SchemaImportManager(
        connections_manager=connections_manager,
        assets_manager=assets_manager,
    )


def _table_metadata(path: str, columns: List[ColumnInfo]) -> AssetMetadata:
    return AssetMetadata(
        identifier=path,
        name=path.split(".")[-1],
        asset_type=UnifiedAssetType.UC_TABLE,
        connector_type="stub",
        schema_info=SchemaInfo(columns=columns),
    )


class TestSchemaImporterBrowseColumnEnrichment:
    """The browse layer must expose columns under a leaf asset path so the UI
    tree shows columns instead of nothing (or, before the fix, schema siblings)."""

    def test_columns_appear_under_table_path(self):
        path = "cat.sch.table_a"
        cols = [
            ColumnInfo(name="id", data_type="int", nullable=False, description="Primary id"),
            ColumnInfo(name="info", data_type="string", nullable=True),
        ]
        stub = _StubConnector(
            containers_by_path={path: []},
            assets_by_path={path: []},
            metadata_by_path={path: _table_metadata(path, cols)},
        )
        manager = _make_manager_with_stub_connector(stub)

        response = manager.browse(db=MagicMock(), connection_id=uuid4(), path=path)

        col_nodes = [n for n in response.nodes if n.node_type == "column"]
        assert [n.name for n in col_nodes] == ["id", "info"]
        assert [n.path for n in col_nodes] == [f"{path}.id", f"{path}.info"]
        assert all(n.has_children is False for n in col_nodes)
        # Description carries through from ColumnInfo
        assert col_nodes[0].description == "Primary id"

    def test_no_metadata_means_no_column_nodes(self):
        """When the connector returns no metadata for a path, the browse
        response is just listing nodes — never invented columns."""
        path = "cat.sch.table_b"
        stub = _StubConnector(
            assets_by_path={path: []},
            metadata_by_path={},  # nothing for this path
        )
        manager = _make_manager_with_stub_connector(stub)

        response = manager.browse(db=MagicMock(), connection_id=uuid4(), path=path)

        assert all(n.node_type != "column" for n in response.nodes)

    def test_metadata_fetch_failure_degrades_silently(self):
        """A failing metadata call must not break browsing or surface a
        top-level error — the listing-only response still comes back."""
        path = "cat.sch.table_c"
        sample_asset = AssetInfo(
            identifier="cat.sch.table_c.x",  # placeholder leaf inside, would be deduped
            name="x",
            asset_type=UnifiedAssetType.UC_TABLE,
            connector_type="stub",
        )
        stub = _StubConnector(
            assets_by_path={path: [sample_asset]},
            metadata_raises=True,
        )
        manager = _make_manager_with_stub_connector(stub)

        response = manager.browse(db=MagicMock(), connection_id=uuid4(), path=path)

        assert response.error is None
        # Listing nodes still present despite the metadata failure
        assert any(n.path == "cat.sch.table_c.x" for n in response.nodes)
        assert all(n.node_type != "column" for n in response.nodes)

    def test_column_node_dedupes_against_listing_node(self):
        """If the listing already produced a node at the same path as a column
        (defensive corner case), enrichment must not duplicate it."""
        path = "cat.sch.table_d"
        # A pre-existing node at the would-be column path
        clashing_asset = AssetInfo(
            identifier=f"{path}.id",
            name="id",
            asset_type=UnifiedAssetType.UC_TABLE,  # bogus type, just for path clash
            connector_type="stub",
        )
        stub = _StubConnector(
            assets_by_path={path: [clashing_asset]},
            metadata_by_path={
                path: _table_metadata(
                    path,
                    [ColumnInfo(name="id", data_type="int")],
                )
            },
        )
        manager = _make_manager_with_stub_connector(stub)

        response = manager.browse(db=MagicMock(), connection_id=uuid4(), path=path)

        matching = [n for n in response.nodes if n.path == f"{path}.id"]
        assert len(matching) == 1

    def test_no_metadata_call_for_root_browse(self):
        """Browsing the root (no path) must not even attempt column enrichment.

        This keeps the top-level catalog list cheap and avoids spurious
        metadata calls on connectors that error on empty identifiers.
        """
        stub = _StubConnector(
            containers_by_path={"": [
                {"name": "cat", "type": "catalog", "path": "cat", "has_children": True},
            ]},
            metadata_raises=True,  # would explode if called
        )
        manager = _make_manager_with_stub_connector(stub)

        response = manager.browse(db=MagicMock(), connection_id=uuid4(), path=None)

        assert response.error is None
        assert [n.path for n in response.nodes] == ["cat"]

    def test_listing_marks_column_bearing_leaves_as_expandable(self):
        """`_has_children` must return True for leaf types whose
        `get_asset_metadata().schema_info` is populated, otherwise the UI
        renders no expand chevron and the user can never see columns or
        function parameters.

        Anchored to the bug in https://github.com/databrickslabs/ontos/pull/289
        where `system.ai.python_exec` (a UC function) appeared as `has_children=false`.
        """
        expandable = {
            # UC: tables + view variants + function parameters
            UnifiedAssetType.UC_TABLE,
            UnifiedAssetType.UC_VIEW,
            UnifiedAssetType.UC_MATERIALIZED_VIEW,
            UnifiedAssetType.UC_STREAMING_TABLE,
            UnifiedAssetType.UC_FUNCTION,
            # BigQuery
            UnifiedAssetType.BQ_TABLE,
            UnifiedAssetType.BQ_VIEW,
            UnifiedAssetType.BQ_MATERIALIZED_VIEW,
            UnifiedAssetType.BQ_EXTERNAL_TABLE,
            UnifiedAssetType.BQ_ROUTINE,
            # Snowflake
            UnifiedAssetType.SNOWFLAKE_TABLE,
            UnifiedAssetType.SNOWFLAKE_VIEW,
            UnifiedAssetType.SNOWFLAKE_MATERIALIZED_VIEW,
            UnifiedAssetType.SNOWFLAKE_FUNCTION,
            UnifiedAssetType.SNOWFLAKE_PROCEDURE,
        }
        for at in expandable:
            assert _has_children(at) is True, f"expected {at} to be expandable"

    def test_listing_marks_non_column_leaves_as_non_expandable(self):
        """Models, volumes, datasets etc. must stay non-expandable — there is
        nothing under them, and a chevron would just yield an empty list."""
        non_expandable = {
            UnifiedAssetType.UC_MODEL,
            UnifiedAssetType.UC_VOLUME,
            UnifiedAssetType.BQ_MODEL,
            # None case
        }
        for at in non_expandable:
            assert _has_children(at) is False, f"expected {at} to be non-expandable"
        assert _has_children(None) is False

    def test_display_type_distinguishes_functions_models_volumes(self):
        """Browse-time labels must preserve source-system semantics.

        Before this fix `_display_type` went through `_TYPE_MAP` which
        collapses functions/volumes/procedures to the import-time
        Ontos type "System" — leaving the user with a tree that
        labels every UC function and volume as "system". The display
        map keeps them distinct so the right icon is picked and the
        label next to the name is meaningful.
        """
        cases = {
            # UC
            UnifiedAssetType.UC_TABLE: "table",
            UnifiedAssetType.UC_VIEW: "view",
            UnifiedAssetType.UC_MATERIALIZED_VIEW: "view",
            UnifiedAssetType.UC_STREAMING_TABLE: "table",
            UnifiedAssetType.UC_FUNCTION: "function",
            UnifiedAssetType.UC_MODEL: "model",
            UnifiedAssetType.UC_VOLUME: "volume",
            # BQ
            UnifiedAssetType.BQ_ROUTINE: "routine",
            UnifiedAssetType.BQ_MODEL: "model",
            UnifiedAssetType.BQ_EXTERNAL_TABLE: "table",
            # Snowflake
            UnifiedAssetType.SNOWFLAKE_FUNCTION: "function",
            UnifiedAssetType.SNOWFLAKE_PROCEDURE: "procedure",
            UnifiedAssetType.SNOWFLAKE_MATERIALIZED_VIEW: "view",
        }
        for at, expected in cases.items():
            assert _display_type(at) == expected, f"{at} -> {_display_type(at)}, want {expected}"

        assert _display_type(None) == "unknown"
