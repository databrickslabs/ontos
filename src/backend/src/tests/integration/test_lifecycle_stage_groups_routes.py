"""Routes of Lifecycle Stage Groups (#1213): groups, an entity's lifecycle, change-group.

The test user is an admin (``test_admins``). Errors are coded: 400 an invalid
group, 404 an unknown one, 409 integrity conflicts, a pending request and an
ambiguous named action.
"""
import uuid

import pytest

from src.common.lifecycle_defaults import DEFAULT_GROUP_IDS
from src.controller.change_log_manager import change_log_manager
from src.db_models.data_products import DataProductDb


def _stage(key, category, order, initial=False):
    return {'key': key, 'label': key.title(), 'category': category, 'order': order,
            'is_initial': initial}


def _group(name='Authority resolution', entity_type='data_product', extra_review=False):
    stages = [
        _stage('draft', 'draft', 0, True), _stage('active', 'active', 1),
        _stage('needs_review', 'review', 2), _stage('retired', 'retired', 3),
    ]
    transitions = [
        {'from_key': 'draft', 'to_key': 'active'},
        {'from_key': 'active', 'to_key': 'needs_review'},
        {'from_key': 'needs_review', 'to_key': 'active'},
        {'from_key': 'active', 'to_key': 'retired'},
    ]
    if extra_review:
        stages.append(_stage('legal_review', 'review', 4))
        transitions += [{'from_key': 'active', 'to_key': 'legal_review'},
                        {'from_key': 'legal_review', 'to_key': 'active'}]
    return {'name': name, 'entity_type': entity_type, 'stages': stages,
            'transitions': transitions}


def _product(db, status='draft', group_id=None):
    pid = str(uuid.uuid4())
    db.add(DataProductDb(id=pid, name=f'P {pid[:8]}', version='1.0.0', status=status,
                         api_version='v1.0.0', kind='DataProduct',
                         lifecycle_stage_group_id=group_id))
    db.commit()
    return pid


def _create(client, body):
    res = client.post('/api/lifecycle-stage-groups', json=body)
    assert res.status_code == 201, res.text
    return res.json()


class TestGroups:
    def test_the_list_has_the_default_group_of_an_entity_type(self, client):
        res = client.get('/api/lifecycle-stage-groups', params={'entity_type': 'data_contract'})
        assert res.status_code == 200, res.text
        [group] = res.json()
        assert group['is_default_for_type'] is True
        assert [s['key'] for s in group['stages']][:2] == ['draft', 'proposed']

    def test_create_stores_the_seeded_defaults_too(self, client):
        created = _create(client, _group())
        listed = client.get('/api/lifecycle-stage-groups',
                            params={'entity_type': 'data_product'}).json()
        assert [g['id'] for g in listed] == [DEFAULT_GROUP_IDS['data_product'], created['id']]

    def test_an_invalid_group_is_a_coded_400(self, client):
        body = _group()
        body['transitions'] = [t for t in body['transitions'] if t['to_key'] != 'retired']
        res = client.post('/api/lifecycle-stage-groups', json=body)
        assert res.status_code == 400
        assert res.json()['detail']['code'] == 'lifecycle_group_unreachable_stages'
        assert res.json()['detail']['params'] == {'stages': ['retired']}

    # One refused request per test: the request session's rollback ends the test's data

    def test_deleting_the_default_is_a_409(self, client):
        _create(client, _group())
        res = client.delete(f"/api/lifecycle-stage-groups/{DEFAULT_GROUP_IDS['data_product']}")
        assert res.status_code == 409
        assert res.json()['detail']['code'] == 'lifecycle_group_is_default'

    def test_deleting_an_unknown_group_is_a_404(self, client):
        res = client.delete('/api/lifecycle-stage-groups/nope')
        assert res.status_code == 404
        assert res.json()['detail']['code'] == 'lifecycle_group_not_found'

    def test_removing_a_stage_in_use_is_a_409(self, client, db_session):
        created = _create(client, _group())
        _product(db_session, 'needs_review', created['id'])
        body = _group()
        body['stages'] = [s for s in body['stages'] if s['key'] != 'needs_review']
        body['transitions'] = [t for t in body['transitions'] if 'needs_review' not in t.values()]
        res = client.put(f"/api/lifecycle-stage-groups/{created['id']}", json=body)
        assert res.status_code == 409
        assert res.json()['detail']['code'] == 'lifecycle_stage_in_use'


