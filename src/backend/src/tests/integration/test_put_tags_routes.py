"""PUT routes and tags (#1435): ``tags: []`` clears, an omitted ``tags`` keeps,
``tags: null`` keeps (it must not be read as "remove all"), for contracts and products."""
import uuid

import pytest

from src.db_models.tags import EntityTagAssociationDb, TagDb
from src.repositories.tags_repository import entity_tag_repo, tag_namespace_repo


@pytest.fixture
def tag(db_session):
    namespace = tag_namespace_repo.get_or_create_default_namespace(
        db_session, user_email='a@example.com',
    )
    tag = TagDb(name=f'pii_{uuid.uuid4().hex[:8]}', namespace_id=namespace.id, status='active')
    db_session.add(tag)
    db_session.commit()
    return tag


def _tag_entity(db_session, tag, entity_id, entity_type):
    entity_tag_repo.add_tag_to_entity(
        db_session, tag_id=tag.id, entity_id=entity_id, entity_type=entity_type,
        assigned_value=None, assigned_by='someone@example.com',
    )
    db_session.commit()


def _count(db_session, entity_id, entity_type):
    db_session.expire_all()
    return db_session.query(EntityTagAssociationDb).filter_by(
        entity_id=entity_id, entity_type=entity_type,
    ).count()


@pytest.fixture
def contract_id(client, db_session, tag):
    resp = client.post('/api/data-contracts', json={
        'name': 'Tagged', 'version': '1.0.0', 'status': 'draft', 'owner': 'test@example.com',
    })
    assert resp.status_code == 200, resp.text
    cid = resp.json()['id']
    _tag_entity(db_session, tag, cid, 'data_contract')
    return cid


@pytest.fixture
def product(client, db_session, tag):
    pid = str(uuid.uuid4())
    body = {
        'id': pid, 'name': 'Tagged', 'version': '1.0.0', 'productType': 'sourceAligned',
        'status': 'draft', 'owner': 'test@example.com',
        'outputPorts': [{'name': 'p', 'version': '1.0.0', 'type': 'table'}],
    }
    assert client.post('/api/data-products', json=body).status_code == 201
    _tag_entity(db_session, tag, pid, 'data_product')
    return pid, body


@pytest.mark.parametrize('payload, expected', [
    ({'tags': []}, 0),
    ({}, 1),
    ({'tags': None}, 1),
])
def test_contract_put_tags(client, db_session, contract_id, payload, expected):
    resp = client.put(f'/api/data-contracts/{contract_id}', json={'name': 'Renamed', **payload})
    assert resp.status_code == 200, resp.text
    assert _count(db_session, contract_id, 'data_contract') == expected


@pytest.mark.parametrize('payload, expected', [
    ({'tags': []}, 0),
    ({}, 1),
    ({'tags': None}, 1),
])
def test_product_put_tags(client, db_session, product, payload, expected):
    pid, body = product
    resp = client.put(f'/api/data-products/{pid}', json={**body, 'name': 'Renamed', **payload})
    assert resp.status_code == 200, resp.text
    assert _count(db_session, pid, 'data_product') == expected


def test_contract_put_with_a_mixed_tag_list_is_refused_and_keeps_the_tags(
    client, db_session, contract_id,
):
    resp = client.put(f'/api/data-contracts/{contract_id}', json={
        'name': 'Renamed', 'tags': [{'tag_fqn': 'ns/new'}, 123],
    })
    assert resp.status_code == 422, resp.text
    assert _count(db_session, contract_id, 'data_contract') == 1


def test_product_put_with_a_mixed_tag_list_is_refused(client, db_session, product):
    pid, body = product
    resp = client.put(f'/api/data-products/{pid}', json={
        **body, 'name': 'Renamed', 'tags': [{'tag_fqn': 'ns/new'}, 123],
    })
    assert resp.status_code == 422, resp.text
    assert _count(db_session, pid, 'data_product') == 1
