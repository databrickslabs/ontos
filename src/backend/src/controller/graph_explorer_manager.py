"""
Graph Explorer Manager.

Business logic for reading/writing property graph data
from/to Databricks Unity Catalog tables using the Statement Execution API.

Table schema (edge-centric, same as graph-demo):
  node_start_id STRING NOT NULL,
  node_start_key STRING NOT NULL,       -- node type
  relationship STRING NOT NULL,
  node_end_id STRING NOT NULL,
  node_end_key STRING NOT NULL,         -- node type
  node_start_properties STRING,         -- JSON
  node_end_properties STRING            -- JSON

Standalone nodes are stored as self-referencing edges with relationship = 'EXISTS'.
"""

import json
import re
from typing import Any, Dict, List, Optional, Tuple

from src.common.logging import get_logger

logger = get_logger(__name__)

# Regex for valid Unity Catalog table names
TABLE_NAME_PATTERN = re.compile(r'^[a-zA-Z0-9_`]+(\.[a-zA-Z0-9_`]+){0,2}$')

DEFAULT_TABLE_NAME = "main.default.property_graph_entity_edges"


def _validate_table_name(table_name: str) -> str:
    """Validate and sanitize a table name to prevent SQL injection."""
    cleaned = table_name.strip().strip('`')
    if not TABLE_NAME_PATTERN.match(cleaned):
        raise ValueError(f"Invalid table name: {table_name}")
    # Wrap parts in backticks for safety
    parts = cleaned.split('.')
    return '.'.join(f'`{p.strip("`")}`' for p in parts)


def _escape_sql_string(value: str) -> str:
    """Escape single quotes for SQL string literals."""
    return value.replace("'", "''")


