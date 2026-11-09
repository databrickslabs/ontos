"""DELETE /api/data-products/{id}: the subscriber deletion notice (#998, I-23).

The notice is written only after the delete is committed, so a delete that
fails leaves no notice behind, and a successful one leaves exactly one per
subscriber.
"""
from uuid import uuid4

import pytest
from sqlalchemy.exc import OperationalError

from src.db_models.data_products import DataProductDb, DataProductSubscriptionDb
from src.db_models.notifications import NotificationDb
from src.repositories.data_products_repository import data_product_repo

SUBSCRIBER = 'subscriber@example.com'


@pytest.fixture
def subscribed_product(db_session):
    product_id = str(uuid4())
    db_session.add(DataProductDb(id=product_id, status='active', name='Doomed Product'))
    db_session.add(DataProductSubscriptionDb(product_id=product_id, subscriber_email=SUBSCRIBER))
    db_session.commit()
    return product_id


def _deletion_notices(db_session):
    db_session.expire_all()
    return [
        n for n in db_session.query(NotificationDb).filter(
            NotificationDb.recipient == SUBSCRIBER
        ).all()
        if 'notifications:lifecycle.deletion.title' in (n.data or '')
    ]


def test_failed_delete_leaves_no_notice(client, db_session, subscribed_product, monkeypatch):
    def failing_remove(*args, **kwargs):
        raise OperationalError('DELETE FROM data_products', {}, Exception('db down'))

    monkeypatch.setattr(data_product_repo, 'remove', failing_remove)

    response = client.delete(f'/api/data-products/{subscribed_product}')

    assert response.status_code == 500
    assert _deletion_notices(db_session) == []


def test_successful_delete_leaves_one_notice(client, db_session, subscribed_product):
    response = client.delete(f'/api/data-products/{subscribed_product}')

    assert response.status_code == 204
    (notice,) = _deletion_notices(db_session)
    assert 'Doomed Product' in notice.data
    assert db_session.get(DataProductDb, subscribed_product) is None
