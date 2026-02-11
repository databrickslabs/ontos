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
import os
import re
import time
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
            start_props_raw = row[col_idx.get("node_start_properties", 5)]
            end_props_raw = row[col_idx.get("node_end_properties", 6)]

            # Parse properties (handles VARIANT and STRING columns)
            start_props = self._parse_props(start_props_raw)
            end_props = self._parse_props(end_props_raw)

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

    # -----------------------------------------------------------------
    # LLM Configuration
    # -----------------------------------------------------------------

    def _get_foundational_endpoint(self) -> str:
        """Return the foundational LLM endpoint (falls back to main LLM_ENDPOINT via config validator)."""
        return getattr(self.settings, "LLM_FOUNDATIONAL_ENDPOINT", "") or getattr(self.settings, "LLM_ENDPOINT", "") or ""

    def get_llm_config(self) -> Dict[str, Any]:
        """Return the current LLM configuration state.

        The graph query panel is enabled whenever a foundational endpoint is
        configured — it does NOT require the global LLM_ENABLED flag, which
        gates the heavier conversational search feature.
        """
        if not self.settings:
            return {"enabled": False, "defaultModel": "", "maxTokens": 4096, "provider": "databricks"}

        endpoint = self._get_foundational_endpoint()
        return {
            "enabled": bool(endpoint),
            "defaultModel": endpoint,
            "maxTokens": 4096,
            "provider": "databricks",
        }

    # -----------------------------------------------------------------
    # Graph Query Translation (Cypher / Gremlin → SQL via LLM)
    # -----------------------------------------------------------------

    _TRANSLATE_SYSTEM_PROMPT = (
        "You are a SQL translation engine for Databricks Unity Catalog. "
        "You translate Cypher or Gremlin graph queries into valid Databricks SQL.\n\n"
        "The target table has the following schema:\n"
        "  node_start_id STRING, node_start_key STRING, relationship STRING,\n"
        "  node_end_id STRING, node_end_key STRING,\n"
        "  node_start_properties VARIANT, node_end_properties VARIANT\n\n"
        "Rules:\n"
        "- Each row represents an edge between two nodes.\n"
        "- node_start_id/node_start_key/node_start_properties describe the source node.\n"
        "- node_end_id/node_end_key/node_end_properties describe the target node.\n"
        "- relationship is the edge type (e.g. 'ALLIED_WITH', 'BORN_ON').\n"
        "- Node labels (types) are stored in node_start_key and node_end_key.\n"
        "- Some tables use relationship = 'EXISTS' for standalone nodes (self-edges).\n"
        "  Check the graph data context to see if EXISTS is listed as a relationship type.\n"
        "  If EXISTS is NOT listed, nodes only appear as edge endpoints.\n"
        "\n"
        "CRITICAL — Subgraph pattern for node-centric queries:\n"
        "When the user asks for specific nodes (e.g. 'dark characters'), use a CTE to find\n"
        "matching node IDs first, then return only edges BETWEEN those nodes. This avoids\n"
        "returning unrelated connected nodes.\n"
        "Example:\n"
        "  WITH matched AS (\n"
        "    SELECT DISTINCT node_start_id AS id FROM table\n"
        "    WHERE node_start_key = 'Character'\n"
        "      AND get_json_object(CAST(node_start_properties AS STRING), '$.alignment') = 'Dark'\n"
        "    UNION\n"
        "    SELECT DISTINCT node_end_id AS id FROM table\n"
        "    WHERE node_end_key = 'Character'\n"
        "      AND get_json_object(CAST(node_end_properties AS STRING), '$.alignment') = 'Dark'\n"
        "  )\n"
        "  SELECT * FROM table\n"
        "  WHERE node_start_id IN (SELECT id FROM matched)\n"
        "    AND node_end_id IN (SELECT id FROM matched)\n"
        "  LIMIT 5000\n"
        "\n"
        "For relationship queries (e.g. 'characters who fought in battles'), don't use the CTE\n"
        "pattern — just filter by relationship type and node types directly.\n"
        "\n"
        "- node_start_properties and node_end_properties are VARIANT columns.\n"
        "  IMPORTANT: Always use get_json_object with CAST to STRING for property access:\n"
        "  Example: get_json_object(CAST(node_start_properties AS STRING), '$.alignment') = 'Dark'\n"
        "  Example: CAST(get_json_object(CAST(node_start_properties AS STRING), '$.age') AS INT) > 30\n"
        "- For natural language queries, use LIKE for fuzzy string matching:\n"
        "  Example: LOWER(get_json_object(CAST(node_start_properties AS STRING), '$.alignment')) LIKE '%dark%'\n"
        "- For Cypher/Gremlin queries, use exact values from the graph data context.\n"
        "- IMPORTANT: Always prefer the actual property values shown in the graph data context.\n"
        "- IMPORTANT: Always SELECT * (all columns). Never select a subset of columns.\n"
        "  The downstream parser requires all columns to extract nodes and edges.\n"
        "- Always add LIMIT 5000 unless the user query already contains a limit.\n"
        "- Return ONLY the SQL query, nothing else — no markdown, no explanation.\n"
    )

    def _get_openai_client(self):
        """Get an OpenAI-compatible client for the configured LLM endpoint."""
        from openai import OpenAI

        token = None

        # Explicit token from settings / env (local dev)
        token = getattr(self.settings, "DATABRICKS_TOKEN", None) or os.environ.get("DATABRICKS_TOKEN")
        if token:
            logger.debug("Graph query LLM: using token from settings/environment")

        # Fall back to Databricks SDK OBO
        if not token:
            try:
                from databricks.sdk.core import Config
                config = Config()
                headers = config.authenticate()
                if headers and "Authorization" in headers:
                    auth_header = headers["Authorization"]
                    if auth_header.startswith("Bearer "):
                        token = auth_header[7:]
                        logger.debug("Graph query LLM: using SDK OBO token")
            except Exception as sdk_err:
                logger.debug(f"Could not get SDK token: {sdk_err}")

        if not token:
            raise RuntimeError("No authentication token available for LLM endpoint.")

        base_url = getattr(self.settings, "LLM_BASE_URL", None)
        if not base_url:
            host = getattr(self.settings, "DATABRICKS_HOST", "")
            if host:
                host = host.rstrip("/")
                if not host.startswith("http://") and not host.startswith("https://"):
                    host = f"https://{host}"
                base_url = f"{host}/serving-endpoints"

        if not base_url:
            raise RuntimeError("LLM_BASE_URL not configured.")

        return OpenAI(api_key=token, base_url=base_url)

    def _get_graph_schema(self, ws_client, table_name: str, warehouse_id: str) -> str:
        """Build a concise schema summary from the actual graph data for LLM context.

        Returns a text block describing actual column types, node types,
        relationship types, and sample property keys with distinct values.
        """
        safe_table = _validate_table_name(table_name)
        lines: List[str] = []

        try:
            # Step 0: Get actual column types via DESCRIBE
            try:
                sql = f"DESCRIBE TABLE {safe_table}"
                cols, desc_rows = self._execute_sql(ws_client, sql, warehouse_id)
                col_types = {r[0]: r[1] for r in desc_rows if r[0] and r[1]}
                if col_types:
                    lines.append("Actual column types: " + ", ".join(
                        f"{k} {v}" for k, v in col_types.items()
                    ))
            except Exception:
                pass

            # Step 1: All distinct node types (start and end)
            sql = (
                f"SELECT DISTINCT node_start_key FROM {safe_table} "
                f"UNION SELECT DISTINCT node_end_key FROM {safe_table} LIMIT 50"
            )
            _, rows = self._execute_sql(ws_client, sql, warehouse_id)
            node_types = sorted(set(r[0] for r in rows if r[0]))
            if node_types:
                lines.append(f"Node types: {', '.join(node_types)}")

            # Step 2: All distinct relationship types
            sql = f"SELECT DISTINCT relationship FROM {safe_table} LIMIT 50"
            _, rows = self._execute_sql(ws_client, sql, warehouse_id)
            rel_types = sorted(set(r[0] for r in rows if r[0]))
            if rel_types:
                lines.append(f"Relationship types: {', '.join(rel_types)}")
                if "EXISTS" not in rel_types:
                    lines.append("NOTE: No 'EXISTS' relationship found — nodes only appear as edge endpoints, not as standalone rows.")

            # Step 3: Sample properties per node type — use raw rows (no EXISTS filter)
            for ntype in node_types[:5]:
                safe_type = _escape_sql_string(ntype)
                sql = (
                    f"SELECT node_start_properties FROM {safe_table} "
                    f"WHERE node_start_key = '{safe_type}' "
                    f"AND node_start_properties IS NOT NULL LIMIT 10"
                )
                _, rows = self._execute_sql(ws_client, sql, warehouse_id)

                # Collect all property keys and their distinct values
                key_values: Dict[str, set] = {}
                for row in rows:
                    props = self._parse_props(row[0])
                    for k, v in props.items():
                        if k.startswith("_"):
                            continue
                        if k not in key_values:
                            key_values[k] = set()
                        if v is not None and len(key_values[k]) < 5:
                            key_values[k].add(str(v)[:50])

                if key_values:
                    prop_parts = []
                    for k, vals in list(key_values.items())[:8]:
                        distinct = sorted(vals)[:4]
                        prop_parts.append(f"{k} (e.g. {', '.join(repr(v) for v in distinct)})")
                    lines.append(f"  {ntype} properties: {'; '.join(prop_parts)}")

            # Step 4: If no properties were found, dump one raw row for debugging
            if not any("properties:" in l for l in lines):
                sql = f"SELECT * FROM {safe_table} LIMIT 1"
                cols, rows = self._execute_sql(ws_client, sql, warehouse_id)
                if rows:
                    raw_sample = {cols[i]: rows[0][i] for i in range(len(cols))}
                    lines.append(f"Sample raw row: {json.dumps(raw_sample, default=str)[:500]}")

        except Exception as e:
            logger.warning(f"Failed to fetch graph schema for LLM context: {e}", exc_info=True)

        return "\n".join(lines) if lines else "No schema information available."

    def _translate_to_sql(self, query: str, language: str, table_name: str,
                          graph_schema: str = "") -> str:
        """Translate a natural language, Cypher, or Gremlin query to Databricks SQL via LLM."""
        client = self._get_openai_client()
        endpoint = self._get_foundational_endpoint()

        safe_table = _validate_table_name(table_name)

        schema_block = ""
        if graph_schema:
            schema_block = f"\nGraph data context:\n{graph_schema}\n"

        if language == "natural":
            user_message = (
                f"Table: {safe_table}\n"
                f"{schema_block}"
                f"User request (natural language): {query}\n\n"
                "Write a Databricks SQL SELECT statement that answers this request. "
                "Return graph data (nodes and edges) that match the user's intent."
            )
        else:
            user_message = (
                f"Table: {safe_table}\n"
                f"{schema_block}"
                f"Language: {language}\n"
                f"Query: {query}\n\n"
                "Translate this to a Databricks SQL SELECT statement."
            )

        response = client.chat.completions.create(
            model=endpoint,
            messages=[
                {"role": "system", "content": self._TRANSLATE_SYSTEM_PROMPT},
                {"role": "user", "content": user_message},
            ],
            max_tokens=2048,
            temperature=0,
        )

        sql = response.choices[0].message.content.strip()
        # Strip markdown fencing if the model wraps it
        if sql.startswith("```"):
            sql = re.sub(r"^```(?:sql)?\s*", "", sql)
            sql = re.sub(r"\s*```$", "", sql)
        return sql.strip()

    @staticmethod
    def _parse_props(raw: Any) -> Dict[str, Any]:
        """Parse a properties value that may be a VARIANT JSON string, dict, or None."""
        if raw is None:
            return {}
        if isinstance(raw, dict):
            return raw
        if isinstance(raw, str):
            try:
                parsed = json.loads(raw)
                return parsed if isinstance(parsed, dict) else {}
            except (json.JSONDecodeError, TypeError):
                return {}
        return {}

    def _parse_query_results(self, columns: List[str], rows: List[List[Any]]) -> Dict[str, Any]:
        """Parse raw SQL result rows into nodes and edges, mirroring get_graph_data."""
        col_idx = {name: i for i, name in enumerate(columns)}
        nodes_map: Dict[str, Dict[str, Any]] = {}
        edges: List[Dict[str, Any]] = []

        has_edge_columns = "relationship" in col_idx

        for row in rows:
            start_id = row[col_idx["node_start_id"]] if "node_start_id" in col_idx else None
            start_key = row[col_idx.get("node_start_key", -1)] if "node_start_key" in col_idx else "Node"
            relationship = row[col_idx["relationship"]] if "relationship" in col_idx else None
            end_id = row[col_idx["node_end_id"]] if "node_end_id" in col_idx else None
            end_key = row[col_idx.get("node_end_key", -1)] if "node_end_key" in col_idx else "Node"
            start_props_raw = row[col_idx.get("node_start_properties", -1)] if "node_start_properties" in col_idx else None
            end_props_raw = row[col_idx.get("node_end_properties", -1)] if "node_end_properties" in col_idx else None

            # Parse properties — handles VARIANT (returned as JSON string by Statement Execution API) and dicts
            start_props = self._parse_props(start_props_raw)
            end_props = self._parse_props(end_props_raw)

            start_label = start_props.pop("_label", None) or (start_id or "")
            end_label = end_props.pop("_label", None) or (end_id or "")

            if start_id and start_id not in nodes_map:
                nodes_map[start_id] = {
                    "id": start_id,
                    "label": start_label,
                    "type": start_key or "Node",
                    "properties": start_props,
                    "status": "existing",
                }

            if end_id and end_id not in nodes_map:
                nodes_map[end_id] = {
                    "id": end_id,
                    "label": end_label,
                    "type": end_key or "Node",
                    "properties": end_props,
                    "status": "existing",
                }

            if relationship and relationship != "EXISTS" and start_id and end_id:
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
            "hasEdgeColumns": has_edge_columns,
        }

    def execute_graph_query(
        self,
        ws_client,
        warehouse_id: str,
        query: str,
        language: str,
        table_name: str,
        override_sql: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Translate a Cypher/Gremlin query to SQL via LLM, execute it, and
        return graph nodes/edges.  If *override_sql* is provided, skip
        translation and execute the SQL directly.
        """
        t0 = time.time()
        endpoint = self._get_foundational_endpoint()

        # Step 1: get SQL
        graph_schema = ""
        if override_sql:
            sql = override_sql
        else:
            # Fetch graph schema context so the LLM knows what types/properties exist
            graph_schema = self._get_graph_schema(ws_client, table_name, warehouse_id)
            logger.info(f"Graph schema context:\n{graph_schema}")
            sql = self._translate_to_sql(query, language, table_name, graph_schema=graph_schema)
        logger.info(f"Graph query SQL: {sql}")

        # Step 2: execute SQL
        try:
            columns, rows = self._execute_sql(ws_client, sql, warehouse_id)
        except RuntimeError as e:
            return {
                "success": False,
                "nodes": [],
                "edges": [],
                "sql": sql,
                "language": language,
                "originalQuery": query,
                "message": str(e),
            }

        # Step 3: parse results
        parsed = self._parse_query_results(columns, rows)
        duration = f"{time.time() - t0:.2f}s"

        # Detect vertex-only queries: CTE pattern means the user asked for specific nodes
        is_vertex_only = bool(re.search(r"(?i)\bWITH\s+matched\s+AS\b", sql))

        return {
            "success": True,
            "nodes": parsed["nodes"],
            "edges": parsed["edges"] if not is_vertex_only else [],
            "sql": sql,
            "language": language,
            "originalQuery": query,
            "rawRowCount": len(rows),
            "hasEdgeColumns": parsed.get("hasEdgeColumns", False),
            "vertexOnly": is_vertex_only,
            "metadata": {
                "source": "databricks",
                "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                "duration": duration,
                "translationModel": endpoint,
                "graphSchema": graph_schema if graph_schema else None,
            },
        }
