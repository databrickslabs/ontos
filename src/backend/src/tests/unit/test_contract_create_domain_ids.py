"""The domains picked when creating a contract are kept.

The create dialog sends ``domainIds`` / ``primaryDomainId`` (the field names),
but ``DataContractCreate`` only accepted the snake_case aliases, so the domain
choice was dropped silently.
"""
import uuid
from pathlib import Path

import pytest
from sqlalchemy.orm import Session

from src.common.api_errors import CodedValueError
from src.controller.data_contracts_manager import DataContractsManager
from src.db_models.data_domains import DataDomain
from src.models.data_contracts_api import DataContractCreate, DataContractUpdate
from src.repositories.entity_domain_association_repository import entity_domain_repo


def _manager():
    mgr = DataContractsManager(data_dir=Path("/tmp"))
    mgr._queue_delivery = lambda *a, **k: None
    mgr._update_search_index = lambda *a, **k: None
    return mgr


def _domain(db: Session) -> str:
    domain = DataDomain(
        id=str(uuid.uuid4()), name=f"d-{uuid.uuid4().hex[:8]}", created_by="user@example.com",
    )
    db.add(domain)
    db.flush()
    return domain.id


def test_create_model_accepts_field_names_for_domains():
    model = DataContractCreate.model_validate(
        {"name": "Orders", "domainIds": ["d1", "d2"], "primaryDomainId": "d2"}
    )
    assert model.domainIds == ["d1", "d2"]
    assert model.primaryDomainId == "d2"


def test_create_model_still_accepts_snake_case_aliases():
    model = DataContractCreate.model_validate(
        {"name": "Orders", "domain_ids": ["d1"], "primary_domain_id": "d1"}
    )
    assert model.domainIds == ["d1"]
    assert model.primaryDomainId == "d1"


def test_create_assigns_the_picked_domains(db_session: Session):
    first, second = _domain(db_session), _domain(db_session)
    payload = DataContractCreate.model_validate(
        {
            "name": f"Orders {uuid.uuid4().hex[:6]}",
            "version": "1.0.0",
            "domainIds": [first, second],
            "primaryDomainId": second,
        }
    )

    created = _manager().create_contract_with_relations(
        db=db_session, contract_data=payload, current_user="alice@example.com",
    )

    domains = entity_domain_repo.get_domains_for_entity(
        db_session, entity_type="data_contract", entity_id=created.id,
    )
    assert {d.domain_id for d in domains} == {first, second}
    assert [d.domain_id for d in domains if d.is_primary] == [second]


def _create(db: Session, **fields):
    payload = DataContractCreate.model_validate(
        {"name": f"Orders {uuid.uuid4().hex[:6]}", "version": "1.0.0", **fields}
    )
    return _manager().create_contract_with_relations(
        db=db, contract_data=payload, current_user="alice@example.com",
    )


def test_create_reads_every_aliased_field_by_name(db_session: Session):
    """The create body is read by field name as well as by alias: ``dataProduct``,
    ``apiVersion`` and the domains sent by name are stored (the wizard sends them so)."""
    created = _create(db_session, dataProduct="orders-dp", apiVersion="v3.0.2")

    assert (created.data_product, created.api_version) == ("orders-dp", "v3.0.2")


def test_the_flat_description_fields_are_read_by_name_and_by_alias():
    by_name = DataContractCreate.model_validate({
        "name": "Orders", "descriptionUsage": "u", "descriptionPurpose": "p",
        "descriptionLimitations": "l",
    })
    by_alias = DataContractCreate.model_validate({
        "name": "Orders", "description_usage": "u", "description_purpose": "p",
        "description_limitations": "l",
    })

    for model in (by_name, by_alias):
        assert (model.descriptionUsage, model.descriptionPurpose) == ("u", "p")
        assert model.descriptionLimitations == "l"


def test_api_version_by_name_wins_over_the_alias():
    model = DataContractCreate.model_validate({
        "name": "Orders", "apiVersion": "v3.0.2", "api_version": "v3.1.0",
    })
    assert model.apiVersion == "v3.0.2"


def test_the_field_name_wins_when_both_spellings_are_sent():
    model = DataContractCreate.model_validate({
        "name": "Orders", "domainIds": ["d1"], "domain_ids": ["d2"],
        "primaryDomainId": "d1", "primary_domain_id": "d2",
    })
    assert (model.domainIds, model.primaryDomainId) == (["d1"], "d1")


