"""Value helpers of the ODPS export: the creation timestamp and the original domain."""
from datetime import datetime, timezone

from src.controller.data_products_manager import _odps_timestamp
from src.controller.domain_export_adapter import domain_export_adapter


def test_the_creation_timestamp_is_exported_in_utc():
    aware = datetime(2024, 6, 7, 10, 9, 10, tzinfo=timezone.utc)
    assert _odps_timestamp(aware) == "2024-06-07T10:09:10Z"
    assert _odps_timestamp(aware.replace(tzinfo=None)) == "2024-06-07T10:09:10Z"
    assert _odps_timestamp(None) is None


def test_an_original_domain_exported_as_json_text_is_read_as_a_list():
    doc = {"customProperties": [{"property": "ontosOriginalDomain", "value": '["sales", "ops"]'}]}
    assert domain_export_adapter.extract_original_domain_strings(doc) == ["sales", "ops"]
