"""
Tableau Connector

Implements the AssetConnector interface for Tableau Cloud and Tableau Server:
browse projects → workbooks / published data sources → views (dashboards and
sheets), with data-source fields exposed as columns.

Path semantics
--------------
The schema importer builds the hierarchy by splitting paths on ``.`` and stores
the path as the asset location, so paths are made of id segments (LUIDs never
contain dots) with a kind prefix:

    p~<project luid>[.p~<child project luid>...]
        .wb~<workbook luid>[.v~<view luid>]
        .ds~<published data source luid>[.<field name>]

Credentials
-----------
The Connected App secret (or PAT secret) is read from a Databricks secret scope at
use time; it is never stored in the connection config.
"""

import base64
import re
import time
from typing import Any, Dict, List, Optional, Tuple

from src.connectors.base import (
    AssetConnector,
    ConnectorAuthenticationError,
    ConnectorCapabilities,
    ConnectorConfig,
    ConnectorConnectionError,
    ConnectorPermissionError,
    DashboardSnapshot,
    LineageLink,
    ListAssetsOptions,
)
from src.connectors.tableau_client import (
    ConnectedAppAuth,
    PatAuth,
    TableauAPIError,
    TableauAuth,
    TableauClient,
)
from src.models.assets import (
    AssetInfo,
    AssetMetadata,
    AssetOwnership,
    AssetValidationResult,
    ColumnInfo,
    SchemaInfo,
    UnifiedAssetType,
)
from src.common.logging import get_logger

logger = get_logger(__name__)

PROJECT, WORKBOOK, DATASOURCE, VIEW = "p", "wb", "ds", "v"
_SEP = "~"


# ============================================================================
# Configuration
# ============================================================================

class TableauConnectorConfig(ConnectorConfig):
    """Configuration specific to the Tableau connector."""

    server_url: Optional[str] = None
    site_content_url: str = ""
    api_version: Optional[str] = None

    auth_mode: str = "connected_app"  # "connected_app" | "pat"
    client_id: Optional[str] = None
    secret_id: Optional[str] = None
    username: Optional[str] = None
    pat_name: Optional[str] = None

    # Databricks secret holding the Connected App secret value (or the PAT secret)
    secret_scope: Optional[str] = None
    secret_key: Optional[str] = None

    # Optional CA bundle path for Tableau Server with a private CA
    ca_bundle_path: Optional[str] = None
    include_hidden_views: bool = False
    # Catalog for Databricks tables Tableau names with two parts (schema.table),
    # e.g. connections that set a default catalog instead of naming it
    default_catalog: Optional[str] = None

    # Workspace client injected at build time for secret access
    workspace_client: Optional[Any] = None

    model_config = {"from_attributes": True, "arbitrary_types_allowed": True}


# ============================================================================
# Paths
# ============================================================================

def make_segment(kind: str, luid: str) -> str:
    return f"{kind}{_SEP}{luid}"


def parse_path(path: Optional[str]) -> List[Tuple[str, str]]:
    """``"p~a.wb~b"`` → ``[("p", "a"), ("wb", "b")]``. A trailing field name is kept as ``("field", name)``."""
    if not path:
        return []
    segments: List[Tuple[str, str]] = []
    parts = path.split(".")
    for i, part in enumerate(parts):
        kind, sep, ident = part.partition(_SEP)
        if sep and kind in (PROJECT, WORKBOOK, DATASOURCE, VIEW):
            segments.append((kind, ident))
        else:
            # Field names may contain dots: everything after the data source segment is the field
            segments.append(("field", ".".join(parts[i:])))
            break
    return segments


def _parse_ts(value: Optional[str]):
    if not value:
        return None
    from datetime import datetime
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


_UC_CONNECTION_TYPES = {"databricks", "spark"}
_TABLE_ASSET_TYPES = ["Table", "View", "Metric View"]


def parse_bracketed_name(full_name: Optional[str]) -> List[str]:
    """``"[samples].[tpch].[orders]"`` → ``["samples", "tpch", "orders"]`` (``]]`` escapes ``]``)."""
    if not full_name:
        return []
    parts: List[str] = []
    buf: List[str] = []
    in_brackets = False
    i = 0
    while i < len(full_name):
        ch = full_name[i]
        if in_brackets:
            if ch == "]":
                if full_name[i + 1:i + 2] == "]":
                    buf.append("]")
                    i += 2
                    continue
                in_brackets = False
            else:
                buf.append(ch)
        elif ch == "[":
            in_brackets = True
        elif ch == ".":
            parts.append("".join(buf))
            buf = []
        else:
            buf.append(ch)
        i += 1
    parts.append("".join(buf))
    return [p for p in parts if p]


