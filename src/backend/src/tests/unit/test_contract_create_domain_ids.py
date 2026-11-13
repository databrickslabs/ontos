"""The domains picked when creating a contract are kept.

The create dialog sends ``domainIds`` / ``primaryDomainId`` (the field names),
but ``DataContractCreate`` only accepted the snake_case aliases, so the domain
choice was dropped silently.
"""
import uuid
from pathlib import Path

from sqlalchemy.orm import Session

from src.controller.data_contracts_manager import DataContractsManager
from src.db_models.data_domains import DataDomain
from src.models.data_contracts_api import DataContractCreate
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
