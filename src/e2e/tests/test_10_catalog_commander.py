"""Catalog Commander — read-only tests against Unity Catalog."""
import pytest


def _find_catalog_and_schema(api, url):
    """Return (catalog_name, schema_name) or call pytest.skip."""
    resp = api.get(url("/api/catalogs"))
    if resp.status_code != 200:
        pytest.skip("Cannot list catalogs")
    catalogs = resp.json()
    if not catalogs:
        pytest.skip("No catalogs available")

    catalog_name = catalogs[0].get("name") or catalogs[0].get("catalog_name")
    if not catalog_name:
        pytest.skip("Catalog has no name field")

    resp = api.get(url(f"/api/catalogs/{catalog_name}/schemas"))
    if resp.status_code != 200:
        pytest.skip(f"Cannot list schemas for catalog '{catalog_name}'")
    schemas = resp.json()
    if not schemas:
        pytest.skip(f"No schemas available in catalog '{catalog_name}'")

    schema_name = schemas[0].get("name") or schemas[0].get("schema_name")
    if not schema_name:
        pytest.skip("Schema has no name field")

    return catalog_name, schema_name


def _find_table(api, url, catalog_name, schema_name):
    """Return table_name from the first available table, or call pytest.skip."""
    resp = api.get(url(f"/api/catalogs/{catalog_name}/schemas/{schema_name}/tables"))
    if resp.status_code != 200:
        pytest.skip(f"Cannot list tables for '{catalog_name}.{schema_name}'")
    tables = resp.json()
    if not tables:
        pytest.skip(f"No tables in '{catalog_name}.{schema_name}'")

    table_name = tables[0].get("name") or tables[0].get("table_name")
    if not table_name:
        pytest.skip("Table has no name field")

    return table_name


class TestCatalogCommander:

    @pytest.mark.readonly
    def test_list_catalogs(self, api, url):
        resp = api.get(url("/api/catalogs"))
        assert resp.status_code == 200
        body = resp.json()
        assert isinstance(body, list)

    @pytest.mark.readonly
    def test_catalog_health(self, api, url):
        resp = api.get(url("/api/catalogs/health"))
        assert resp.status_code == 200

    @pytest.mark.readonly
    def test_list_schemas_if_catalogs_exist(self, api, url):
        """List schemas for the first available catalog."""
        resp = api.get(url("/api/catalogs"))
        if resp.status_code != 200:
            pytest.skip("Cannot list catalogs")
        catalogs = resp.json()
        if not catalogs:
            pytest.skip("No catalogs available")

        catalog_name = catalogs[0].get("name") or catalogs[0].get("catalog_name")
        if not catalog_name:
            pytest.skip("Catalog has no name field")

        resp = api.get(url(f"/api/catalogs/{catalog_name}/schemas"))
        assert resp.status_code == 200
        assert isinstance(resp.json(), list)

    @pytest.mark.readonly
    def test_list_tables_in_schema(self, api, url):
        """List tables for the first available catalog/schema."""
        catalog_name, schema_name = _find_catalog_and_schema(api, url)

        resp = api.get(url(f"/api/catalogs/{catalog_name}/schemas/{schema_name}/tables"))
        assert resp.status_code == 200
        assert isinstance(resp.json(), list)

    @pytest.mark.readonly
    def test_list_views_in_schema(self, api, url):
        """List views for the first available catalog/schema."""
        catalog_name, schema_name = _find_catalog_and_schema(api, url)

        resp = api.get(url(f"/api/catalogs/{catalog_name}/schemas/{schema_name}/views"))
        assert resp.status_code == 200
        assert isinstance(resp.json(), list)

    @pytest.mark.readonly
    def test_list_functions_in_schema(self, api, url):
        """List functions for the first available catalog/schema."""
        catalog_name, schema_name = _find_catalog_and_schema(api, url)

        resp = api.get(url(f"/api/catalogs/{catalog_name}/schemas/{schema_name}/functions"))
        assert resp.status_code == 200
        assert isinstance(resp.json(), list)

    @pytest.mark.readonly
    def test_list_objects_in_schema(self, api, url):
        """List all objects (tables + views) for the first available catalog/schema."""
        catalog_name, schema_name = _find_catalog_and_schema(api, url)

        resp = api.get(url(f"/api/catalogs/{catalog_name}/schemas/{schema_name}/objects"))
        assert resp.status_code == 200
        assert isinstance(resp.json(), list)

    @pytest.mark.readonly
    def test_list_columns_for_object(self, api, url):
        """List columns for the first available table."""
        catalog_name, schema_name = _find_catalog_and_schema(api, url)
        table_name = _find_table(api, url, catalog_name, schema_name)

        resp = api.get(
            url(f"/api/catalogs/{catalog_name}/schemas/{schema_name}/objects/{table_name}/columns")
        )
        assert resp.status_code == 200
        assert isinstance(resp.json(), list)

    @pytest.mark.readonly
    def test_get_dataset_content(self, api, url):
        """Fetch a small sample of rows from the first available table."""
        catalog_name, schema_name = _find_catalog_and_schema(api, url)
        table_name = _find_table(api, url, catalog_name, schema_name)

        full_name = f"{catalog_name}.{schema_name}.{table_name}"
        resp = api.get(
            url(f"/api/catalogs/dataset/{full_name}"),
            params={"limit": 5},
        )

        if resp.status_code == 400:
            pytest.skip(f"Dataset path '{full_name}' rejected by validation (may contain special chars)")
        if resp.status_code == 403:
            pytest.skip(f"No SELECT privilege on '{full_name}'")
        if resp.status_code == 200:
            body = resp.json()
            # Response may be a dict with schema+rows or a plain list
            if isinstance(body, dict):
                assert "rows" in body or "data" in body or "schema" in body, (
                    f"Unexpected dataset response shape: {list(body.keys())}"
                )
            elif isinstance(body, list):
                if body == []:
                    pytest.skip(f"Table '{full_name}' exists but contains no rows")
            return

        assert resp.status_code == 200, (
            f"Unexpected status {resp.status_code}: {resp.text[:300]}"
        )