def uc_table_name(table: Dict[str, Any], default_catalog: Optional[str] = None) -> Optional[str]:
    """Unity Catalog ``catalog.schema.table`` for a Tableau DatabaseTable, or None."""
    if (table.get("connectionType") or "").lower() not in _UC_CONNECTION_TYPES:
        return None
    parts = parse_bracketed_name(table.get("fullName"))
    if len(parts) == 2 and default_catalog:
        parts = [default_catalog] + parts
    return ".".join(parts) if len(parts) == 3 else None


# ============================================================================
# Listing cache (module level: connectors are rebuilt per request)
# ============================================================================

_LISTING_CACHE: Dict[Tuple[Any, ...], Tuple[float, Any]] = {}


def clear_listing_cache() -> None:
    _LISTING_CACHE.clear()


# ============================================================================
# Connector
# ============================================================================

_DATASOURCE_FIELDS_QUERY = """
query DatasourceFields($luid: String!) {
  publishedDatasources(filter: {luid: $luid}) {
    luid name description isCertified hasExtracts
    upstreamTables { name schema fullName connectionType }
    fields {
      __typename name description
      ... on ColumnField { role dataType columns { name remoteType table { ... on DatabaseTable { fullName connectionType } } } }
      ... on CalculatedField { role dataType formula fields { name } }
    }
  }
}
"""

_WORKBOOK_VIEWS_QUERY = """
query WorkbookViews($luid: String!) {
  workbooks(filter: {luid: $luid}) {
    upstreamTables { fullName connectionType }
    embeddedDatasources { fields { ... on CalculatedField { name formula } } }
    dashboards { luid name upstreamDatasources { ...ViewDatasource } }
    sheets { luid name upstreamDatasources { ...ViewDatasource } }
  }
}

# A view reads an embedded data source, which proxies the published one
fragment ViewDatasource on Datasource {
  ... on PublishedDatasource { luid }
  ... on EmbeddedDatasource { upstreamDatasources { luid } }
}
"""

_METADATA_PROBE_QUERY = "query { publishedDatasourcesConnection(first: 1) { totalCount } }"

_DATASOURCE_FORMULAS_QUERY = """
query DatasourceFormulas($luid: String!) {
  publishedDatasources(filter: {luid: $luid}) { fields { ... on CalculatedField { name formula } } }
}
"""

# Calculations that filter by the signed-in user: a snapshot rendered as the
# importer's account would show that account's rows to every Ontos user.
_USER_FUNCTION_RE = re.compile(
    r"\b(USERNAME|FULLNAME|USERDOMAIN|ISMEMBEROF|ISUSERNAME|ISFULLNAME|USERATTRIBUTE|USERATTRIBUTEINCLUDES)\s*\(",
    re.IGNORECASE,
)

# Tableau render errors (code 400074) by message
_RENDER_FAILURES = (
    ("refresh token", "auth_expired"),
    ("not connected", "not_connected"),
)


