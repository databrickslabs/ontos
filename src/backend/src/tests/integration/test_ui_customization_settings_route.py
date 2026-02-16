from fastapi.testclient import TestClient


def test_get_ui_customization_includes_brand_name(client: TestClient):
    response = client.get("/api/settings/ui-customization")
    assert response.status_code == 200

    data = response.json()
    assert "brand_name" in data
