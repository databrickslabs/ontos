"""Unit tests for the ODCS/ODPS import discriminator (src.common.entity_kind)."""
import pytest

from src.common.entity_kind import classify_import_entity, describe_import_entity


@pytest.mark.parametrize("kind,expected", [
    ("DataContract", "contract"),
    ("DataProduct", "product"),
    ("data-product", "product"),
    ("Data Contract", "contract"),
    ("data_product", "product"),
])
def test_kind_is_primary_signal(kind, expected):
    assert classify_import_entity({"kind": kind, "name": "x"}) == expected


def test_declared_but_unknown_kind_is_not_guessed():
    # A declared-but-foreign kind must not be force-classified as either standard.
    assert classify_import_entity({"kind": "Dataset", "name": "x"}) == "unknown"


def test_structural_fallback_when_kind_absent():
    assert classify_import_entity({"name": "p", "outputPorts": [{"name": "o"}]}) == "product"
    assert classify_import_entity({"name": "p", "inputPorts": [{"name": "i"}]}) == "product"
    assert classify_import_entity({"name": "c", "schema": [{"name": "t"}]}) == "contract"
    assert classify_import_entity({"name": "c", "datasets": [{"name": "d"}]}) == "contract"


def test_ambiguous_or_sparse_payload_is_unknown():
    # No kind and markers for both (or neither) → don't reject a legitimate file.
    assert classify_import_entity({"name": "x"}) == "unknown"
    assert classify_import_entity({"name": "x", "schema": [], "outputPorts": []}) == "unknown"
    assert classify_import_entity("not-a-dict") == "unknown"


def test_describe_labels():
    assert describe_import_entity({"kind": "DataProduct"}) == "ODPS Data Product"
    assert describe_import_entity({"kind": "DataContract"}) == "ODCS Data Contract"
    assert describe_import_entity({"name": "x"}) == "unrecognized entity"
