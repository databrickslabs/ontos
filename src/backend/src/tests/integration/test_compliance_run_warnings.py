"""Running a policy through the API: CamelCase MATCH types and empty runs (#1150 A and B)."""
import uuid

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from src.db_models.compliance import CompliancePolicyDb
from src.db_models.data_products import DataProductDb


def _policy(db: Session, rule: str) -> CompliancePolicyDb:
    policy = CompliancePolicyDb(
        id=str(uuid.uuid4()), name=f'policy-{uuid.uuid4().hex[:8]}', rule=rule,
        category='Governance', severity='low', is_active=True,
    )
    db.add(policy)
    db.commit()
    return policy


def _run(client: TestClient, policy: CompliancePolicyDb) -> dict:
    response = client.post(f'/api/compliance/policies/{policy.id}/runs', json={})
    assert response.status_code == 200, response.text
    return response.json()


def test_a_camel_case_match_type_evaluates_the_entities(client: TestClient, db_session: Session):
    name = f'camel-{uuid.uuid4().hex[:8]}'
    product = DataProductDb(
        id=str(uuid.uuid4()), api_version='v1.0.0', kind='DataProduct',
        status='draft', name=name, version='1.0.0',
    )
    db_session.add(product)
    db_session.commit()
    policy = _policy(
        db_session,
        f"MATCH (p:DataProduct) WHERE p.name = '{name}' ASSERT p.status = 'active' "
        "ON_FAIL FAIL 'Product is not active'",
    )

    run = _run(client, policy)

    assert run['status'] == 'succeeded'
    assert (run['success_count'], run['failure_count']) == (0, 1)
    assert run['warning_code'] is None
    body = client.get(f"/api/compliance/runs/{run['id']}/results").json()
    [result] = body['results']
    assert result['object_id'] == product.id
    assert result['message'] == 'Product is not active'


def test_a_run_that_matches_nothing_has_the_warning(client: TestClient, db_session: Session):
    policy = _policy(db_session, "MATCH (d:Dataset) ASSERT d.name != ''")

    run = _run(client, policy)

    assert run['status'] == 'succeeded'
    assert run['error_message'] is None and run['error_code'] is None
    assert run['warning_code'] == 'no_entities_matched'
    # The runs list of the policy page shows it too
    runs = client.get(f'/api/compliance/policies/{policy.id}/runs').json()
    assert [r['warning_code'] for r in runs] == ['no_entities_matched']
