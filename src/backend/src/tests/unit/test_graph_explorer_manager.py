"""
Unit tests for GraphExplorerManager.

Tests the get_neighbors() method with mocked Databricks Statement Execution API.
"""

import json
import pytest
from unittest.mock import MagicMock, patch, call

from src.controller.graph_explorer_manager import GraphExplorerManager, _validate_table_name, _escape_sql_string


class TestValidateTableName:
    """Test table name validation and sanitization."""

    def test_valid_three_part_name(self):
        result = _validate_table_name("main.default.my_table")
        assert result == "`main`.`default`.`my_table`"

    def test_valid_single_part(self):
        result = _validate_table_name("my_table")
        assert result == "`my_table`"

    def test_rejects_sql_injection(self):
        with pytest.raises(ValueError, match="Invalid table name"):
            _validate_table_name("main; DROP TABLE users --")

    def test_strips_whitespace(self):
        result = _validate_table_name("  main.default.t  ")
        assert result == "`main`.`default`.`t`"


class TestEscapeSqlString:
    """Test SQL string escaping."""

    def test_escapes_single_quotes(self):
        assert _escape_sql_string("O'Brien") == "O''Brien"

    def test_no_change_for_safe_strings(self):
        assert _escape_sql_string("hello") == "hello"


class TestGraphExplorerManager:
    """Unit tests for GraphExplorerManager business logic."""

    @pytest.fixture
    def manager(self):
        settings = MagicMock()
        settings.DATABRICKS_WAREHOUSE_ID = "test-warehouse"
        settings.LLM_ENDPOINT = ""
        settings.GRAPH_MAX_EDGES = 10000
        settings.GRAPH_MAX_NODES = 5000
        settings.GRAPH_QUERY_TIMEOUT = "30s"
        settings.GRAPH_NEIGHBOR_LIMIT = 50
        return GraphExplorerManager(settings=settings)

    @pytest.fixture
    def mock_ws_client(self):
        return MagicMock()

    def _make_sql_result(self, columns, rows):
        """Helper to create a mock Statement Execution API result."""
        mock_result = MagicMock()
        mock_result.status.state = "SUCCEEDED"

        # Build column schema
        col_objects = []
        for col_name in columns:
            col_obj = MagicMock()
            col_obj.name = col_name
            col_objects.append(col_obj)

        mock_result.manifest.schema.columns = col_objects
        mock_result.result.data_array = rows

        return mock_result

    # ---------------------------------------------------------------
    # get_neighbors tests
    # ---------------------------------------------------------------

    def test_get_neighbors_both_directions(self, manager, mock_ws_client):
        """Test expanding all neighbors of a node."""
        columns = [
            "node_start_id", "node_start_key", "relationship",
            "node_end_id", "node_end_key",
            "node_start_properties", "node_end_properties",
        ]

        # First call: COUNT query
        count_result = self._make_sql_result(["count"], [["2"]])
        # Second call: SELECT query
        data_result = self._make_sql_result(columns, [
            ["alice", "Person", "KNOWS", "bob", "Person",
             json.dumps({"_label": "Alice"}), json.dumps({"_label": "Bob"})],
            ["alice", "Person", "WORKS_AT", "acme", "Company",
             json.dumps({"_label": "Alice"}), json.dumps({"_label": "Acme"})],
        ])

        mock_ws_client.statement_execution.execute_statement.side_effect = [
            count_result, data_result
        ]

        result = manager.get_neighbors(
            mock_ws_client, "main.default.test_graph", "wh-1",
            node_id="alice", direction="both", limit=25,
        )

        assert len(result["nodes"]) == 3  # alice, bob, acme
        assert len(result["edges"]) == 2  # KNOWS, WORKS_AT
        assert result["truncated"] is False
        assert result["totalAvailable"] == 2

        # Verify SQL contains the right direction filter
        calls = mock_ws_client.statement_execution.execute_statement.call_args_list
        count_sql = calls[0].kwargs["statement"]
        assert "node_start_id = 'alice' OR node_end_id = 'alice'" in count_sql
        assert "relationship != 'EXISTS'" in count_sql

    def test_get_neighbors_outgoing_only(self, manager, mock_ws_client):
        """Test expanding only outgoing edges."""
        columns = [
            "node_start_id", "node_start_key", "relationship",
            "node_end_id", "node_end_key",
            "node_start_properties", "node_end_properties",
        ]

        count_result = self._make_sql_result(["count"], [["1"]])
        data_result = self._make_sql_result(columns, [
            ["alice", "Person", "KNOWS", "bob", "Person",
             json.dumps({"_label": "Alice"}), json.dumps({"_label": "Bob"})],
        ])

        mock_ws_client.statement_execution.execute_statement.side_effect = [
            count_result, data_result
        ]

        result = manager.get_neighbors(
            mock_ws_client, "main.default.test_graph", "wh-1",
            node_id="alice", direction="outgoing", limit=25,
        )

        assert len(result["nodes"]) == 2  # alice, bob
        assert len(result["edges"]) == 1

        # Verify direction filter
        calls = mock_ws_client.statement_execution.execute_statement.call_args_list
        count_sql = calls[0].kwargs["statement"]
        assert "node_start_id = 'alice'" in count_sql
        assert "OR" not in count_sql

    def test_get_neighbors_incoming_only(self, manager, mock_ws_client):
        """Test expanding only incoming edges."""
        columns = [
            "node_start_id", "node_start_key", "relationship",
            "node_end_id", "node_end_key",
            "node_start_properties", "node_end_properties",
        ]

        count_result = self._make_sql_result(["count"], [["1"]])
        data_result = self._make_sql_result(columns, [
            ["bob", "Person", "KNOWS", "alice", "Person",
             json.dumps({"_label": "Bob"}), json.dumps({"_label": "Alice"})],
        ])

        mock_ws_client.statement_execution.execute_statement.side_effect = [
            count_result, data_result
        ]

        result = manager.get_neighbors(
            mock_ws_client, "main.default.test_graph", "wh-1",
            node_id="alice", direction="incoming", limit=25,
        )

        assert len(result["nodes"]) == 2
        calls = mock_ws_client.statement_execution.execute_statement.call_args_list
        count_sql = calls[0].kwargs["statement"]
        assert "node_end_id = 'alice'" in count_sql
        assert "node_start_id" not in count_sql

    def test_get_neighbors_with_edge_type_filter(self, manager, mock_ws_client):
        """Test filtering by specific edge types."""
        columns = [
            "node_start_id", "node_start_key", "relationship",
            "node_end_id", "node_end_key",
            "node_start_properties", "node_end_properties",
        ]

        count_result = self._make_sql_result(["count"], [["1"]])
        data_result = self._make_sql_result(columns, [
            ["alice", "Person", "KNOWS", "bob", "Person",
             json.dumps({"_label": "Alice"}), json.dumps({"_label": "Bob"})],
        ])

        mock_ws_client.statement_execution.execute_statement.side_effect = [
            count_result, data_result
        ]

        result = manager.get_neighbors(
            mock_ws_client, "main.default.test_graph", "wh-1",
            node_id="alice", direction="both",
            edge_types=["KNOWS"], limit=25,
        )

        assert len(result["edges"]) == 1
        assert result["edges"][0]["relationshipType"] == "KNOWS"

        # Verify edge type filter in SQL
        calls = mock_ws_client.statement_execution.execute_statement.call_args_list
        count_sql = calls[0].kwargs["statement"]
        assert "relationship IN ('KNOWS')" in count_sql

    def test_get_neighbors_truncated(self, manager, mock_ws_client):
        """Test truncation when more neighbors exist than the limit."""
        columns = [
            "node_start_id", "node_start_key", "relationship",
            "node_end_id", "node_end_key",
            "node_start_properties", "node_end_properties",
        ]

        # COUNT returns 50, but we're requesting limit=2
        count_result = self._make_sql_result(["count"], [["50"]])
        data_result = self._make_sql_result(columns, [
            ["alice", "Person", "KNOWS", "bob", "Person", None, None],
            ["alice", "Person", "KNOWS", "carol", "Person", None, None],
        ])

        mock_ws_client.statement_execution.execute_statement.side_effect = [
            count_result, data_result
        ]

        result = manager.get_neighbors(
            mock_ws_client, "main.default.test_graph", "wh-1",
            node_id="alice", direction="both", limit=2,
        )

        assert result["truncated"] is True
        assert result["totalAvailable"] == 50
        assert len(result["edges"]) == 2

    def test_get_neighbors_empty_result(self, manager, mock_ws_client):
        """Test expanding a node with no neighbors."""
        count_result = self._make_sql_result(["count"], [["0"]])
        data_result = self._make_sql_result([], [])
        # Override to handle empty columns
        data_result.manifest.schema.columns = []
        data_result.result.data_array = []

        mock_ws_client.statement_execution.execute_statement.side_effect = [
            count_result, data_result
        ]

        result = manager.get_neighbors(
            mock_ws_client, "main.default.test_graph", "wh-1",
            node_id="lonely_node", direction="both", limit=25,
        )

        assert len(result["nodes"]) == 0
        assert len(result["edges"]) == 0
        assert result["truncated"] is False
        assert result["totalAvailable"] == 0

    def test_get_neighbors_deduplicates_nodes(self, manager, mock_ws_client):
        """Test that nodes appearing in multiple edges are not duplicated."""
        columns = [
            "node_start_id", "node_start_key", "relationship",
            "node_end_id", "node_end_key",
            "node_start_properties", "node_end_properties",
        ]

        count_result = self._make_sql_result(["count"], [["2"]])
        # alice appears as start node in both rows
        data_result = self._make_sql_result(columns, [
            ["alice", "Person", "KNOWS", "bob", "Person", None, None],
            ["alice", "Person", "LIKES", "bob", "Person", None, None],
        ])

        mock_ws_client.statement_execution.execute_statement.side_effect = [
            count_result, data_result
        ]

        result = manager.get_neighbors(
            mock_ws_client, "main.default.test_graph", "wh-1",
            node_id="alice", direction="both", limit=25,
        )

        # Only 2 unique nodes despite appearing in multiple rows
        assert len(result["nodes"]) == 2
        node_ids = {n["id"] for n in result["nodes"]}
        assert node_ids == {"alice", "bob"}
        # But both edges are present
        assert len(result["edges"]) == 2

    def test_get_neighbors_sql_injection_protection(self, manager, mock_ws_client):
        """Test that node IDs with special characters are escaped."""
        columns = [
            "node_start_id", "node_start_key", "relationship",
            "node_end_id", "node_end_key",
            "node_start_properties", "node_end_properties",
        ]

        count_result = self._make_sql_result(["count"], [["0"]])
        data_result = self._make_sql_result(columns, [])
        data_result.result.data_array = []

        mock_ws_client.statement_execution.execute_statement.side_effect = [
            count_result, data_result
        ]

        # Node ID with a single quote (SQL injection attempt)
        result = manager.get_neighbors(
            mock_ws_client, "main.default.test_graph", "wh-1",
            node_id="alice'; DROP TABLE users; --", direction="both", limit=25,
        )

        # Verify the escaped string is in the SQL
        calls = mock_ws_client.statement_execution.execute_statement.call_args_list
        count_sql = calls[0].kwargs["statement"]
        assert "alice''; DROP TABLE users; --" in count_sql  # Double-escaped

    # ---------------------------------------------------------------
    # get_graph_data tests
    # ---------------------------------------------------------------

    def test_get_graph_data_basic(self, manager, mock_ws_client):
        """Test basic graph data loading."""
        columns = [
            "node_start_id", "node_start_key", "relationship",
            "node_end_id", "node_end_key",
            "node_start_properties", "node_end_properties",
        ]

        count_result = self._make_sql_result(["count"], [["2"]])
        data_result = self._make_sql_result(columns, [
            ["alice", "Person", "KNOWS", "bob", "Person",
             json.dumps({"_label": "Alice", "age": "30"}),
             json.dumps({"_label": "Bob"})],
            ["alice", "Person", "EXISTS", "alice", "Person",
             json.dumps({"_label": "Alice"}),
             json.dumps({"_label": "Alice"})],
        ])

        mock_ws_client.statement_execution.execute_statement.side_effect = [
            count_result, data_result
        ]

        data = manager.get_graph_data(mock_ws_client, "main.default.test", "wh-1")

        assert len(data["nodes"]) == 2  # alice, bob
        assert len(data["edges"]) == 1  # KNOWS only, EXISTS filtered out
        assert data["truncated"] is False

    def test_get_graph_data_empty_table(self, manager, mock_ws_client):
        """Test loading from an empty table."""
        count_result = self._make_sql_result(["count"], [["0"]])
        data_result = self._make_sql_result([], [])
        data_result.manifest.schema.columns = []
        data_result.result.data_array = []

        mock_ws_client.statement_execution.execute_statement.side_effect = [
            count_result, data_result
        ]

        data = manager.get_graph_data(mock_ws_client, "main.default.test", "wh-1")

        assert data["nodes"] == []
        assert data["edges"] == []
        assert data["truncated"] is False

    def test_get_graph_data_truncated(self, mock_ws_client):
        """Test that get_graph_data returns truncation info when data exceeds limit."""
        settings = MagicMock()
        settings.DATABRICKS_WAREHOUSE_ID = "test-warehouse"
        settings.LLM_ENDPOINT = ""
        settings.GRAPH_MAX_EDGES = 2  # Very low limit
        settings.GRAPH_QUERY_TIMEOUT = "30s"
        mgr = GraphExplorerManager(settings=settings)

        columns = [
            "node_start_id", "node_start_key", "relationship",
            "node_end_id", "node_end_key",
            "node_start_properties", "node_end_properties",
        ]

        # Total rows = 100, but limit is 2
        count_result = self._make_sql_result(["count"], [["100"]])
        data_result = self._make_sql_result(columns, [
            ["a", "N", "R", "b", "N", None, None],
            ["c", "N", "R", "d", "N", None, None],
        ])

        mock_ws_client.statement_execution.execute_statement.side_effect = [
            count_result, data_result
        ]

        data = mgr.get_graph_data(mock_ws_client, "main.default.test", "wh-1")

        assert data["truncated"] is True
        assert data["totalAvailable"] == 100

        # Verify LIMIT in the SQL
        calls = mock_ws_client.statement_execution.execute_statement.call_args_list
        select_sql = calls[1].kwargs["statement"]
        assert "LIMIT 2" in select_sql

    def test_get_graph_data_respects_max_rows_argument(self, manager, mock_ws_client):
        """Test that explicit max_rows overrides settings."""
        columns = [
            "node_start_id", "node_start_key", "relationship",
            "node_end_id", "node_end_key",
            "node_start_properties", "node_end_properties",
        ]

        count_result = self._make_sql_result(["count"], [["5"]])
        data_result = self._make_sql_result(columns, [
            ["a", "N", "R", "b", "N", None, None],
        ])

        mock_ws_client.statement_execution.execute_statement.side_effect = [
            count_result, data_result
        ]

        data = manager.get_graph_data(mock_ws_client, "main.default.test", "wh-1", max_rows=1)

        # Verify LIMIT in the SQL
        calls = mock_ws_client.statement_execution.execute_statement.call_args_list
        select_sql = calls[1].kwargs["statement"]
        assert "LIMIT 1" in select_sql

    def test_get_graph_data_uses_timeout_from_settings(self, mock_ws_client):
        """Test that _execute_sql uses GRAPH_QUERY_TIMEOUT from settings."""
        settings = MagicMock()
        settings.DATABRICKS_WAREHOUSE_ID = "test-warehouse"
        settings.LLM_ENDPOINT = ""
        settings.GRAPH_MAX_EDGES = 10000
        settings.GRAPH_QUERY_TIMEOUT = "60s"
        mgr = GraphExplorerManager(settings=settings)

        count_result = self._make_sql_result(["count"], [["0"]])
        data_result = self._make_sql_result([], [])
        data_result.manifest.schema.columns = []
        data_result.result.data_array = []

        mock_ws_client.statement_execution.execute_statement.side_effect = [
            count_result, data_result
        ]

        mgr.get_graph_data(mock_ws_client, "main.default.test", "wh-1")

        # Verify timeout was passed
        calls = mock_ws_client.statement_execution.execute_statement.call_args_list
        for c in calls:
            assert c.kwargs["wait_timeout"] == "60s"

    # ---------------------------------------------------------------
    # _parse_props tests
    # ---------------------------------------------------------------

    def test_parse_props_json_string(self, manager):
        result = manager._parse_props('{"name": "Alice", "age": 30}')
        assert result == {"name": "Alice", "age": 30}

    def test_parse_props_dict(self, manager):
        result = manager._parse_props({"name": "Alice"})
        assert result == {"name": "Alice"}

    def test_parse_props_none(self, manager):
        assert manager._parse_props(None) == {}

    def test_parse_props_invalid_json(self, manager):
        assert manager._parse_props("not json") == {}

    # ---------------------------------------------------------------
    # LLM config tests
    # ---------------------------------------------------------------

    def test_get_llm_config_disabled(self, manager):
        config = manager.get_llm_config()
        assert config["enabled"] is False

    def test_get_llm_config_enabled(self):
        settings = MagicMock()
        settings.LLM_ENDPOINT = "databricks-claude-sonnet"
        mgr = GraphExplorerManager(settings=settings)

        config = mgr.get_llm_config()
        assert config["enabled"] is True
        assert config["defaultModel"] == "databricks-claude-sonnet"
