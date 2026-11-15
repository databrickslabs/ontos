"""The domains picked when creating a contract are kept.

The create dialog sends ``domainIds`` / ``primaryDomainId`` (the field names),
but ``DataContractCreate`` only accepted the snake_case aliases, so the domain
choice was dropped silently.
"""
import uuid
from pathlib import Path

import pytest
from sqlalchemy.orm import Session

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


def test_create_stores_the_other_fields_sent_by_name(db_session: Session):
    """populate_by_name makes every aliased field of DataContractBase readable by
    name, not only the domains: the ones the create path stores are kept."""
    created = _create(db_session, dataProduct="orders-dp", apiVersion="v3.0.2")

    assert (created.data_product, created.api_version) == ("orders-dp", "v3.0.2")


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
    created = _create(db_session, apiVersion="v3.0.2")
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