class TableauConnector(AssetConnector):
    """Asset connector for Tableau Cloud and Tableau Server."""

    connector_type = "tableau"
    display_name = "Tableau"
    description = "Tableau Cloud / Server workbooks, dashboards and published data sources"

    def __init__(
        self,
        config: Optional[TableauConnectorConfig] = None,
        client: Optional[TableauClient] = None,
    ):
        super().__init__(config or TableauConnectorConfig())
        self._client = client

    # ------------------------------------------------------------------
    # Client
    # ------------------------------------------------------------------

    @property
    def _cfg(self) -> TableauConnectorConfig:
        return self._config  # type: ignore[return-value]

    def _read_secret(self) -> str:
        cfg = self._cfg
        if not (cfg.secret_scope and cfg.secret_key):
            raise ConnectorAuthenticationError(
                "Tableau secret scope and key are not configured", connector_type=self.connector_type
            )
        if cfg.workspace_client is None:
            raise ConnectorAuthenticationError(
                "No workspace client available to read the Tableau secret", connector_type=self.connector_type
            )
        try:
            raw = cfg.workspace_client.secrets.get_secret(scope=cfg.secret_scope, key=cfg.secret_key).value
        except Exception as exc:
            raise ConnectorAuthenticationError(
                f"Could not read secret '{cfg.secret_scope}/{cfg.secret_key}': {exc}",
                connector_type=self.connector_type,
            ) from exc
        if not raw:
            raise ConnectorAuthenticationError(
                f"Secret '{cfg.secret_scope}/{cfg.secret_key}' is empty", connector_type=self.connector_type
            )
        text = raw.decode("utf-8") if isinstance(raw, bytes) else str(raw)
        # The secrets API returns the value base64-encoded
        try:
            return base64.b64decode(text, validate=True).decode("utf-8").strip()
        except Exception:
            return text.strip()

    def _build_auth(self) -> TableauAuth:
        cfg = self._cfg
        secret = self._read_secret()
        if cfg.auth_mode == "pat":
            if not cfg.pat_name:
                raise ConnectorAuthenticationError("PAT name is not configured", connector_type=self.connector_type)
            return PatAuth(token_name=cfg.pat_name, token_secret=secret)
        if not (cfg.client_id and cfg.secret_id and cfg.username):
            raise ConnectorAuthenticationError(
                "Connected App client id, secret id and username are required", connector_type=self.connector_type
            )
        return ConnectedAppAuth(client_id=cfg.client_id, secret_id=cfg.secret_id, secret_value=secret, username=cfg.username)

    def _ensure_client(self) -> TableauClient:
        if self._client is None:
            cfg = self._cfg
            if not cfg.server_url:
                raise ConnectorAuthenticationError("Tableau server URL is not configured", connector_type=self.connector_type)
            self._client = TableauClient(
                cfg.server_url,
                cfg.site_content_url,
                self._build_auth(),
                api_version=cfg.api_version,
                verify=cfg.ca_bundle_path or True,
                timeout=cfg.timeout_seconds,
            )
        return self._client

    def _translate(self, exc: TableauAPIError) -> Exception:
        """Connector error for a Tableau API error: 401 → auth, 403 → permission, else connection."""
        if exc.status == 401:
            return ConnectorAuthenticationError(str(exc), connector_type=self.connector_type)
        if exc.status == 403:
            return ConnectorPermissionError(str(exc), connector_type=self.connector_type)
        return ConnectorConnectionError(str(exc), connector_type=self.connector_type)

    def _call(self, fn, *args, **kwargs):
        """Run a client call, translating API errors to connector errors."""
        try:
            return fn(*args, **kwargs)
        except TableauAPIError as exc:
            raise self._translate(exc) from exc

    def _get_or_none(self, site_path: str) -> Optional[Dict[str, Any]]:
        """GET a REST resource; None only when Tableau says it does not exist (404)."""
        client = self._ensure_client()
        try:
            return client.get_json(site_path)
        except TableauAPIError as exc:
            if exc.status == 404:
                return None
            raise self._translate(exc) from exc

    def _cached(self, kind: str, loader, *key_parts):
        client = self._ensure_client()
        # Per identity: different accounts may see different content
        key = (client.server_url, client.site_content_url, client.identity, kind) + tuple(key_parts)
        hit = _LISTING_CACHE.get(key)
        ttl = self._cfg.cache_ttl_seconds
        if hit and time.time() - hit[0] < ttl:
            return hit[1]
        value = self._call(loader)
        _LISTING_CACHE[key] = (time.time(), value)
        return value

    # -- listings --------------------------------------------------------------

    def _projects(self) -> List[Dict[str, Any]]:
        client = self._ensure_client()
        return self._cached("projects", lambda: list(client.paginate("/projects", "projects", "project")))

    def _workbooks(self) -> List[Dict[str, Any]]:
        client = self._ensure_client()
        return self._cached("workbooks", lambda: list(client.paginate("/workbooks", "workbooks", "workbook")))

    def _datasources(self) -> List[Dict[str, Any]]:
        client = self._ensure_client()
        return self._cached("datasources", lambda: list(client.paginate("/datasources", "datasources", "datasource")))

    def _workbook_views(self, workbook_luid: str) -> List[Dict[str, Any]]:
        client = self._ensure_client()
        return self._cached(
            "views", lambda: list(client.paginate(
                f"/workbooks/{workbook_luid}/views", "views", "view", {"includeUsageStatistics": "true"},
            )), workbook_luid,
        )

    def _workbook_graph(self, workbook_luid: str) -> Dict[str, Any]:
        """Metadata API view of a workbook: view kinds, view → published data sources, upstream tables.

        Empty when the Metadata API is unavailable; callers then fall back to REST-only data.
        """
        client = self._ensure_client()

        def load() -> Dict[str, Any]:
            try:
                result = client.graphql(_WORKBOOK_VIEWS_QUERY, {"luid": workbook_luid})
            except TableauAPIError as exc:
                logger.warning(f"Metadata API query for workbook {workbook_luid} failed: {exc}")
                return {}
            graph: Dict[str, Any] = {"kinds": {}, "datasources": {}, "upstream_tables": [], "formulas": []}
            for wb in result.data.get("workbooks") or []:
                graph["upstream_tables"].extend(t for t in wb.get("upstreamTables") or [] if t)
                for embedded in wb.get("embeddedDatasources") or []:
                    graph["formulas"].extend(
                        (f.get("name"), f["formula"]) for f in (embedded or {}).get("fields") or [] if f and f.get("formula")
                    )
                for kind, views in ((UnifiedAssetType.TABLEAU_DASHBOARD, wb.get("dashboards")),
                                    (UnifiedAssetType.TABLEAU_SHEET, wb.get("sheets"))):
                    for view in views or []:
                        if not view.get("luid"):
                            continue
                        graph["kinds"].setdefault(view["luid"], kind)
                        published = graph["datasources"].setdefault(view["luid"], set())
                        for ds in view.get("upstreamDatasources") or []:
                            if not ds:
                                continue
                            if ds.get("luid"):
                                published.add(ds["luid"])
                            published.update(
                                up["luid"] for up in ds.get("upstreamDatasources") or [] if up and up.get("luid")
                            )
            graph["datasources"] = {k: sorted(v) for k, v in graph["datasources"].items()}
            return graph

        return self._cached("workbook_graph", load, workbook_luid)

    def _view_kinds(self, workbook_luid: str) -> Dict[str, UnifiedAssetType]:
        """View luid → dashboard/sheet, from the Metadata API (REST views don't say)."""
        return self._workbook_graph(workbook_luid).get("kinds", {})

    def _project_path(self, project_luid: Optional[str]) -> Optional[str]:
        """Connector path of a project (``p~root.p~child``), from the project hierarchy."""
        by_id = {p["id"]: p for p in self._projects()}
        chain: List[str] = []
        current = project_luid
        while current and current in by_id and len(chain) < 50:
            chain.append(make_segment(PROJECT, current))
            current = by_id[current].get("parentProjectId")
        if not chain or current:
            return None
        return ".".join(reversed(chain))

    def _datasource_path(self, datasource_luid: str) -> Optional[str]:
        ds = next((d for d in self._datasources() if d.get("id") == datasource_luid), None)
        project_path = self._project_path((ds or {}).get("project", {}).get("id")) if ds else None
        return f"{project_path}.{make_segment(DATASOURCE, datasource_luid)}" if project_path else None

    def _view_url(self, view: Dict[str, Any]) -> Optional[str]:
        content_url = view.get("contentUrl") or ""
        if "/sheets/" not in content_url:
            return None
        workbook_part, view_part = content_url.split("/sheets/", 1)
        site = self._cfg.site_content_url
        site_prefix = f"/site/{site}" if site else ""
        return f"{self._ensure_client().server_url}/#{site_prefix}/views/{workbook_part}/{view_part}"

    # ------------------------------------------------------------------
    # Capabilities
    # ------------------------------------------------------------------

    def _get_capabilities(self) -> ConnectorCapabilities:
        return ConnectorCapabilities(
            can_list_assets=True,
            can_get_metadata=True,
            can_validate_exists=True,
            can_get_schema=True,
            can_get_sample_data=False,
            can_get_statistics=False,
            can_get_lineage=True,
            supported_asset_types=[
                UnifiedAssetType.TABLEAU_PROJECT,
                UnifiedAssetType.TABLEAU_WORKBOOK,
                UnifiedAssetType.TABLEAU_DASHBOARD,
                UnifiedAssetType.TABLEAU_SHEET,
                UnifiedAssetType.TABLEAU_DATASOURCE,
            ],
        )

    @property
    def is_available(self) -> bool:
        if not self._config.enabled:
            return False
        try:
            self._ensure_client()
            return True
        except Exception:
            return False

    # ------------------------------------------------------------------
    # Browse
    # ------------------------------------------------------------------

    def list_containers(self, parent_path: Optional[str] = None) -> List[Dict[str, Any]]:
        """Projects at the top level, child projects under a project."""
        segments = parse_path(parent_path)
        if segments and segments[-1][0] != PROJECT:
            return []
        parent_luid = segments[-1][1] if segments else None
        prefix = f"{parent_path}." if parent_path else ""
        containers = []
        for project in self._projects():
            if (project.get("parentProjectId") or None) != parent_luid:
                continue
            containers.append({
                "name": project.get("name", ""),
                "type": "project",
                "path": prefix + make_segment(PROJECT, project["id"]),
                "comment": project.get("description") or None,
                "has_children": True,
            })
        return containers

    def list_assets(self, options: Optional[ListAssetsOptions] = None) -> List[AssetInfo]:
        """Workbooks and data sources under a project, views under a workbook."""
        options = options or ListAssetsOptions()
        path = options.path or ""
        segments = parse_path(path)
        if not segments:
            return []
        kind, luid = segments[-1]
        search = (options.search_term or "").lower()
        results: List[AssetInfo] = []

        if kind == PROJECT:
            for wb in self._workbooks():
                if (wb.get("project") or {}).get("id") != luid:
                    continue
                results.append(AssetInfo(
                    identifier=f"{path}.{make_segment(WORKBOOK, wb['id'])}",
                    name=wb.get("name", ""),
                    asset_type=UnifiedAssetType.TABLEAU_WORKBOOK,
                    connector_type=self.connector_type,
                    description=wb.get("description") or None,
                    path=f"{path}.{make_segment(WORKBOOK, wb['id'])}",
                    url=wb.get("webpageUrl"),
                ))
            for ds in self._datasources():
                if (ds.get("project") or {}).get("id") != luid:
                    continue
                results.append(AssetInfo(
                    identifier=f"{path}.{make_segment(DATASOURCE, ds['id'])}",
                    name=ds.get("name", ""),
                    asset_type=UnifiedAssetType.TABLEAU_DATASOURCE,
                    connector_type=self.connector_type,
                    description=ds.get("description") or None,
                    path=f"{path}.{make_segment(DATASOURCE, ds['id'])}",
                    url=ds.get("webpageUrl"),
                ))
        elif kind == WORKBOOK:
            kinds = self._view_kinds(luid)
            for view in self._workbook_views(luid):
                view_type = kinds.get(view["id"], UnifiedAssetType.TABLEAU_SHEET)
                results.append(AssetInfo(
                    identifier=f"{path}.{make_segment(VIEW, view['id'])}",
                    name=view.get("name", ""),
                    asset_type=view_type,
                    connector_type=self.connector_type,
                    path=f"{path}.{make_segment(VIEW, view['id'])}",
                    url=self._view_url(view),
                ))

        if search:
            results = [r for r in results if search in r.name.lower()]
        if options.asset_types:
            results = [r for r in results if r.asset_type in options.asset_types]
        return results[options.offset:options.offset + options.limit]

    # ------------------------------------------------------------------
    # Metadata
    # ------------------------------------------------------------------

    def get_asset_metadata(self, identifier: str) -> Optional[AssetMetadata]:
        segments = parse_path(identifier)
        if not segments or segments[-1][0] == "field":
            return None
        kind, luid = segments[-1]
        if kind == PROJECT:
            return self._project_metadata(identifier, luid)
        if kind == WORKBOOK:
            return self._workbook_metadata(identifier, luid)
        if kind == VIEW:
            workbook_luid = next((i for k, i in segments if k == WORKBOOK), None)
            return self._view_metadata(identifier, luid, workbook_luid)
        if kind == DATASOURCE:
            return self._datasource_metadata(identifier, luid)
        return None

    @staticmethod
    def _ownership(item: Dict[str, Any]) -> Optional[AssetOwnership]:
        owner = item.get("owner") or {}
        if not owner:
            return None
        return AssetOwnership(owner=owner.get("name") or owner.get("id"), owner_email=owner.get("email"))

    @staticmethod
    def _tags(item: Dict[str, Any]) -> Dict[str, str]:
        tags = (item.get("tags") or {}).get("tag") or []
        return {t["label"]: "" for t in tags if t.get("label")}

    def _project_metadata(self, identifier: str, luid: str) -> Optional[AssetMetadata]:
        project = next((p for p in self._projects() if p.get("id") == luid), None)
        if project is None:
            return None
        return AssetMetadata(
            identifier=identifier, name=project.get("name", ""), asset_type=UnifiedAssetType.TABLEAU_PROJECT,
            connector_type=self.connector_type, description=project.get("description") or None, path=identifier,
            ownership=self._ownership(project),
            properties={"tableau_luid": luid, "parent_project_luid": project.get("parentProjectId")},
            created_at=_parse_ts(project.get("createdAt")), updated_at=_parse_ts(project.get("updatedAt")),
        )

    def _workbook_metadata(self, identifier: str, luid: str) -> Optional[AssetMetadata]:
        body = self._get_or_none(f"/workbooks/{luid}")
        if body is None:
            return None
        wb = body.get("workbook") or {}
        return AssetMetadata(
            identifier=identifier, name=wb.get("name", ""), asset_type=UnifiedAssetType.TABLEAU_WORKBOOK,
            connector_type=self.connector_type, description=wb.get("description") or None, path=identifier,
            url=wb.get("webpageUrl"), ownership=self._ownership(wb), tags=self._tags(wb),
            properties={
                "tableau_luid": luid,
                "tableau_project": (wb.get("project") or {}).get("name"),
                "tableau_content_url": wb.get("contentUrl"),
                "tableau_default_view_luid": wb.get("defaultViewId"),
                "upstream_tables": [
                    {k: t.get(k) for k in ("fullName", "connectionType")}
                    for t in self._workbook_graph(luid).get("upstream_tables", [])
                ],
            },
            created_at=_parse_ts(wb.get("createdAt")), updated_at=_parse_ts(wb.get("updatedAt")),
        )

    def _view_metadata(self, identifier: str, luid: str, workbook_luid: Optional[str]) -> Optional[AssetMetadata]:
        body = self._get_or_none(f"/views/{luid}")
        if body is None:
            return None
        view = body.get("view") or {}
        workbook_luid = workbook_luid or (view.get("workbook") or {}).get("id")
        view_type = self._view_kinds(workbook_luid).get(luid, UnifiedAssetType.TABLEAU_SHEET) if workbook_luid else UnifiedAssetType.TABLEAU_SHEET
        usage = next((v.get("usage") for v in self._workbook_views(workbook_luid) if v.get("id") == luid), None) if workbook_luid else None
        url = self._view_url(view)
        return AssetMetadata(
            identifier=identifier, name=view.get("name", ""), asset_type=view_type,
            connector_type=self.connector_type, path=identifier, url=url,
            ownership=self._ownership(view), tags=self._tags(view),
            properties={
                "tableau_luid": luid,
                "tableau_workbook_luid": workbook_luid,
                "tableau_content_url": view.get("contentUrl"),
                "dashboardUrl": url,
                "dashboardPlatform": "tableau",
                "view_count": int((usage or {}).get("totalViewCount") or 0) if usage else None,
                "upstream_datasource_luids": (
                    self._workbook_graph(workbook_luid).get("datasources", {}).get(luid) if workbook_luid else None
                ),
            },
            created_at=_parse_ts(view.get("createdAt")), updated_at=_parse_ts(view.get("updatedAt")),
        )

    def _datasource_metadata(self, identifier: str, luid: str) -> Optional[AssetMetadata]:
        client = self._ensure_client()
        body = self._get_or_none(f"/datasources/{luid}")
        if body is None:
            return None
        ds = body.get("datasource") or {}

        columns: List[ColumnInfo] = []
        properties: Dict[str, Any] = {
            "tableau_luid": luid,
            "tableau_project": (ds.get("project") or {}).get("name"),
            "tableau_connection_type": ds.get("type"),
            "is_certified": bool(ds.get("isCertified")),
            "has_extracts": bool(ds.get("hasExtracts")),
        }
        try:
            result = client.graphql(_DATASOURCE_FIELDS_QUERY, {"luid": luid})
            node = next(iter(result.data.get("publishedDatasources") or []), None)
            if not result.is_complete:
                properties["metadata_incomplete"] = result.warning_codes
            if node:
                upstream = node.get("upstreamTables") or []
                properties["upstream_tables"] = [
                    {k: t.get(k) for k in ("name", "schema", "fullName", "connectionType")} for t in upstream if t
                ]
                properties["lineage_redacted"] = any((t or {}).get("name") is None for t in upstream)
                for f in node.get("fields") or []:
                    columns.append(self._field_column(f))
        except TableauAPIError as exc:
            logger.warning(f"Metadata API query for data source {luid} failed: {exc}")
            properties["metadata_api_error"] = str(exc)

        return AssetMetadata(
            identifier=identifier, name=ds.get("name", ""), asset_type=UnifiedAssetType.TABLEAU_DATASOURCE,
            connector_type=self.connector_type, description=ds.get("description") or None, path=identifier,
            url=ds.get("webpageUrl"), ownership=self._ownership(ds), tags=self._tags(ds),
            schema_info=SchemaInfo(columns=columns) if columns else None,
            properties=properties,
            created_at=_parse_ts(ds.get("createdAt")), updated_at=_parse_ts(ds.get("updatedAt")),
        )

    def _field_column(self, field: Dict[str, Any]) -> ColumnInfo:
        typename = field.get("__typename") or "Field"
        remote_columns = field.get("columns") or []
        remote_type = next((c.get("remoteType") for c in remote_columns if c.get("remoteType")), None)
        data_type = field.get("dataType") or remote_type or "UNKNOWN"
        props: Dict[str, Any] = {
            "tableau_field_type": typename,
            "role": field.get("role"),
            "tableau_data_type": field.get("dataType"),
            "remote_type": remote_type,
            "is_calculated": typename == "CalculatedField",
        }
        if typename == "CalculatedField":
            props["formula"] = field.get("formula")
            props["referenced_fields"] = [f.get("name") for f in field.get("fields") or [] if f.get("name")]
        if remote_columns:
            props["upstream_columns"] = [c.get("name") for c in remote_columns if c.get("name")]
            refs = []
            for c in remote_columns:
                table = uc_table_name(c.get("table") or {}, self._cfg.default_catalog)
                if table and c.get("name"):
                    refs.append(f"{table}.{c['name']}")
            if refs:
                props["upstream_column_refs"] = refs
        return ColumnInfo(
            name=field.get("name") or "",
            data_type=str(data_type),
            description=field.get("description") or None,
            properties={k: v for k, v in props.items() if v is not None},
        )

    # ------------------------------------------------------------------
    # Import hooks
    # ------------------------------------------------------------------

    def import_properties(self, metadata: AssetMetadata) -> Dict[str, Any]:
        props = {k: v for k, v in (metadata.properties or {}).items() if v not in (None, [], {})}
        if metadata.url:
            props["url"] = metadata.url
        if metadata.updated_at:
            props["source_updated_at"] = metadata.updated_at.isoformat()
        return props

    def import_column_properties(self, column: Any) -> Dict[str, Any]:
        return dict(getattr(column, "properties", None) or {})

    def lineage_links(self, path: str, metadata: AssetMetadata) -> List[LineageLink]:
        """Semantic model → UC tables, fields → UC columns / other fields, views → data sources,
        workbooks → UC tables (covers embedded data sources)."""
        props = metadata.properties or {}
        links: List[LineageLink] = []
        catalog = self._cfg.default_catalog

        def table_links(source: str) -> None:
            for table in props.get("upstream_tables") or []:
                name = uc_table_name(table, catalog)
                if name:
                    links.append(LineageLink(
                        source_path=source, relationship_type="consumesFrom",
                        target_location=name, target_asset_types=_TABLE_ASSET_TYPES,
                    ))

        if metadata.asset_type == UnifiedAssetType.TABLEAU_DATASOURCE:
            table_links(path)
            for column in (metadata.schema_info.columns if metadata.schema_info else []):
                column_path = f"{path}.{column.name}"
                for ref in column.properties.get("upstream_column_refs") or []:
                    links.append(LineageLink(
                        source_path=column_path, relationship_type="derivedFrom",
                        target_location=ref, target_asset_types=["Column"],
                    ))
                for referenced in column.properties.get("referenced_fields") or []:
                    if referenced != column.name:
                        links.append(LineageLink(
                            source_path=column_path, relationship_type="derivedFrom",
                            target_path=f"{path}.{referenced}",
                        ))
        elif metadata.asset_type == UnifiedAssetType.TABLEAU_WORKBOOK:
            table_links(path)
        elif metadata.asset_type in (UnifiedAssetType.TABLEAU_DASHBOARD, UnifiedAssetType.TABLEAU_SHEET):
            for ds_luid in props.get("upstream_datasource_luids") or []:
                ds_path = self._datasource_path(ds_luid)
                if ds_path:
                    links.append(LineageLink(source_path=path, relationship_type="consumesFrom", target_path=ds_path))
        return links

    # ------------------------------------------------------------------
    # Snapshots
    # ------------------------------------------------------------------

    def wants_snapshot(self, metadata: AssetMetadata) -> bool:
        return metadata.asset_type == UnifiedAssetType.TABLEAU_DASHBOARD

    @staticmethod
    def _view_ids(path: str) -> Tuple[Optional[str], Optional[str]]:
        segments = dict((k, i) for k, i in parse_path(path) if k in (WORKBOOK, VIEW))
        return segments.get(WORKBOOK), segments.get(VIEW)

    @staticmethod
    def _render_failure(exc: TableauAPIError) -> str:
        if exc.status == 403:
            return "forbidden"
        message = str(exc).lower()
        for marker, status in _RENDER_FAILURES:
            if marker in message:
                return status
        return "error"

    def capture_snapshot(self, path: str) -> Optional[DashboardSnapshot]:
        """High-resolution view image; the cached thumbnail when rendering fails."""
        workbook_luid, view_luid = self._view_ids(path)
        if not view_luid:
            return None
        client = self._ensure_client()
        try:
            content = client.get_bytes(f"/views/{view_luid}/image", {"resolution": "high", "maxAge": 1})
            if content:
                return DashboardSnapshot(status="ok", content=content, source="view_image")
            status, error = "empty", "Tableau returned an empty image"
        except TableauAPIError as exc:
            status, error = self._render_failure(exc), str(exc)
        snapshot = DashboardSnapshot(status=status, error=error)
        if workbook_luid:
            try:
                preview = client.get_bytes(f"/workbooks/{workbook_luid}/views/{view_luid}/previewImage")
                if preview:
                    snapshot.content, snapshot.source = preview, "preview_image"
            except TableauAPIError as exc:
                logger.info(f"No preview image for view {view_luid}: {exc}")
        return snapshot

    def _datasource_formulas(self, datasource_luid: str) -> List[Tuple[str, str]]:
        client = self._ensure_client()

        def load() -> List[Tuple[str, str]]:
            result = client.graphql(_DATASOURCE_FORMULAS_QUERY, {"luid": datasource_luid})
            return [
                (f.get("name"), f["formula"])
                for node in result.data.get("publishedDatasources") or []
                for f in (node or {}).get("fields") or [] if f and f.get("formula")
            ]

        return self._cached("ds_formulas", load, datasource_luid)

    def snapshot_risks(self, path: str) -> List[str]:
        """Calculations behind the view that filter by the signed-in user."""
        workbook_luid, view_luid = self._view_ids(path)
        if not workbook_luid:
            return []
        graph = self._workbook_graph(workbook_luid)
        if "kinds" not in graph:
            # Fail closed: without the Metadata API, user filters cannot be ruled out
            return ["Could not check the calculations for user filters (Metadata API unavailable)"]
        formulas = list(graph.get("formulas") or [])
        risks = []
        for ds_luid in graph.get("datasources", {}).get(view_luid) or []:
            try:
                formulas.extend(self._datasource_formulas(ds_luid))
            except Exception as exc:
                logger.warning(f"Could not read formulas of data source {ds_luid}: {exc}")
                risks.append(f"Could not check the calculations of data source {ds_luid} for user filters")
        for name, formula in formulas:
            match = _USER_FUNCTION_RE.search(formula or "")
            if match:
                risks.append(f"'{name}' uses {match.group(1).upper()}()")
        return sorted(set(risks))

    def validate_asset_exists(self, identifier: str) -> AssetValidationResult:
        try:
            metadata = self.get_asset_metadata(identifier)
        except Exception as exc:
            return AssetValidationResult(identifier=identifier, exists=False, validated=False, message=str(exc))
        if metadata is None:
            return AssetValidationResult(identifier=identifier, exists=False, message="Not found")
        return AssetValidationResult(identifier=identifier, exists=True, asset_type=metadata.asset_type)

    # ------------------------------------------------------------------
    # Health check
    # ------------------------------------------------------------------

    def health_check(self) -> Dict[str, Any]:
        """Version, sign-in, site role and Metadata API availability, with actionable warnings."""
        result: Dict[str, Any] = {
            "connector_type": self.connector_type,
            "available": False,
            "enabled": self._config.enabled,
            "healthy": False,
            "warnings": [],
        }
        try:
            client = self._ensure_client()
            info = client.server_info()
            result["product_version"] = (info.get("productVersion") or {}).get("value")
            result["api_version"] = info.get("restApiVersion")
            session = client.session()
            result["available"] = True
            result["healthy"] = True
        except Exception as exc:
            result["error"] = str(exc)
            return result

        try:
            user = client.get_json(f"/users/{session.user_id}").get("user") or {}
            site_role = user.get("siteRole") or ""
            result["site_role"] = site_role
            if "SiteAdministrator" not in site_role and site_role != "ServerAdministrator":
                result["warnings"].append(
                    "The account is not a site administrator: Tableau hides database, table and column "
                    "names of content it does not own, so lineage to Unity Catalog will be incomplete."
                )
        except TableauAPIError as exc:
            result["warnings"].append(f"Could not read the account's site role: {exc}")

        try:
            probe = client.graphql(_METADATA_PROBE_QUERY)
            result["metadata_api"] = True
            if not probe.is_complete:
                result["warnings"].append(f"Metadata API returned incomplete results: {probe.warning_codes}")
        except TableauAPIError as exc:
            result["metadata_api"] = False
            result["warnings"].append(
                "The Metadata API is not available (on Tableau Server it must be enabled with "
                f"'tsm maintenance metadata-services enable'): {exc}"
            )
        return result
