"""The publication fields of DataProduct are server-managed: the OpenAPI says so."""
from src.models.data_products import DataProduct

FIELDS = ("publication_scope", "published_at", "published_by")


def _props():
    return DataProduct.model_json_schema()["properties"]


def test_publication_fields_are_read_only_in_schema():
    props = _props()
    for name in FIELDS:
        assert props[name].get("readOnly") is True, name


def test_publication_fields_say_how_to_publish():
    props = _props()
    for name in FIELDS:
        description = props[name]["description"]
        assert "/publish" in description, name
        assert "/set-publication-scope" in description, name
        assert "/unpublish" in description, name


def test_other_fields_stay_writable():
    props = _props()
    assert "readOnly" not in props["name"]
    assert "readOnly" not in props["status"]
