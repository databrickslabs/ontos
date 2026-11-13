"""``POST /api/data-products/{id}/change-status`` audits the move by its target.

``DEPRECATE`` (with the deprecation reason, sunset date and replacement) for a
deprecation, ``RETIRE`` for a retirement, ``CHANGE_STATUS`` otherwise: the entries the
``update_data_product`` tool writes too (``test_tool_product_status_audit``).
"""
import json
import uuid
from datetime import date, timedelta

from src.db_models.audit_log import AuditLogDb
from src.db_models.data_products import DataProductDb


def _product(db, status):
    product_id = str(uuid.uuid4())
    db.add(DataProductDb(
        id=product_id, name=f'Product {product_id[:8]}', version='1.0.0', status=status,
        api_version='v1.0.0', kind='DataProduct',
    ))
    db.commit()
    return product_id


def _entries(db, product_id):
    db.expire_all()
    rows = db.query(AuditLogDb).filter(AuditLogDb.feature == 'data-products').all()
    out = []
    for row in rows:
        details = json.loads(row.details) if isinstance(row.details, str) else row.details
        if (details or {}).get('product_id') == product_id:
            out.append((row.action, details))
    return out


def _change(client, product_id, **body):
    return client.post(f'/api/data-products/{product_id}/change-status', json=body)


def test_a_deprecation_is_audited_as_deprecate_with_its_details(client, db_session):
    replacement = _product(db_session, 'active')
    product_id = _product(db_session, 'active')
    sunset = (date.today() + timedelta(days=30)).isoformat()

    res = _change(client, product_id, new_status='deprecated', deprecation_reason='Superseded',
                  sunset_date=sunset, replacement_id=replacement)

    assert res.status_code == 200, res.text
    [(action, details)] = _entries(db_session, product_id)
    assert action == 'DEPRECATE'
    assert details['new_status'] == 'deprecated'
    assert details['deprecation_reason'] == 'Superseded'
    assert details['sunset_date'] == sunset
    assert details['replacement_id'] == replacement


def test_a_retirement_is_audited_as_retire(client, db_session):
    product_id = _product(db_session, 'deprecated')

    res = _change(client, product_id, new_status='retired')

    assert res.status_code == 200, res.text
    [(action, details)] = _entries(db_session, product_id)
    assert action == 'RETIRE'
    assert details['new_status'] == 'retired'
    assert 'deprecation_reason' not in details


def test_another_transition_is_audited_as_change_status(client, db_session):
    product_id = _product(db_session, 'draft')

    res = _change(client, product_id, new_status='proposed')

    assert res.status_code == 200, res.text
    [(action, details)] = _entries(db_session, product_id)
    assert action == 'CHANGE_STATUS'
    assert details['new_status'] == 'proposed'
