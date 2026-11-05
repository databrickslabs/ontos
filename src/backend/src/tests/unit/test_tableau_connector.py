"""Tableau connector: path scheme, browse, metadata mapping, health check, secret handling."""

import base64
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from src.connectors.base import (
    ConnectorAuthenticationError,
    ConnectorConnectionError,
    ConnectorPermissionError,
    ListAssetsOptions,
)
from src.connectors.tableau import (
    TableauConnector,
    TableauConnectorConfig,
    clear_listing_cache,
    parse_path,
)
from src.connectors.tableau_client import GraphQLResult, PatAuth, TableauAPIError
from src.models.assets import UnifiedAssetType

PROJECTS = [
    {"id": "p1", "name": "Finance", "description": "Finance dashboards"},
    {"id": "p2", "name": "Sub", "parentProjectId": "p1"},
    {"id": "p3", "name": "Other"},
]
WORKBOOKS = [
    {"id": "wb1", "name": "Orders Overview", "project": {"id": "p1", "name": "Finance"}, "webpageUrl": "https://t/wb1"},
    {"id": "wb2", "name": "Elsewhere", "project": {"id": "p3", "name": "Other"}},
]
DATASOURCES = [{"id": "ds1", "name": "TPCH Orders", "project": {"id": "p1", "name": "Finance"}}]
VIEWS = [
    {"id": "v1", "name": "Orders Overview", "contentUrl": "OrdersOverview/sheets/OrdersOverview", "usage": {"totalViewCount": "12"}},
    {"id": "v2", "name": "Revenue by Status", "contentUrl": "OrdersOverview/sheets/RevenuebyStatus"},
]
DS_FIELDS = {
    "publishedDatasources": [{
        "luid": "ds1", "name": "TPCH Orders",
        "upstreamTables": [{"name": "orders", "schema": "tpch", "fullName": "[samples].[tpch].[orders]", "connectionType": "databricks"}],
        "fields": [
            {"__typename": "ColumnField", "name": "Total Price", "description": None, "role": "MEASURE", "dataType": "REAL",
             "columns": [{"name": "o_totalprice", "remoteType": "NUMERIC"}]},
            {"__typename": "CalculatedField", "name": "Avg Order Value", "description": "Revenue per order", "role": "MEASURE",
             "dataType": "REAL", "formula": "SUM([Total Price]) / COUNTD([Order Key])", "fields": [{"name": "Total Price"}, {"name": "Order Key"}]},
        ],
    }]
}


class FakeClient:
    server_url = "https://10xx.online.tableau.com"
    site_content_url = "mysite"
    identity = "pat:ontos"

    def __init__(self, graphql_data=None, site_role="SiteAdministratorCreator", metadata_api=True):
        self.graphql_data = graphql_data or {}
        self.site_role = site_role
        self.metadata_api = metadata_api

    def paginate(self, path, collection, item, params=None):
        return {
            "/projects": PROJECTS, "/workbooks": WORKBOOKS, "/datasources": DATASOURCES, "/workbooks/wb1/views": VIEWS,
        }.get(path, [])

    def get_json(self, path, params=None):
        if path == "/workbooks/wb1":
            return {"workbook": {**WORKBOOKS[0], "tags": {"tag": [{"label": "certified"}]}, "owner": {"id": "u1", "name": "owner@example.com"}}}
        if path == "/views/v1":
            return {"view": {**VIEWS[0], "workbook": {"id": "wb1"}}}
        if path == "/datasources/ds1":
            return {"datasource": {**DATASOURCES[0], "type": "databricks", "isCertified": True}}
        if path.startswith("/users/"):
            return {"user": {"siteRole": self.site_role}}
        raise TableauAPIError("not found", 404)

    def graphql(self, query, variables=None):
        if not self.metadata_api:
            raise TableauAPIError("Metadata API disabled", 400)
        if "WorkbookViews" in query:
            return GraphQLResult({"workbooks": [{"dashboards": [{"luid": "v1", "name": "Orders Overview"}], "sheets": [{"luid": "v2"}]}]})
        if "DatasourceFields" in query:
            return GraphQLResult(self.graphql_data or DS_FIELDS)
        return GraphQLResult({"publishedDatasourcesConnection": {"totalCount": 1}})

    def server_info(self):
        return {"productVersion": {"value": "2026.3.2"}, "restApiVersion": "3.30"}

    def session(self):
        return SimpleNamespace(user_id="u1")


@pytest.fixture(autouse=True)
def _fresh_cache():
    clear_listing_cache()
    yield
    clear_listing_cache()


def _connector(client=None):
    return TableauConnector(TableauConnectorConfig(server_url=FakeClient.server_url, site_content_url="mysite"), client=client or FakeClient())


def test_parse_path_keeps_field_names_with_dots():
    assert parse_path("p~a.p~b.ds~c.Sales.Net") == [("p", "a"), ("p", "b"), ("ds", "c"), ("field", "Sales.Net")]
    assert parse_path("") == []


def test_browse_projects_hierarchy():
    connector = _connector()
    top = connector.list_containers(None)
    assert [(c["name"], c["path"], c["type"]) for c in top] == [("Finance", "p~p1", "project"), ("Other", "p~p3", "project")]
    assert [c["path"] for c in connector.list_containers("p~p1")] == ["p~p1.p~p2"]
    assert connector.list_containers("p~p1.wb~wb1") == []