def test_create_still_stores_the_other_fields_sent_by_alias(db_session: Session):
    created = _create(db_session, data_product="orders-dp", api_version="v3.0.2")

    assert (created.data_product, created.api_version) == ("orders-dp", "v3.0.2")


@pytest.mark.parametrize("key", ["domainIds", "domain_ids"])
def test_create_refuses_an_unknown_domain_id(db_session: Session, key):
    """An unknown domain id is refused (the route answers 400), not dropped."""
    with pytest.raises(ValueError, match="not found"):
        _create(db_session, **{key: [str(uuid.uuid4())]})


def _update(db: Session, contract_id: str, **fields):
    _manager().update_contract_with_relations(
        db=db, contract_id=contract_id,
        contract_data=DataContractUpdate.model_validate({"name": "Renamed", **fields}),
    )
    return {
        d.domain_id for d in entity_domain_repo.get_domains_for_entity(
            db, entity_type="data_contract", entity_id=contract_id,
        )
    }


@pytest.mark.parametrize("fields", [{}, {"domainIds": None, "primaryDomainId": None}])
def test_an_update_without_domains_or_with_null_keeps_them(db_session: Session, fields):
    domain = _domain(db_session)
    created = _create(db_session, domainIds=[domain])

    assert _update(db_session, created.id, **fields) == {domain}


def test_an_update_with_empty_domain_ids_clears_them(db_session: Session):
    created = _create(db_session, domainIds=[_domain(db_session)])

    assert _update(db_session, created.id, domainIds=[]) == set()


def test_an_update_with_null_api_version_keeps_it(db_session: Session):
    created = _create(db_session, api_version="v3.0.2")
    _update(db_session, created.id, apiVersion=None)

    db_session.expire_all()
    assert db_session.get(type(created), created.id).api_version == "v3.0.2"


def _primary(db: Session, contract_id: str):
    return [
        d.domain_id for d in entity_domain_repo.get_domains_for_entity(
            db, entity_type="data_contract", entity_id=contract_id,
        ) if d.is_primary
    ]


def test_an_update_with_only_primary_domain_id_moves_the_primary(db_session: Session):
    """primaryDomainId alone keeps the domains and changes the primary (before, it
    cleared every domain)."""
    first, second = _domain(db_session), _domain(db_session)
    created = _create(db_session, domainIds=[first, second], primaryDomainId=first)

    assert _update(db_session, created.id, primaryDomainId=second) == {first, second}
    assert _primary(db_session, created.id) == [second]


def test_an_update_with_only_an_unrelated_primary_domain_id_is_refused(db_session: Session):
    first, other = _domain(db_session), _domain(db_session)
    created = _create(db_session, domainIds=[first])

    with pytest.raises(ValueError, match="not one of the contract's domains"):
        _update(db_session, created.id, primaryDomainId=other)


@pytest.mark.parametrize("ids_key", ["domainIds", "domain_ids"])
def test_an_update_with_domain_ids_and_primary_replaces_them(db_session: Session, ids_key):
    """domainIds with primaryDomainId replaces the domains (the lone-primary path is
    only for primaryDomainId alone): the new primary isn't a stored domain."""
    first, second, third = _domain(db_session), _domain(db_session), _domain(db_session)
    created = _create(db_session, domainIds=[first])

    fields = {ids_key: [second, third], "primaryDomainId": third}
    assert _update(db_session, created.id, **fields) == {second, third}
    assert _primary(db_session, created.id) == [third]


def test_an_update_with_domain_id_and_primary_replaces_them(db_session: Session):
    first, second = _domain(db_session), _domain(db_session)
    created = _create(db_session, domainIds=[first])

    assert _update(db_session, created.id, domainId=second, primaryDomainId=second) == {second}
    assert _primary(db_session, created.id) == [second]


def _stored(db: Session, contract_id: str) -> set:
    return {
        d.domain_id for d in entity_domain_repo.get_domains_for_entity(
            db, entity_type="data_contract", entity_id=contract_id,
        )
    }


@pytest.mark.parametrize("fields", [
    {"primaryDomainId": ""},
    {"domainId": ""},
    {"domainIds": [""]},
    {"domainIds": [" "]},
    {"domainIds": ["x"], "primaryDomainId": ""},
    {"domainIds": [], "primaryDomainId": ""},
])
def test_an_update_with_a_blank_domain_identifier_is_refused(
    db_session: Session, fields,
):
    """A blank id is a value, not absence: it is refused with a code, never read as
    "clear the domains" (before, ``primaryDomainId: ""`` cleared them)."""
    created = _create(db_session, domainIds=[_domain(db_session)])

    with pytest.raises(CodedValueError) as refused:
        _update(db_session, created.id, **fields)

    assert refused.value.code == "invalid_domain_identifier"


