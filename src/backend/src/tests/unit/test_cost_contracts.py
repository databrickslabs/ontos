from datetime import date
from pathlib import Path

import pytest
from pydantic import ValidationError

from src.db_models.costs import CostItemDb
from src.models.costs import CostItemCreate, CostItemUpdate

DATA_DIR = Path(__file__).parents[2] / "data"
DEMO_FILES = (
    "demo_data_auto.sql",
    "demo_data_fsi.sql",
    "demo_data_hls.sql",
    "demo_data_mfg.sql",
    "demo_data_retail.sql",
)


def _cost_create(cost_center: str) -> CostItemCreate:
    return CostItemCreate(
        entity_id="product-1",
        entity_type="data_product",
        cost_center=cost_center,
        amount_cents=100,
        currency="USD",
        start_month=date(2026, 1, 1),
    )


@pytest.mark.parametrize("value", ["infrastructure", " HR ", "storage", "Maintenance", "other"])
def test_api_models_normalize_supported_cost_centers(value: str):
    assert _cost_create(value).cost_center == value.strip().upper()
    assert CostItemUpdate(cost_center=value).cost_center == value.strip().upper()


def test_api_model_rejects_unknown_cost_center():
    with pytest.raises(ValidationError):
        _cost_create("tools")


def test_database_model_normalizes_and_rejects_cost_centers():
    assert CostItemDb(cost_center=" infrastructure ").cost_center == "INFRASTRUCTURE"
    with pytest.raises(ValueError, match="Unsupported cost center"):
        CostItemDb(cost_center="tools")


@pytest.mark.parametrize("filename", DEMO_FILES)
def test_demo_cost_rows_use_canonical_cost_centers(filename: str):
    sql = (DATA_DIR / filename).read_text()
    cost_block = sql.split("INSERT INTO cost_items", 1)[1].split("ON CONFLICT", 1)[0]

    for invalid_value in (
        "'infrastructure'",
        "'hr'",
        "'storage'",
        "'maintenance'",
        "'other'",
        "'tools'",
    ):
        assert invalid_value not in cost_block