def test_list_assets_under_project_and_workbook():
    connector = _connector()
    in_project = connector.list_assets(ListAssetsOptions(path="p~p1"))
    assert [(a.name, a.identifier, a.asset_type) for a in in_project] == [
        ("Orders Overview", "p~p1.wb~wb1", UnifiedAssetType.TABLEAU_WORKBOOK),
        ("TPCH Orders", "p~p1.ds~ds1", UnifiedAssetType.TABLEAU_DATASOURCE),
    ]

    views = connector.list_assets(ListAssetsOptions(path="p~p1.wb~wb1"))
    assert [(v.name, v.asset_type) for v in views] == [
        ("Orders Overview", UnifiedAssetType.TABLEAU_DASHBOARD),
        ("Revenue by Status", UnifiedAssetType.TABLEAU_SHEET),
    ]
    assert views[0].url == "https://10xx.online.tableau.com/#/site/mysite/views/OrdersOverview/OrdersOverview"


def test_views_default_to_sheet_without_metadata_api():
    views = _connector(FakeClient(metadata_api=False)).list_assets(ListAssetsOptions(path="p~p1.wb~wb1"))
    assert {v.asset_type for v in views} == {UnifiedAssetType.TABLEAU_SHEET}


def test_datasource_metadata_maps_fields_to_columns():
    md = _connector().get_asset_metadata("p~p1.ds~ds1")

    assert md.asset_type == UnifiedAssetType.TABLEAU_DATASOURCE
    assert md.properties["is_certified"] is True
    assert md.properties["upstream_tables"][0]["fullName"] == "[samples].[tpch].[orders]"
    assert md.properties["lineage_redacted"] is False
    price, aov = md.schema_info.columns
    assert price.name == "Total Price" and price.properties["upstream_columns"] == ["o_totalprice"]
    assert price.properties["remote_type"] == "NUMERIC" and price.properties["is_calculated"] is False
    assert aov.properties["formula"] == "SUM([Total Price]) / COUNTD([Order Key])"
    assert aov.properties["referenced_fields"] == ["Total Price", "Order Key"]
    assert aov.description == "Revenue per order"


def test_redacted_upstream_tables_are_flagged():
    redacted = {"publishedDatasources": [{**DS_FIELDS["publishedDatasources"][0], "upstreamTables": [{"name": None}]}]}
    md = _connector(FakeClient(graphql_data=redacted)).get_asset_metadata("p~p1.ds~ds1")
    assert md.properties["lineage_redacted"] is True


def test_view_and_workbook_metadata():
    connector = _connector()
    view = connector.get_asset_metadata("p~p1.wb~wb1.v~v1")
    assert view.asset_type == UnifiedAssetType.TABLEAU_DASHBOARD
    assert view.properties["dashboardPlatform"] == "tableau"
    assert view.properties["view_count"] == 12
    wb = connector.get_asset_metadata("p~p1.wb~wb1")
    assert wb.tags == {"certified": ""}
    assert wb.ownership.owner == "owner@example.com"
    assert connector.get_asset_metadata("p~p1.ds~ds1.Total Price") is None


def test_health_check_warns_for_non_admin_and_missing_metadata_api():
    result = _connector(FakeClient(site_role="Creator", metadata_api=False)).health_check()
    assert result["healthy"] is True
    assert result["api_version"] == "3.30" and result["site_role"] == "Creator"
    assert result["metadata_api"] is False
    assert any("site administrator" in w for w in result["warnings"])
    assert any("tsm maintenance metadata-services enable" in w for w in result["warnings"])

    admin = _connector().health_check()
    assert admin["warnings"] == [] and admin["metadata_api"] is True


def test_secret_is_read_from_scope_and_decoded():
    ws = MagicMock()
    ws.secrets.get_secret.return_value = SimpleNamespace(value=base64.b64encode(b"pat-secret").decode())
    connector = TableauConnector(TableauConnectorConfig(
        server_url="https://t", auth_mode="pat", pat_name="ontos", secret_scope="tableau", secret_key="pat", workspace_client=ws,
    ))
    auth = connector._build_auth()
    assert auth == PatAuth("ontos", "pat-secret")
    ws.secrets.get_secret.assert_called_once_with(scope="tableau", key="pat")


def test_missing_secret_configuration_is_an_auth_error():
    connector = TableauConnector(TableauConnectorConfig(server_url="https://t", client_id="c", secret_id="k", username="u"))
    with pytest.raises(ConnectorAuthenticationError):
        connector._build_auth()
    assert connector.health_check()["healthy"] is False


class FailingClient(FakeClient):
    def __init__(self, status):
        super().__init__()
        self.status = status

    def get_json(self, path, params=None):
        raise TableauAPIError(f"failed {self.status}", self.status)


@pytest.mark.parametrize("status,error", [
    (401, ConnectorAuthenticationError),
    (403, ConnectorPermissionError),
    (500, ConnectorConnectionError),
])
def test_api_errors_map_to_connector_errors(status, error):
    with pytest.raises(error):
        _connector(FailingClient(status)).get_asset_metadata("p~p1.wb~wb1")


def test_not_found_is_none_but_outages_are_not_reported_missing():
    assert _connector(FailingClient(404)).get_asset_metadata("p~p1.wb~wb1") is None
    assert _connector(FailingClient(404)).validate_asset_exists("p~p1.wb~wb1").exists is False

    outage = _connector(FailingClient(503)).validate_asset_exists("p~p1.wb~wb1")
    assert outage.exists is False and outage.validated is False


def test_listing_cache_is_per_identity():
    class OtherUser(FakeClient):
        identity = "pat:other"

        def paginate(self, path, collection, item, params=None):
            return [] if path == "/projects" else super().paginate(path, collection, item, params)

    assert len(_connector().list_containers(None)) == 2
    assert _connector(OtherUser()).list_containers(None) == []