def test_a_create_with_a_blank_domain_identifier_is_refused(db_session: Session):
    with pytest.raises(CodedValueError) as refused:
        _create(db_session, domainIds=[_domain(db_session)], primaryDomainId="")

    assert refused.value.params == {"field": "primaryDomainId"}


def test_an_update_with_empty_domain_ids_wins_over_a_legacy_domain_id(db_session: Session):
    """domainIds [] is the modern clear-all: the legacy domainId doesn't keep a domain."""
    domain = _domain(db_session)
    created = _create(db_session, domainIds=[domain])

    assert _update(db_session, created.id, domainIds=[], domainId=domain) == set()


def test_a_create_with_empty_domain_ids_wins_over_a_legacy_domain_id(db_session: Session):
    created = _create(db_session, domainIds=[], domainId=_domain(db_session))

    assert _stored(db_session, created.id) == set()


def test_an_update_with_domain_ids_wins_over_a_legacy_domain_id(db_session: Session):
    first, second = _domain(db_session), _domain(db_session)
    created = _create(db_session, domainIds=[first])

    assert _update(db_session, created.id, domainIds=[second], domainId=first) == {second}


def test_an_update_with_primary_and_legacy_domain_id_takes_the_primary(db_session: Session):
    first, second = _domain(db_session), _domain(db_session)
    created = _create(db_session, domainIds=[first])

    assert _update(db_session, created.id, primaryDomainId=second, domainId=first) == {second}


def test_an_update_with_a_legacy_domain_id_alone_still_replaces_the_domain(db_session: Session):
    first, second = _domain(db_session), _domain(db_session)
    created = _create(db_session, domainIds=[first])

    assert _update(db_session, created.id, domainId=second) == {second}


@pytest.mark.parametrize("fields", [
    {"domain": ""}, {"domain": "  "}, {"domainIds": ["x"], "domain": ""},
])
def test_a_blank_domain_name_does_not_clear_the_domains_of_an_update(db_session: Session, fields):
    """The legacy ``domain`` (name) counts as sent when present: blank is refused instead of
    resolving to "no domain" and clearing them. The assistant's update tool sends a dict
    (the REST update model has no ``domain`` field)."""
    created = _create(db_session, domainIds=[_domain(db_session)])

    with pytest.raises(CodedValueError) as refused:
        _manager().update_contract_with_relations(
            db=db_session, contract_id=created.id, contract_data=dict(fields),
        )

    assert refused.value.code == "invalid_domain_identifier"
    assert refused.value.params in ({"field": "domain"}, {"field": "domainIds"})


def test_a_create_with_a_blank_domain_name_is_refused(db_session: Session):
    with pytest.raises(CodedValueError) as refused:
        _create(db_session, domain="")

    assert refused.value.params == {"field": "domain"}


@pytest.mark.parametrize("domain_ids", [[], ["other"]])
def test_a_primary_outside_domain_ids_is_refused(db_session: Session, domain_ids):
    """The replace path refuses a primary that isn't one of the domainIds (before, it fell
    back to the first one, or to none), as the lone-primary path does."""
    first, other = _domain(db_session), _domain(db_session)
    created = _create(db_session, domainIds=[first])
    ids = [other if d == "other" else d for d in domain_ids]

    with pytest.raises(CodedValueError) as refused:
        _update(db_session, created.id, domainIds=ids, primaryDomainId=first)

    assert refused.value.code == "primary_domain_not_in_domains"
    assert refused.value.params == {"primaryDomainId": first}


def test_a_create_with_a_primary_outside_domain_ids_is_refused(db_session: Session):
    first, other = _domain(db_session), _domain(db_session)

    with pytest.raises(CodedValueError) as refused:
        _create(db_session, domainIds=[first], primaryDomainId=other)

    assert refused.value.code == "primary_domain_not_in_domains"


def test_the_lone_primary_refusal_is_coded(db_session: Session):
    first, other = _domain(db_session), _domain(db_session)
    created = _create(db_session, domainIds=[first])

    with pytest.raises(CodedValueError) as refused:
        _update(db_session, created.id, primaryDomainId=other)

    assert refused.value.code == "primary_domain_not_in_domains"
