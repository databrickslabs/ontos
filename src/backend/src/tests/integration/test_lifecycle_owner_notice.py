"""The owner lifecycle notices: default workflows "Owner Deprecation Notice" and
"Owner Retirement Notice" (#998).

Shipped inactive. Once an admin enables them, deprecating or retiring a data
product or data contract notifies its owners, with ``data.i18n`` keys and the
reason, sunset date and replacement as params; while they are off, the owners
get nothing.
"""
import json
from datetime import date, timedelta
from uuid import uuid4

import pytest

from src.controller.workflows_manager import WorkflowsManager
from src.db_models.data_contracts import DataContractDb
from src.db_models.data_products import DataProductDb
from src.db_models.notifications import NotificationDb
from src.db_models.teams import TeamDb, TeamMemberDb
from src.repositories.process_workflows_repository import process_workflow_repo

OWNER = 'owner@example.com'
NOTICES = {
    'deprecated': 'Owner Deprecation Notice',
    'retired': 'Owner Retirement Notice',
}
TITLE_KEY = 'notifications:workflowDefaults.templates.entity_{}.title'
SUNSET = (date.today() + timedelta(days=30)).isoformat()


@pytest.fixture
def defaults(db_session):
    """The default workflows, created as at startup (event-driven ones inactive)."""
    WorkflowsManager(db=db_session).load_from_yaml(requests_only_active=True)
    return {status: process_workflow_repo.get_by_name(db_session, name)
            for status, name in NOTICES.items()}


@pytest.fixture
def enabled(client, defaults):
    for workflow in defaults.values():
        response = client.post(
            f'/api/workflows/{workflow.id}/toggle-active', params={'is_active': 'true'},
        )
        assert response.status_code == 200, response.text
    return defaults


def _owner_team(db_session):
    team = TeamDb(
        name=f'owners-{uuid4().hex[:8]}', created_by='admin@example.com',
        updated_by='admin@example.com',
    )
    db_session.add(team)
    db_session.flush()
    db_session.add(TeamMemberDb(
        team_id=team.id, member_type='user', member_identifier=OWNER,
        added_by='admin@example.com',
    ))
    return team.id


@pytest.fixture
def products(db_session):
    team_id = _owner_team(db_session)
    old, new = str(uuid4()), str(uuid4())
    # A new version keeps the name (clone_product_for_new_version)
    db_session.add(DataProductDb(
        id=old, status='active', name='Orders', version='1.0.0', owner_team_id=team_id,
    ))
    db_session.add(DataProductDb(id=new, status='active', name='Orders', version='2.0.0'))
    db_session.commit()
    return old, new


@pytest.fixture
def contracts(db_session):
    team_id = _owner_team(db_session)
    old, new = str(uuid4()), str(uuid4())
    for contract_id, version, owner_team in ((old, '1.0.0', team_id), (new, '2.0.0', None)):
        db_session.add(DataContractDb(
            id=contract_id, name='orders', version=version, status='active',
            version_family_id=contract_id, owner_team_id=owner_team,
        ))
    db_session.commit()
    return old, new


def _notices(db_session, status):
    db_session.expire_all()
    found = []
    for notice in db_session.query(NotificationDb).filter(NotificationDb.recipient == OWNER):
        data = json.loads(notice.data) if isinstance(notice.data, str) else notice.data
        if (data or {}).get('i18n', {}).get('title') == TITLE_KEY.format(status):
            found.append((notice, data['i18n']))
    return found


def _lines(i18n):
    return {line['key'].rsplit('.', 1)[-1]: line.get('params') for line in i18n['descriptionLines']}


def _change(client, path, entity_id, new_status, **deprecation):
    response = client.post(
        f'/api/{path}/{entity_id}/change-status', json={'new_status': new_status, **deprecation},
    )
    assert response.status_code == 200, response.text


DEPRECATION = {'deprecation_reason': 'Superseded by v2', 'sunset_date': SUNSET}


@pytest.mark.parametrize('path, entities, entity_type, name', [
    ('data-products', 'products', 'data_product', 'Orders'),
    ('data-contracts', 'contracts', 'data_contract', 'orders'),
])
def test_enabled_notices_tell_the_owners_with_reason_sunset_and_replacement(
    client, db_session, enabled, request, path, entities, entity_type, name,
):
    old, new = request.getfixturevalue(entities)

    _change(client, path, old, 'deprecated', replacement_id=new, **DEPRECATION)
    _change(client, path, old, 'retired')

    for status in ('deprecated', 'retired'):
        (notice, i18n), = _notices(db_session, status)
        lines = _lines(i18n)
        # Same name, so the versions tell the two apart
        assert lines[f'{status}Version'] == {
            'entity_type': entity_type, 'entity_name': name, 'version': '1.0.0',
        }
        assert lines['reason'] == {'reason': 'Superseded by v2'}
        assert lines['sunsetDate'] == {'sunsetDate': SUNSET}
        assert lines['replacementVersion'] == {
            'replacementName': name, 'replacementVersion': '2.0.0', 'replacementId': new,
        }
        assert notice.type == 'warning'
        assert notice.link == f'/{path}/{new}'
        # The English text, for clients that don't translate
        assert notice.description.splitlines() == [
            f"{entity_type} '{name}' (version 1.0.0) has been {status}.",
            'Reason: Superseded by v2', f'Sunset date: {SUNSET}',
            f'Replacement: {name} (version 2.0.0)',
        ]


def test_unset_fields_are_left_out(client, db_session, enabled, products):
    old, _ = products

    _change(client, 'data-products', old, 'deprecated', deprecation_reason='No longer maintained')

    (notice, i18n), = _notices(db_session, 'deprecated')
    assert list(_lines(i18n)) == ['deprecatedVersion', 'reason']
    assert notice.description == (
        "data_product 'Orders' (version 1.0.0) has been deprecated.\n"
        "Reason: No longer maintained"
    )
    # No replacement: the product's own page
    assert notice.link == f'/data-products/{old}'


def test_notices_are_off_by_default(client, db_session, defaults, products, contracts):
    assert all(not workflow.is_active for workflow in defaults.values())

    for path, (old, new) in (('data-products', products), ('data-contracts', contracts)):
        _change(client, path, old, 'deprecated', replacement_id=new, **DEPRECATION)
        _change(client, path, old, 'retired')

    assert _notices(db_session, 'deprecated') == []
    assert _notices(db_session, 'retired') == []