class TestEntityLifecycle:
    def test_an_entity_shows_its_group_stage_and_next_stages(self, client, db_session):
        pid = _product(db_session, 'approved')
        res = client.get(f'/api/lifecycle/data_product/{pid}')
        assert res.status_code == 200, res.text
        body = res.json()
        assert body['stage']['category'] == 'review'
        assert [s['key'] for s in body['allowed_transitions']] == ['draft', 'active', 'deprecated']

    def test_change_group_resets_to_the_first_stage(self, client, db_session):
        created = _create(client, _group())
        pid = _product(db_session, 'approved')
        res = client.post(f'/api/lifecycle/data_product/{pid}/change-group',
                          json={'group_id': created['id']})
        assert res.status_code == 200, res.text
        assert res.json()['status'] == 'draft'
        assert res.json()['group']['name'] == 'Authority resolution'
        db_session.expire_all()
        assert db_session.get(DataProductDb, pid).status == 'draft'

    def test_change_group_is_a_409_while_a_request_is_pending(self, client, db_session):
        created = _create(client, _group())
        pid = _product(db_session, 'draft')
        change_log_manager.log_change_with_details(
            db_session, entity_type='data_product', entity_id=pid,
            action='status_change_requested', username='carol',
            details={'request_id': 'r1', 'from_status': 'draft', 'target_status': 'proposed'},
        )
        res = client.post(f'/api/lifecycle/data_product/{pid}/change-group',
                          json={'group_id': created['id']})
        assert res.status_code == 409
        assert res.json()['detail']['code'] == 'lifecycle_change_pending_request'

    def test_a_group_of_another_entity_type_is_a_400(self, client, db_session):
        asset_group = _create(client, _group(entity_type='asset'))
        pid = _product(db_session, 'draft')
        res = client.post(f'/api/lifecycle/data_product/{pid}/change-group',
                          json={'group_id': asset_group['id']})
        assert res.status_code == 400
        assert res.json()['detail']['code'] == 'lifecycle_group_wrong_entity_type'

    def test_an_unknown_group_is_a_404(self, client, db_session):
        pid = _product(db_session, 'draft')
        res = client.post(f'/api/lifecycle/data_product/{pid}/change-group',
                          json={'group_id': 'nope'})
        assert res.status_code == 404
        assert res.json()['detail']['code'] == 'lifecycle_group_not_found'


    def test_changing_to_the_current_group_is_a_409(self, client, db_session):
        pid = _product(db_session, 'retired')
        res = client.post(f'/api/lifecycle/data_product/{pid}/change-group',
                          json={'group_id': DEFAULT_GROUP_IDS['data_product']})
        assert res.status_code == 409
        assert res.json()['detail']['code'] == 'lifecycle_change_same_group'

    def test_a_group_whose_first_stage_is_active_cant_be_saved(self, client):
        body = _group()
        body['stages'][0]['is_initial'] = False
        body['stages'][1]['is_initial'] = True
        body['transitions'].append({'from_key': 'active', 'to_key': 'draft'})
        res = client.post('/api/lifecycle-stage-groups', json=body)
        assert res.status_code == 400
        assert res.json()['detail']['code'] == 'lifecycle_group_initial_not_draft'


class TestNamedActions:
    def test_an_ambiguous_submit_review_is_a_409(self, client, db_session):
        created = _create(client, _group(extra_review=True))
        pid = _product(db_session, 'active', created['id'])
        res = client.post(f'/api/data-products/{pid}/submit-review')
        assert res.status_code == 409
        detail = res.json()['detail']
        assert detail['code'] == 'lifecycle_action_ambiguous'
        assert detail['params']['candidates'] == ['needs_review', 'legal_review']

    def test_a_submit_review_with_no_review_stage_is_a_409(self, client, db_session):
        created = _create(client, _group())
        pid = _product(db_session, 'draft', created['id'])
        res = client.post(f'/api/data-products/{pid}/submit-review')
        assert res.status_code == 409
        assert res.json()['detail']['code'] == 'invalid_status_transition'

    def test_publish_from_a_stage_with_no_active_move_is_a_409(self, client, db_session):
        created = _create(client, _group())
        pid = _product(db_session, 'retired', created['id'])
        res = client.post(f'/api/data-products/{pid}/publish')
        assert res.status_code == 409
        assert res.json()['detail']['code'] == 'invalid_status_transition'

    def test_the_change_status_route_follows_a_custom_group(self, client, db_session):
        created = _create(client, _group())
        pid = _product(db_session, 'active', created['id'])
        res = client.post(f'/api/data-products/{pid}/change-status',
                          json={'new_status': 'needs_review'})
        assert res.status_code == 200, res.text
        assert res.json()['product']['statusCategory'] == 'review'


class TestNotAnAdmin:
    """Read/Write on the entity's feature but not Admin: owners only."""

    @pytest.fixture
    def not_admin(self, monkeypatch):
        from src.common.features import FeatureAccessLevel
        from src.routes import lifecycle_stage_groups_routes as routes

        async def has_level(feature_id, level, user, request):
            return level != FeatureAccessLevel.ADMIN

        monkeypatch.setattr(routes, 'has_feature_permission', has_level)

    def _owned(self, db, status, owner):
        pid = _product(db, status)
        row = db.get(DataProductDb, pid)
        row.draft_owner_id = owner
        db.commit()
        return pid

    def test_the_owner_changes_the_group(self, client, db_session, mock_test_user, not_admin):
        created = _create(client, _group())
        pid = self._owned(db_session, 'draft', mock_test_user.email)
        res = client.post(f'/api/lifecycle/data_product/{pid}/change-group',
                          json={'group_id': created['id']})
        assert res.status_code == 200, res.text

    def test_someone_else_cant_change_the_group(self, client, db_session, not_admin):
        created = _create(client, _group())
        pid = self._owned(db_session, 'approved', 'someone@example.com')
        res = client.post(f'/api/lifecycle/data_product/{pid}/change-group',
                          json={'group_id': created['id']})
        # Refused before any write (the refused request's rollback ends the test data)
        assert res.status_code == 403

    def test_someone_elses_unpublished_product_reads_as_missing(
        self, client, db_session, not_admin,
    ):
        pid = self._owned(db_session, 'draft', 'someone@example.com')
        assert client.get(f'/api/lifecycle/data_product/{pid}').status_code == 404

    def test_a_published_product_reads_for_everyone(self, client, db_session, not_admin):
        pid = self._owned(db_session, 'active', 'someone@example.com')
        res = client.get(f'/api/lifecycle/data_product/{pid}')
        assert res.status_code == 200
        assert res.json()['stage']['category'] == 'active'


def test_a_stored_group_reads_with_its_stages_and_transitions(client):
    created = _create(client, _group())
    res = client.get(f"/api/lifecycle-stage-groups/{created['id']}")
    assert res.status_code == 200
    body = res.json()
    assert [s['key'] for s in body['stages']] == ['draft', 'active', 'needs_review', 'retired']
    assert {'from_key': 'needs_review', 'to_key': 'active'} in body['transitions']
