"""A contract's apiVersion is an ODCS version.

``DataContractCreate`` now reads ``apiVersion`` by name, so a client value is
stored instead of the default. A version without its "v" ('3.0.2', as the
inline create dialog sent) is normalized; one outside the ODCS enum is refused
with the code ``odcs_api_version_unsupported`` (HTTP 422 on the routes).
"""
import pytest
from pydantic import ValidationError

from src.models.data_contracts_api import DataContractCreate, DataContractUpdate


@pytest.mark.parametrize("model", [DataContractCreate, DataContractUpdate])
@pytest.mark.parametrize("sent, stored", [
    ("v3.1.0", "v3.1.0"), ("3.0.2", "v3.0.2"), (" V3.0.1 ", "v3.0.1"), ("v2.2.2", "v2.2.2"),
])
def test_api_version_is_normalized(model, sent, stored):
    assert model.model_validate({"name": "Orders", "apiVersion": sent}).apiVersion == stored


@pytest.mark.parametrize("model", [DataContractCreate, DataContractUpdate])
@pytest.mark.parametrize("sent", ["9.9.9", "latest", ""])
def test_api_version_outside_odcs_is_refused(model, sent):
    with pytest.raises(ValidationError) as err:
        model.model_validate({"name": "Orders", "apiVersion": sent})
    [error] = err.value.errors()
    assert error["type"] == "odcs_api_version_unsupported"
    assert error["ctx"] == {"api_version": sent}


def test_api_version_defaults_and_keeps_alias():
    assert DataContractCreate.model_validate({"name": "Orders"}).apiVersion == "v3.1.0"
    assert DataContractCreate.model_validate(
        {"name": "Orders", "api_version": "3.0.2"}).apiVersion == "v3.0.2"
    assert DataContractUpdate.model_validate({"name": "Orders"}).apiVersion is None
