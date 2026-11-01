"""POST /data-contracts/{id}/handle-deploy records the decision and deploys nothing
(#1151 item 1)."""
from fastapi.testclient import TestClient


def _contract_id(client: TestClient) -> str:
    response = client.post('/api/data-contracts', json={
        'name': 'Deploy Route Contract', 'version': '1.0.0', 'status': 'draft',
        'owner': 'test@example.com',
    })
    assert response.status_code == 200, response.text
    return response.json()['id']


def test_execute_deployment_is_accepted_and_answered_with_a_warning(client: TestClient):
    contract_id = _contract_id(client)

    response = client.post(
        f'/api/data-contracts/{contract_id}/handle-deploy',
        json={'decision': 'approve', 'execute_deployment': True},
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body['message'] == "Deploy decision 'approve' recorded successfully"
    assert [w['code'] for w in body['warnings']] == ['deployment_not_available']
    assert 'job_id' not in body


def test_an_approval_without_the_flag_has_no_warning(client: TestClient):
    contract_id = _contract_id(client)

    response = client.post(
        f'/api/data-contracts/{contract_id}/handle-deploy', json={'decision': 'approve'},
    )

    assert response.status_code == 200, response.text
    assert 'warnings' not in response.json()


def test_the_openapi_description_says_the_flag_is_ignored(client: TestClient):
    schema = client.get('/openapi.json').json()
    field = schema['components']['schemas']['HandleDeployPayload']['properties'][
        'execute_deployment'
    ]
    assert field['description'].startswith('Ignored.')
