"""A field sent under both its camelCase and snake_case spellings reads camelCase.

Pydantic alone reads the alias first, so the winner depended on which spelling a
model declares as the alias; the contract create and update models now share one rule.
"""
from typing import Optional

import pytest
from pydantic import BaseModel, Field

from src.common.payload_spellings import CamelCaseSpellingWins, camel_case_spelling_wins
from src.models.data_contracts_api import DataContractCreate, DataContractUpdate

BOTH = {
    "domainIds": ["a"], "domain_ids": ["b"],
    "primaryDomainId": "a", "primary_domain_id": "b",
    "dataProduct": "camel", "data_product": "snake",
}


@pytest.mark.parametrize("model, base", [
    (DataContractCreate, {"name": "Orders"}),
    (DataContractUpdate, {}),
])
def test_create_and_update_read_the_camel_case_spelling(model, base):
    parsed = model.model_validate({**base, **BOTH})

    assert parsed.domainIds == ["a"]
    assert parsed.primaryDomainId == "a"
    assert parsed.dataProduct == "camel"


@pytest.mark.parametrize("model, base", [
    (DataContractCreate, {"name": "Orders"}),
    (DataContractUpdate, {}),
])
def test_one_spelling_alone_is_read_as_before(model, base):
    assert model.model_validate({**base, "domain_ids": ["b"]}).domainIds == ["b"]
    assert model.model_validate({**base, "domainIds": ["a"]}).domainIds == ["a"]


def test_a_camel_case_alias_wins_over_a_snake_case_name():
    parsed = DataContractUpdate.model_validate(
        {"parentContractId": "camel", "parent_contract_id": "snake"}
    )

    assert parsed.parent_contract_id == "camel"


class _Model(CamelCaseSpellingWins):
    first_name: Optional[str] = Field(None, alias="given_name")

    class Config:
        populate_by_name = True


def test_two_snake_case_spellings_are_left_to_pydantic():
    data = {"first_name": "name", "given_name": "alias"}

    assert camel_case_spelling_wins(_Model, data) is data
    assert _Model.model_validate(data).first_name == "alias"


class _AliasOnly(BaseModel):
    fieldName: Optional[str] = Field(None, alias="field_name")


def test_a_model_that_reads_only_the_alias_is_left_unchanged():
    data = {"fieldName": "name", "field_name": "alias"}

    assert camel_case_spelling_wins(_AliasOnly, data) is data