class GraphExplorerManager:
    """Manages graph explorer operations via Databricks SQL."""

    def __init__(self, settings=None):
        self.settings = settings

    def _execute_sql(self, ws_client, sql: str, warehouse_id: str) -> Tuple[List[str], List[List[Any]]]:
        """Execute a SQL statement and return (columns, rows)."""
        logger.debug(f"Executing SQL: {sql[:200]}...")
        result = ws_client.statement_execution.execute_statement(
            statement=sql,
            warehouse_id=warehouse_id,
            wait_timeout="30s"
        )

        if result.status and result.status.state:
            state = str(result.status.state)
            if "FAILED" in state or "CANCELED" in state:
                error_msg = result.status.error.message if result.status.error else "Query failed"
                raise RuntimeError(f"SQL execution failed: {error_msg}")

        columns = []
        if result.manifest and result.manifest.schema and result.manifest.schema.columns:
            columns = [col.name for col in result.manifest.schema.columns]

        rows = []
        if result.result and result.result.data_array:
            rows = result.result.data_array

        return columns, rows

    def ensure_table_exists(self, ws_client, table_name: str, warehouse_id: str) -> None:
        """Create the graph table if it doesn't exist."""
        safe_table = _validate_table_name(table_name)
        sql = f"""CREATE TABLE IF NOT EXISTS {safe_table} (
            node_start_id STRING NOT NULL,
            node_start_key STRING NOT NULL,
            relationship STRING NOT NULL,
            node_end_id STRING NOT NULL,
            node_end_key STRING NOT NULL,
            node_start_properties STRING,
            node_end_properties STRING
        )"""
        self._execute_sql(ws_client, sql, warehouse_id)
        logger.info(f"Ensured table exists: {safe_table}")

    def get_graph_data(self, ws_client, table_name: str, warehouse_id: str) -> Dict[str, Any]:
        """Read all graph data from a Databricks table and return as nodes + edges."""
        safe_table = _validate_table_name(table_name)
        sql = f"SELECT * FROM {safe_table}"
        columns, rows = self._execute_sql(ws_client, sql, warehouse_id)

        if not columns:
            return {"nodes": [], "edges": []}

        # Build column index map
        col_idx = {name: i for i, name in enumerate(columns)}

        # Track unique nodes and edges
        nodes_map: Dict[str, Dict[str, Any]] = {}
        edges: List[Dict[str, Any]] = []

        for row in rows:
            start_id = row[col_idx.get("node_start_id", 0)] or ""
            start_key = row[col_idx.get("node_start_key", 1)] or "Node"
            relationship = row[col_idx.get("relationship", 2)] or ""
            end_id = row[col_idx.get("node_end_id", 3)] or ""
            end_key = row[col_idx.get("node_end_key", 4)] or "Node"
            start_props_str = row[col_idx.get("node_start_properties", 5)] or "{}"
            end_props_str = row[col_idx.get("node_end_properties", 6)] or "{}"

            # Parse properties
            try:
                start_props = json.loads(start_props_str) if start_props_str else {}
            except (json.JSONDecodeError, TypeError):
                start_props = {}
            try:
                end_props = json.loads(end_props_str) if end_props_str else {}
            except (json.JSONDecodeError, TypeError):
                end_props = {}

            # Extract label from properties or use id
            start_label = start_props.pop("_label", None) or start_id
            end_label = end_props.pop("_label", None) or end_id

            # Register start node
            if start_id and start_id not in nodes_map:
                nodes_map[start_id] = {
                    "id": start_id,
                    "label": start_label,
                    "type": start_key,
                    "properties": start_props,
                    "status": "existing",
                }

            # Register end node
            if end_id and end_id not in nodes_map:
                nodes_map[end_id] = {
                    "id": end_id,
                    "label": end_label,
                    "type": end_key,
                    "properties": end_props,
                    "status": "existing",
                }

            # Add edge (skip EXISTS self-references — those are standalone node markers)
            if relationship != "EXISTS" and start_id and end_id:
                edge_id = f"{start_id}-{relationship}-{end_id}"
                edges.append({
                    "id": edge_id,
                    "source": start_id,
                    "target": end_id,
                    "relationshipType": relationship,
                    "properties": {},
                    "status": "existing",
                })

        return {
            "nodes": list(nodes_map.values()),
            "edges": edges,
        }

    def write_nodes_and_edges(
        self,
        ws_client,
        table_name: str,
        warehouse_id: str,
        nodes: List[Dict[str, Any]],
        edges: List[Dict[str, Any]],
    ) -> Dict[str, Any]:
        """Write new nodes and edges to the Databricks table."""
        safe_table = _validate_table_name(table_name)
        nodes_written = 0
        edges_written = 0

        # Build a lookup of all nodes (from provided list) for edge writing
        node_map = {n["id"]: n for n in nodes}

        # Write standalone nodes as EXISTS self-referencing edges
        for node in nodes:
            node_id = _escape_sql_string(node["id"])
            node_type = _escape_sql_string(node.get("type", "Node"))
            props = dict(node.get("properties", {}))
            props["_label"] = node.get("label", node["id"])
            props_json = _escape_sql_string(json.dumps(props))

            sql = f"""INSERT INTO {safe_table}
                (node_start_id, node_start_key, relationship, node_end_id, node_end_key, node_start_properties, node_end_properties)
                VALUES ('{node_id}', '{node_type}', 'EXISTS', '{node_id}', '{node_type}', '{props_json}', '{props_json}')"""
            self._execute_sql(ws_client, sql, warehouse_id)
            nodes_written += 1

        # Write edges
        for edge in edges:
            source_id = _escape_sql_string(edge["source"])
            target_id = _escape_sql_string(edge["target"])
            rel_type = _escape_sql_string(edge.get("relationshipType", "RELATES_TO"))

            # Get source/target node info for properties
            source_node = node_map.get(edge["source"], {})
            target_node = node_map.get(edge["target"], {})

            source_type = _escape_sql_string(source_node.get("type", "Node"))
            target_type = _escape_sql_string(target_node.get("type", "Node"))

            source_props = dict(source_node.get("properties", {}))
            source_props["_label"] = source_node.get("label", edge["source"])
            target_props = dict(target_node.get("properties", {}))
            target_props["_label"] = target_node.get("label", edge["target"])

            source_props_json = _escape_sql_string(json.dumps(source_props))
            target_props_json = _escape_sql_string(json.dumps(target_props))

            sql = f"""INSERT INTO {safe_table}
                (node_start_id, node_start_key, relationship, node_end_id, node_end_key, node_start_properties, node_end_properties)
                VALUES ('{source_id}', '{source_type}', '{rel_type}', '{target_id}', '{target_type}', '{source_props_json}', '{target_props_json}')"""
            self._execute_sql(ws_client, sql, warehouse_id)
            edges_written += 1

        return {"nodesWritten": nodes_written, "edgesWritten": edges_written}

    def delete_node(self, ws_client, table_name: str, warehouse_id: str, node_id: str) -> None:
        """Delete a node and all its connected edges."""
        safe_table = _validate_table_name(table_name)
        safe_id = _escape_sql_string(node_id)
        sql = f"DELETE FROM {safe_table} WHERE node_start_id = '{safe_id}' OR node_end_id = '{safe_id}'"
        self._execute_sql(ws_client, sql, warehouse_id)
        logger.info(f"Deleted node {node_id} and connected edges from {safe_table}")

    def delete_edge(self, ws_client, table_name: str, warehouse_id: str, source_id: str, target_id: str, relationship_type: str) -> None:
        """Delete a specific edge."""
        safe_table = _validate_table_name(table_name)
        safe_source = _escape_sql_string(source_id)
        safe_target = _escape_sql_string(target_id)
        safe_rel = _escape_sql_string(relationship_type)
        sql = f"""DELETE FROM {safe_table}
            WHERE node_start_id = '{safe_source}'
              AND node_end_id = '{safe_target}'
              AND relationship = '{safe_rel}'"""
        self._execute_sql(ws_client, sql, warehouse_id)
        logger.info(f"Deleted edge {source_id} -[{relationship_type}]-> {target_id} from {safe_table}")

    def update_node(self, ws_client, table_name: str, warehouse_id: str, node_id: str, label: str, node_type: str, properties: Dict) -> None:
        """Update a node's properties, type, and label across all rows."""
        safe_table = _validate_table_name(table_name)
        safe_id = _escape_sql_string(node_id)
        safe_type = _escape_sql_string(node_type)
        props = dict(properties)
        props["_label"] = label
        props_json = _escape_sql_string(json.dumps(props))

        # Update as start node
        sql = f"""UPDATE {safe_table}
            SET node_start_key = '{safe_type}', node_start_properties = '{props_json}'
            WHERE node_start_id = '{safe_id}'"""
        self._execute_sql(ws_client, sql, warehouse_id)

        # Update as end node
        sql = f"""UPDATE {safe_table}
            SET node_end_key = '{safe_type}', node_end_properties = '{props_json}'
            WHERE node_end_id = '{safe_id}'"""
        self._execute_sql(ws_client, sql, warehouse_id)
        logger.info(f"Updated node {node_id} in {safe_table}")
