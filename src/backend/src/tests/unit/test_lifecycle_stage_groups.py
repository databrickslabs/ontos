"""Lifecycle Stage Groups: the lifecycle service and the managers that use it (#1213).

Every product, contract and asset is in a group (NULL = its type's default);
``status`` is a stage key. The seeded default groups reproduce the transition
maps the app had before, and a custom group may loop
(``Active -> Needs Review -> Active``). Named actions resolve by Stage
Category, version visibility and the Marketplace branch on it, and the standards
export carries the stage and group.
"""
import os
os.environ['TESTING'] = 'true'
os.environ['SKIP_STARTUP_TASKS'] = 'true'

import json
import uuid
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from sqlalchemy.orm import Session

from src.common.api_errors import InvalidStatusTransitionError
from src.common.lifecycle_defaults import DEFAULT_GROUP_IDS, default_transitions
from src.common.lifecycle_status import InvalidStatusError
from src.common.version_visibility import compute_rank, is_admin_only_status, is_visible_consumer
from src.controller.data_products_manager import DataProductsManager
from src.controller.lifecycle_service import (
    LifecycleActionUnresolvedError, LifecycleGroupConflictError, LifecycleGroupInvalidError,
    lifecycle_service,
)
from src.db_models.assets import AssetDb
from src.db_models.change_log import ChangeLogDb
from src.db_models.data_contracts import DataContractDb
from src.db_models.data_products import DataProductDb
from src.db_models.process_workflows import ProcessWorkflowDb
from src.repositories.lifecycle_stage_groups_repository import lifecycle_stage_groups_repo


@pytest.fixture(autouse=True)
def fresh_cache():
    lifecycle_service.invalidate()
    yield
    lifecycle_service.invalidate()


@pytest.fixture
def product_manager(db_session: Session) -> DataProductsManager:
    mgr = DataProductsManager(
        db=db_session, ws_client=MagicMock(),
        notifications_manager=MagicMock(), tags_manager=MagicMock(),
    )
    mgr._update_search_index = lambda *a, **k: None
    mgr._queue_delivery = lambda *a, **k: None
    return mgr


def _stage(key, category, order, initial=False, label=None):
    return {'key': key, 'label': label or key.replace('_', ' ').title(), 'category': category,
            'color': None, 'order': order, 'is_initial': initial}


def _looping_group(name='Authority resolution', entity_type='data_product', default=False):
    """``Active -> Needs Review -> Active`` (#831)."""
    return {
        'name': name, 'description': None, 'entity_type': entity_type,
        'is_default_for_type': default,
        'stages': [
            _stage('draft', 'draft', 0, initial=True),
            _stage('active', 'active', 1),
            _stage('needs_review', 'review', 2),
            _stage('retired', 'retired', 3),
        ],
        'transitions': [
            {'from_key': 'draft', 'to_key': 'active'},
            {'from_key': 'active', 'to_key': 'needs_review'},
            {'from_key': 'needs_review', 'to_key': 'active'},
            {'from_key': 'active', 'to_key': 'retired'},
        ],
    }


def _product(db, status='draft', group_id=None, **extra):
    pid = str(uuid.uuid4())
    db.add(DataProductDb(
        id=pid, name=f'Product {pid[:8]}', version='1.0.0', status=status,
        api_version='v1.0.0', kind='DataProduct', lifecycle_stage_group_id=group_id, **extra,
    ))
    db.commit()
    return pid


class TestSeededDefaults:
    @pytest.mark.parametrize('entity_type', ['data_product', 'data_contract', 'asset'])
    def test_the_default_groups_reproduce_the_old_transition_maps(self, db_session, entity_type):
        lifecycle_stage_groups_repo.seed_defaults(db_session)
        db_session.commit()
        group = lifecycle_service.default_group(db_session, entity_type)
        assert group.id == DEFAULT_GROUP_IDS[entity_type]
        expected = default_transitions(entity_type)
        assert {k: [s.key for s in group.targets(k)] for k in group.stages} == expected
        assert group.initial.key == 'draft'

    def test_the_seeded_categories(self, db_session):
        group = lifecycle_service.default_group(db_session, 'data_product')
        assert {k: s.category for k, s in group.stages.items()} == {
            'draft': 'draft', 'sandbox': 'draft', 'proposed': 'review',
            'under_review': 'review', 'approved': 'review', 'active': 'active',
            'deprecated': 'deprecated', 'retired': 'retired',
        }

    def test_seeding_twice_creates_nothing_more(self, db_session):
        assert lifecycle_stage_groups_repo.seed_defaults(db_session) == 3
        assert lifecycle_stage_groups_repo.seed_defaults(db_session) == 0


class TestLoopingGroup:
    def test_a_product_loops_active_needs_review_active(self, db_session, product_manager):
        group = lifecycle_service.save_group(db_session, _looping_group(), 'admin')
        pid = _product(db_session, 'active', group.id)

        walk = ['needs_review', 'active', 'needs_review']
        assert [product_manager.transition_status(pid, s, 'alice').status for s in walk] == walk

    def test_a_move_outside_the_group_is_refused_with_its_allowed_stages(
        self, db_session, product_manager,
    ):
        group = lifecycle_service.save_group(db_session, _looping_group(), 'admin')
        pid = _product(db_session, 'needs_review', group.id)
        with pytest.raises(InvalidStatusTransitionError) as err:
            product_manager.transition_status(pid, 'deprecated', 'alice')
        assert err.value.params == {
            'fromStatus': 'needs_review', 'toStatus': 'deprecated', 'allowed': ['active'],
        }

    def test_a_product_under_review_again_leaves_the_marketplace(self, db_session, product_manager):
        group = lifecycle_service.save_group(db_session, _looping_group(), 'admin')
        pid = _product(db_session, 'active', group.id, publication_scope='organization')
        assert [p.id for p in product_manager.get_published_products()] == [pid]

        product_manager.transition_status(pid, 'needs_review', 'alice')
        assert product_manager.get_published_products() == []

    def test_visibility_follows_the_category_not_the_key(self, db_session):
        group = lifecycle_service.save_group(db_session, _looping_group(), 'admin')
        in_review = SimpleNamespace(status='needs_review', lifecycle_stage_group_id=group.id)
        active = SimpleNamespace(status='active', lifecycle_stage_group_id=group.id)
        retired = SimpleNamespace(status='retired', lifecycle_stage_group_id=group.id)
        assert not is_visible_consumer(in_review)
        assert is_visible_consumer(active)
        assert is_admin_only_status(retired)
        # An elevated reader sees the version in review after the draft, before the active one
        draft = SimpleNamespace(status='draft', lifecycle_stage_group_id=group.id)
        ranks = [compute_rank(r, has_elevated_access=True) for r in (draft, in_review, active)]
        assert ranks == sorted(ranks)


class TestDeadEnds:
    def test_a_stage_with_no_move_out_must_be_retired(self):
        group = _looping_group()
        group['stages'].append(_stage('parked', 'deprecated', 4))
        group['transitions'].append({'from_key': 'active', 'to_key': 'parked'})
        with pytest.raises(LifecycleGroupInvalidError) as err:
            lifecycle_service.validate_definition(group)
        assert err.value.code == 'lifecycle_group_dead_end_stages'
        assert err.value.params == {'stages': ['parked']}

        group['transitions'].append({'from_key': 'parked', 'to_key': 'retired'})
        lifecycle_service.validate_definition(group)


class TestGroupNames:
    def test_a_name_is_stored_trimmed_and_a_padded_duplicate_is_refused(self, db_session):
        saved = lifecycle_service.save_group(db_session, _looping_group('  Foo '), 'admin')
        assert saved.name == 'Foo'
        with pytest.raises(LifecycleGroupConflictError) as err:
            lifecycle_service.save_group(db_session, _looping_group('foo  '), 'admin')
        assert err.value.code == 'lifecycle_group_name_taken'

    def test_a_blank_name_is_refused(self, db_session):
        with pytest.raises(LifecycleGroupInvalidError) as err:
            lifecycle_service.save_group(db_session, _looping_group('   '), 'admin')
        assert err.value.code == 'lifecycle_group_name_required'


class TestConcurrentEdits:
    def test_a_save_based_on_an_older_read_is_refused(self, db_session):
        from datetime import datetime, timezone

        group = lifecycle_service.save_group(db_session, _looping_group(), 'admin')
        read_at = datetime(2026, 11, 14, 10, 0, tzinfo=timezone.utc)
        group.updated_at = datetime(2026, 11, 14, 10, 5, tzinfo=timezone.utc)  # saved since
        db_session.commit()
        changed = _looping_group()
        changed['stages'][2]['label'] = 'Periodic review'
        with pytest.raises(LifecycleGroupConflictError) as err:
            lifecycle_service.save_group(db_session, changed, 'bob', group_id=group.id,
                                         expected_updated_at=read_at)
        assert err.value.code == 'lifecycle_group_changed'

    def test_a_save_based_on_the_current_read_saves(self, db_session):
        group = lifecycle_service.save_group(db_session, _looping_group(), 'admin')
        changed = _looping_group()
        changed['stages'][2]['label'] = 'Periodic review'
        saved = lifecycle_service.save_group(db_session, changed, 'bob', group_id=group.id,
                                             expected_updated_at=group.updated_at)
        assert {s.key: s.label for s in saved.stages}['needs_review'] == 'Periodic review'


class TestSaveValidation:
    @pytest.mark.parametrize('change, code', [
        (lambda g: g['stages'][0].update(is_initial=False), 'lifecycle_group_initial_stage'),
        (lambda g: g['stages'][1].update(is_initial=True), 'lifecycle_group_initial_stage'),
        (lambda g: g['transitions'].remove({'from_key': 'active', 'to_key': 'retired'}),
         'lifecycle_group_unreachable_stages'),
        (lambda g: g['stages'][1].update(category='review'), 'lifecycle_group_no_active_stage'),
        (lambda g: g['stages'][2].update(key='active'), 'lifecycle_stage_duplicate_key'),
        (lambda g: g['stages'][2].update(key='Needs Review'), 'lifecycle_stage_invalid_key'),
        (lambda g: g['stages'][2].update(category='certified'), 'lifecycle_stage_invalid_category'),
        (lambda g: g['transitions'].append({'from_key': 'draft', 'to_key': 'gone'}),
         'lifecycle_transition_unknown_stage'),
    ])
    def test_a_group_that_breaks_a_rule_is_refused_with_its_code(self, db_session, change, code):
        group = _looping_group()
        change(group)
        with pytest.raises(LifecycleGroupInvalidError) as err:
            lifecycle_service.save_group(db_session, group, 'admin')
        assert err.value.code == code

    def test_names_are_unique_per_entity_type(self, db_session):
        lifecycle_service.save_group(db_session, _looping_group(), 'admin')
        with pytest.raises(LifecycleGroupConflictError) as err:
            lifecycle_service.save_group(db_session, _looping_group(), 'admin')
        assert err.value.code == 'lifecycle_group_name_taken'
        # The same name for another entity type is fine
        lifecycle_service.save_group(db_session, _looping_group(entity_type='asset'), 'admin')


class TestIntegrity:
    def test_a_stage_in_use_cant_be_removed(self, db_session):
        group = lifecycle_service.save_group(db_session, _looping_group(), 'admin')
        _product(db_session, 'needs_review', group.id)
        changed = _looping_group()
        changed['stages'] = [s for s in changed['stages'] if s['key'] != 'needs_review']
        changed['transitions'] = [t for t in changed['transitions']
                                  if 'needs_review' not in t.values()]
        with pytest.raises(LifecycleGroupConflictError) as err:
            lifecycle_service.save_group(db_session, changed, 'admin', group_id=group.id)
        assert err.value.code == 'lifecycle_stage_in_use'
        assert err.value.params == {'key': 'needs_review', 'count': 1}

    def test_a_stage_a_workflow_rule_names_cant_be_removed(self, db_session):
        group = lifecycle_service.save_group(db_session, _looping_group(), 'admin')
        db_session.add(ProcessWorkflowDb(
            id=str(uuid.uuid4()), name='Review gate', trigger_config=json.dumps({
                'type': 'before_status_change', 'entity_types': ['data_product'],
                'to_status': 'needs_review',
            }),
        ))
        db_session.commit()
        changed = _looping_group()
        changed['stages'] = [s for s in changed['stages'] if s['key'] != 'needs_review']
        changed['transitions'] = [t for t in changed['transitions']
                                  if 'needs_review' not in t.values()]
        with pytest.raises(LifecycleGroupConflictError) as err:
            lifecycle_service.save_group(db_session, changed, 'admin', group_id=group.id)
        assert err.value.code == 'lifecycle_stage_in_workflow'
        assert err.value.params['workflows'] == ['Review gate']

    def test_a_kept_stage_keeps_its_entities_and_a_label_change_saves(self, db_session):
        group = lifecycle_service.save_group(db_session, _looping_group(), 'admin')
        _product(db_session, 'needs_review', group.id)
        changed = _looping_group()
        changed['stages'][2]['label'] = 'Under periodic review'
        saved = lifecycle_service.save_group(db_session, changed, 'admin', group_id=group.id)
        assert {s.key: s.label for s in saved.stages}['needs_review'] == 'Under periodic review'

    def test_the_default_group_cant_be_deleted(self, db_session):
        lifecycle_stage_groups_repo.seed_defaults(db_session)
        db_session.commit()
        with pytest.raises(LifecycleGroupConflictError) as err:
            lifecycle_service.delete_group(db_session, DEFAULT_GROUP_IDS['data_product'])
        assert err.value.code == 'lifecycle_group_is_default'

    def test_an_assigned_group_cant_be_deleted_an_unused_one_can(self, db_session):
        used = lifecycle_service.save_group(db_session, _looping_group(), 'admin')
        unused = lifecycle_service.save_group(db_session, _looping_group('Spare'), 'admin')
        _product(db_session, 'active', used.id)
        with pytest.raises(LifecycleGroupConflictError) as err:
            lifecycle_service.delete_group(db_session, used.id)
        assert err.value.code == 'lifecycle_group_in_use'
        lifecycle_service.delete_group(db_session, unused.id)
        assert lifecycle_stage_groups_repo.get(db_session, unused.id) is None

    def test_a_new_default_keeps_entities_without_a_group_in_the_old_one(self, db_session):
        lifecycle_stage_groups_repo.seed_defaults(db_session)
        db_session.commit()
        pid = _product(db_session, 'sandbox')
        lifecycle_service.save_group(db_session, _looping_group(default=True), 'admin')
        db_session.expire_all()
        assert db_session.get(DataProductDb, pid).lifecycle_stage_group_id == \
            DEFAULT_GROUP_IDS['data_product']
        assert lifecycle_service.default_group(db_session, 'data_product').name == \
            'Authority resolution'


class TestNamedActions:
    def test_the_seeded_stage_wins_when_allowed(self, db_session):
        contract = SimpleNamespace(status='proposed', lifecycle_stage_group_id=None)
        # proposed -> under_review and approved are both review stages
        assert lifecycle_service.resolve_action(db_session, 'data_contract', contract,
                                                'approve') == 'approved'

    def test_a_custom_group_resolves_by_category(self, db_session):
        group = lifecycle_service.save_group(db_session, _looping_group(), 'admin')
        product = SimpleNamespace(status='active', lifecycle_stage_group_id=group.id)
        assert lifecycle_service.resolve_action(db_session, 'data_product', product,
                                                'submit_review') == 'needs_review'
        assert lifecycle_service.resolve_action(db_session, 'data_product', product,
                                                'retire') == 'retired'

    def test_approving_a_review_without_an_approved_stage_goes_to_active(self, db_session):
        group = lifecycle_service.save_group(db_session, _looping_group(), 'admin')
        product = SimpleNamespace(status='needs_review', lifecycle_stage_group_id=group.id)
        assert lifecycle_service.resolve_action(db_session, 'data_product', product,
                                                'approve') == 'active'
        assert lifecycle_service.awaits_review_decision(db_session, 'data_product', product)

    def test_an_approved_contract_awaits_no_review_decision(self, db_session):
        contract = SimpleNamespace(status='approved', lifecycle_stage_group_id=None)
        assert not lifecycle_service.awaits_review_decision(db_session, 'data_contract', contract)

    def test_no_allowed_stage_of_the_category_is_an_invalid_transition(self, db_session):
        group = lifecycle_service.save_group(db_session, _looping_group(), 'admin')
        product = SimpleNamespace(status='draft', lifecycle_stage_group_id=group.id)
        with pytest.raises(InvalidStatusTransitionError) as err:
            lifecycle_service.resolve_action(db_session, 'data_product', product, 'deprecate')
        assert err.value.params['allowed'] == ['active']

    def test_several_allowed_stages_of_the_category_are_ambiguous(self, db_session):
        group = _looping_group()
        group['stages'].append(_stage('legal_review', 'review', 4))
        group['transitions'].append({'from_key': 'active', 'to_key': 'legal_review'})
        group['transitions'].append({'from_key': 'legal_review', 'to_key': 'active'})
        saved = lifecycle_service.save_group(db_session, group, 'admin')
        product = SimpleNamespace(status='active', lifecycle_stage_group_id=saved.id)
        with pytest.raises(LifecycleActionUnresolvedError) as err:
            lifecycle_service.resolve_action(db_session, 'data_product', product, 'submit_review')
        assert err.value.code == 'lifecycle_action_ambiguous'
        assert err.value.params['candidates'] == ['needs_review', 'legal_review']

    def test_the_product_submit_action_uses_the_resolved_stage(self, db_session, product_manager):
        group = lifecycle_service.save_group(db_session, _looping_group(), 'admin')
        pid = _product(db_session, 'active', group.id)
        assert product_manager.submit_for_review(pid, 'alice').status == 'needs_review'


class TestNewEntities:
    def test_a_new_product_starts_in_the_initial_stage_of_its_group(self, db_session):
        group = lifecycle_service.save_group(db_session, _looping_group(), 'admin')
        assert lifecycle_service.stage_for_new(db_session, 'data_product', group.id, None) == \
            (group.id, 'draft')
        assert lifecycle_service.stage_for_new(db_session, 'data_product', group.id, 'ACTIVE') == \
            (group.id, 'active')

    def test_a_status_that_isnt_a_stage_of_the_group_is_refused(self, db_session):
        group = lifecycle_service.save_group(db_session, _looping_group(), 'admin')
        with pytest.raises(InvalidStatusError) as err:
            lifecycle_service.stage_for_new(db_session, 'data_product', group.id, 'proposed')
        assert err.value.params['allowed'] == ['draft', 'active', 'needs_review', 'retired']

    def test_a_group_of_another_entity_type_is_refused(self, db_session):
        group = lifecycle_service.save_group(db_session, _looping_group(), 'admin')
        with pytest.raises(LifecycleGroupInvalidError) as err:
            lifecycle_service.stage_for_new(db_session, 'data_contract', group.id, None)
        assert err.value.code == 'lifecycle_group_wrong_entity_type'

    def test_a_new_asset_without_status_starts_active(self, db_session):
        assert lifecycle_service.stage_for_new(
            db_session, 'asset', None, None, default_category='active',
        )[1] == 'active'

    def test_a_product_created_in_a_group_stores_it(self, db_session, product_manager):
        group = lifecycle_service.save_group(db_session, _looping_group(), 'admin')
        created = product_manager.create_product({
            'id': str(uuid.uuid4()), 'name': 'Looping', 'version': '1.0.0',
            'lifecycleStageGroupId': group.id,
        }, db=db_session)
        assert created.status == 'draft'
        assert created.lifecycle_stage_group_id == group.id
        assert created.status_category == 'draft'


class TestChangeGroup:
    def test_it_resets_to_the_first_stage_and_writes_the_change_log(self, db_session):
        group = lifecycle_service.save_group(db_session, _looping_group(), 'admin')
        pid = _product(db_session, 'approved')

        result = lifecycle_service.change_group(db_session, 'data_product', pid, group.id, 'bob')

        assert result['status'] == 'draft'
        assert result['group']['id'] == group.id
        assert [s['key'] for s in result['allowed_transitions']] == ['active']
        db_session.expire_all()
        row = db_session.get(DataProductDb, pid)
        assert (row.status, row.lifecycle_stage_group_id) == ('draft', group.id)
        entry = db_session.query(ChangeLogDb).filter(
            ChangeLogDb.entity_id == pid, ChangeLogDb.action == 'LIFECYCLE_GROUP_CHANGE',
        ).one()
        details = json.loads(entry.details_json)
        assert details['from_status'] == 'approved'
        assert details['to_group_id'] == group.id

    def test_it_is_refused_while_a_status_change_request_is_pending(self, db_session):
        from src.controller.change_log_manager import change_log_manager

        group = lifecycle_service.save_group(db_session, _looping_group(), 'admin')
        pid = _product(db_session, 'draft')
        change_log_manager.log_change_with_details(
            db_session, entity_type='data_product', entity_id=pid,
            action='status_change_requested', username='carol',
            details={'request_id': 'req-1', 'from_status': 'draft', 'target_status': 'proposed'},
        )
        with pytest.raises(LifecycleGroupConflictError) as err:
            lifecycle_service.change_group(db_session, 'data_product', pid, group.id, 'bob')
        assert err.value.code == 'lifecycle_change_pending_request'
        db_session.expire_all()
        assert db_session.get(DataProductDb, pid).lifecycle_stage_group_id is None

    def test_it_works_for_assets(self, db_session):
        from src.db_models.assets import AssetTypeDb

        group = lifecycle_service.save_group(
            db_session, _looping_group(entity_type='asset'), 'admin',
        )
        asset_type = AssetTypeDb(id=uuid.uuid4(), name=f'Type {uuid.uuid4().hex[:6]}')
        db_session.add(asset_type)
        asset = AssetDb(id=uuid.uuid4(), name='Orders', asset_type_id=asset_type.id,
                        status='deprecated')
        db_session.add(asset)
        db_session.commit()
        result = lifecycle_service.change_group(db_session, 'asset', str(asset.id), group.id, 'bob')
        assert result['status'] == 'draft'


class TestStandardsRoundTrip:
    def test_export_writes_the_category_status_and_the_exact_stage(self, db_session):
        group = lifecycle_service.save_group(db_session, _looping_group(), 'admin')
        row = SimpleNamespace(status='needs_review', lifecycle_stage_group_id=group.id)
        assert lifecycle_service.export_status(db_session, 'data_product', row) == (
            'proposed',
            {'ontosLifecycleStage': 'needs_review',
             'ontosLifecycleStageGroup': 'Authority resolution',
             'ontosLifecycleStageGroupId': group.id},
        )

    def test_the_default_group_exports_the_standard_values(self, db_session):
        row = SimpleNamespace(status='under_review', lifecycle_stage_group_id=None)
        status, props = lifecycle_service.export_status(db_session, 'data_contract', row)
        assert status == 'proposed'
        assert props['ontosLifecycleStage'] == 'under_review'

    def test_import_restores_the_stage_and_group_and_removes_the_properties(self, db_session):
        group = lifecycle_service.save_group(db_session, _looping_group(), 'admin')
        custom = [
            {'property': 'ontosLifecycleStage', 'value': 'needs_review'},
            {'property': 'ontosLifecycleStageGroup', 'value': 'authority RESOLUTION'},
            {'property': 'owner', 'value': 'x'},
        ]
        assert lifecycle_service.imported_status(db_session, 'data_product', 'proposed',
                                                 custom) == (group.id, 'needs_review', None)
        assert custom == [{'property': 'owner', 'value': 'x'}]

    def test_an_unknown_group_maps_by_category_into_the_default(self, db_session):
        custom = [
            {'property': 'ontosLifecycleStage', 'value': 'needs_review'},
            {'property': 'ontosLifecycleStageGroup', 'value': 'Elsewhere'},
        ]
        group_id, key, note = lifecycle_service.imported_status(
            db_session, 'data_product', 'proposed', custom,
        )
        assert (group_id, key) == (None, 'proposed')
        assert note['code'] == 'imported_lifecycle_group_unknown'

    def test_an_older_export_keeps_its_stage_key(self, db_session):
        assert lifecycle_service.imported_status(
            db_session, 'data_product', 'under_review', [],
        )[1] == 'under_review'

    def test_an_unknown_status_starts_in_draft_with_a_note(self, db_session):
        _group, key, note = lifecycle_service.imported_status(
            db_session, 'data_contract', 'production', None,
        )
        assert key == 'draft'
        assert note['code'] == 'imported_status_mapped'

    def test_a_product_export_round_trips_through_import(self, db_session, product_manager):
        group = lifecycle_service.save_group(db_session, _looping_group(), 'admin')
        pid = _product(db_session, 'needs_review', group.id)
        odps = product_manager.build_odps_export(pid, db=db_session)
        assert odps['status'] == 'proposed'
        props = {c['property']: c['value'] for c in odps['customProperties']}
        assert props['ontosLifecycleStage'] == 'needs_review'
        assert props['ontosLifecycleStageGroup'] == 'Authority resolution'

        result = product_manager.create_products_from_files(
            [('p.json', json.dumps(odps).encode('utf-8'))], user='alice@example.com',
            on_duplicate='new',
        )
        assert (result.created, result.failed) == (1, 0), result.items
        imported = db_session.get(DataProductDb, result.created_ids[0])
        assert (imported.lifecycle_stage_group_id, imported.status) == (group.id, 'needs_review')
        # The lifecycle properties set the stage and group; they aren't stored as such
        assert 'ontosLifecycleStage' not in {
            p.property for p in imported.custom_properties
        }


def test_a_contract_keeps_its_group_on_transitions(db_session):
    from pathlib import Path

    from src.controller.data_contracts_manager import DataContractsManager

    mgr = DataContractsManager(data_dir=Path('/tmp'))
    mgr._update_search_index = lambda *a, **k: None
    group = lifecycle_service.save_group(
        db_session, _looping_group(entity_type='data_contract'), 'admin',
    )
    cid = str(uuid.uuid4())
    db_session.add(DataContractDb(id=cid, name='C', version='1.0.0', status='active',
                                  lifecycle_stage_group_id=group.id))
    db_session.commit()
    assert mgr.transition_status(db=db_session, contract_id=cid,
                                 new_status='needs_review').status == 'needs_review'
    with pytest.raises(InvalidStatusTransitionError):
        mgr.transition_status(db=db_session, contract_id=cid, new_status='approved')


def _intake_group(entity_type='data_product'):
    """A group whose first stage isn't ``draft``, with one review step."""
    return {
        'name': 'Intake', 'description': None, 'entity_type': entity_type,
        'is_default_for_type': False,
        'stages': [
            _stage('intake', 'draft', 0, initial=True),
            _stage('needs_review', 'review', 1),
            _stage('live', 'active', 2),
            _stage('gone', 'retired', 3),
        ],
        'transitions': [
            {'from_key': 'intake', 'to_key': 'needs_review'},
            {'from_key': 'needs_review', 'to_key': 'live'},
            {'from_key': 'needs_review', 'to_key': 'intake'},
            {'from_key': 'live', 'to_key': 'gone'},
        ],
    }


class TestReviewFeedback:
    def test_a_new_product_without_status_starts_in_its_groups_first_stage(
        self, db_session, product_manager,
    ):
        group = lifecycle_service.save_group(db_session, _intake_group(), 'admin')
        created = product_manager.create_product({
            'id': str(uuid.uuid4()), 'name': 'Intake product', 'version': '1.0.0',
            'lifecycleStageGroupId': group.id,
        }, db=db_session)
        assert created.status == 'intake'

    def test_new_versions_and_clones_keep_the_group_and_start_in_its_first_stage(
        self, db_session, product_manager,
    ):
        from pathlib import Path

        from src.controller.data_contracts_manager import DataContractsManager

        group = lifecycle_service.save_group(db_session, _intake_group(), 'admin')
        pid = _product(db_session, 'live', group.id)
        clone = product_manager.clone_product_for_new_version(
            db_session, pid, '2.0.0', current_user='alice',
        )
        db_session.expire_all()
        row = db_session.get(DataProductDb, clone.id)
        assert (row.lifecycle_stage_group_id, row.status) == (group.id, 'intake')

        contract_group = lifecycle_service.save_group(
            db_session, _intake_group('data_contract'), 'admin',
        )
        cid = str(uuid.uuid4())
        db_session.add(DataContractDb(id=cid, name='C', version='1.0.0', status='live',
                                      lifecycle_stage_group_id=contract_group.id,
                                      version_family_id=cid))
        db_session.commit()
        mgr = DataContractsManager(data_dir=Path('/tmp'))
        mgr._update_search_index = lambda *a, **k: None
        new_contract = mgr.clone_contract_for_new_version(db_session, cid, '2.0.0',
                                                          current_user='alice')
        assert (new_contract.lifecycle_stage_group_id, new_contract.status) == \
            (contract_group.id, 'intake')

    def test_a_review_request_in_a_group_without_a_start_step_stays_submitted(
        self, db_session, product_manager, monkeypatch,
    ):
        from src.common import workflow_triggers

        registry = MagicMock()
        registry.before_status_change.return_value = (True, [])
        registry.on_request_review.return_value = []
        monkeypatch.setattr(workflow_triggers, 'get_trigger_registry', lambda db: registry)
        group = lifecycle_service.save_group(db_session, _intake_group(), 'admin')
        pid = _product(db_session, 'intake', group.id)

        product_manager.request_review(pid, None, 'owner@example.com', current_user='owner')

        db_session.expire_all()
        assert db_session.get(DataProductDb, pid).status == 'needs_review'
        data = registry.on_request_review.call_args.kwargs['entity_data']
        assert data['to_status'] == 'needs_review'

    def test_a_paused_workflow_run_of_the_entity_blocks_a_group_change(self, db_session):
        from src.db_models.process_workflows import WorkflowExecutionDb

        group = lifecycle_service.save_group(db_session, _looping_group(), 'admin')
        pid = _product(db_session, 'draft')
        other = _product(db_session, 'draft')
        workflow = ProcessWorkflowDb(id=str(uuid.uuid4()), name='Approval',
                                     trigger_config='{}')
        db_session.add(workflow)
        db_session.flush()
        execution = WorkflowExecutionDb(
            id=str(uuid.uuid4()), workflow_id=workflow.id, status='paused',
            trigger_context=json.dumps({'entity_id': pid, 'entity_type': 'data_product'}),
        )
        db_session.add(execution)
        db_session.commit()

        with pytest.raises(LifecycleGroupConflictError) as err:
            lifecycle_service.change_group(db_session, 'data_product', pid, group.id, 'bob')
        assert err.value.params['requestId'] == execution.id
        # Another entity's paused run doesn't block
        assert lifecycle_service.change_group(
            db_session, 'data_product', other, group.id, 'bob',
        )['status'] == 'draft'

    def test_a_group_change_unpublishes_an_entity_reset_to_an_unpublished_stage(
        self, db_session,
    ):
        group = lifecycle_service.save_group(db_session, _looping_group(), 'admin')
        pid = _product(db_session, 'active', publication_scope='organization')
        lifecycle_service.change_group(db_session, 'data_product', pid, group.id, 'bob')
        db_session.expire_all()
        assert db_session.get(DataProductDb, pid).publication_scope == 'none'

    def test_the_approvals_queue_lists_custom_review_stages_but_not_approved(self, db_session):
        from src.controller.approvals_manager import ApprovalsManager

        group = lifecycle_service.save_group(db_session, _intake_group(), 'admin')
        waiting = _product(db_session, 'needs_review', group.id)
        approved = _product(db_session, 'approved')
        queue = ApprovalsManager().get_approvals_queue(
            db_session, can_see_contract=lambda c: True, can_see_product=lambda p: True,
        )
        ids = {p['id'] for p in queue['products']}
        assert waiting in ids and approved not in ids


class TestAssetStatusChanges:
    def _asset(self, db_session, status):
        from src.db_models.assets import AssetTypeDb

        asset_type = AssetTypeDb(id=uuid.uuid4(), name=f'Type {uuid.uuid4().hex[:6]}')
        db_session.add(asset_type)
        asset = AssetDb(id=uuid.uuid4(), name='Orders', asset_type_id=asset_type.id,
                        status=status)
        db_session.add(asset)
        db_session.commit()
        return asset

    @staticmethod
    def _manager():
        from src.controller.assets_manager import AssetsManager

        mgr = AssetsManager()
        mgr._update_search_index = lambda *a, **k: None
        return mgr

    @pytest.mark.parametrize('start, target', [
        ('active', 'draft'), ('draft', 'retired'), ('retired', 'active'),
        ('deprecated', 'draft'), ('active', 'deprecated'),
    ])
    def test_the_default_group_keeps_every_move_assets_had(self, db_session, start, target):
        from src.models.assets import AssetUpdate

        asset = self._asset(db_session, start)
        updated = self._manager().update_asset(
            db_session, asset_id=asset.id, asset_in=AssetUpdate(status=target),
            current_user_id='u',
        )
        assert updated.status == target

    def test_a_custom_group_refuses_a_move_it_doesnt_allow_with_a_code(self, db_session):
        from src.models.assets import AssetUpdate

        group = lifecycle_service.save_group(
            db_session, _looping_group(entity_type='asset'), 'admin',
        )
        asset = self._asset(db_session, 'active')
        asset.lifecycle_stage_group_id = group.id
        db_session.commit()
        mgr = self._manager()
        with pytest.raises(InvalidStatusTransitionError) as err:
            mgr.update_asset(db_session, asset_id=asset.id,
                             asset_in=AssetUpdate(status='draft'), current_user_id='u')
        assert err.value.params['allowed'] == ['needs_review', 'retired']
        # Repeating the stored status is no move
        assert mgr.update_asset(db_session, asset_id=asset.id,
                                asset_in=AssetUpdate(status='ACTIVE', name='Orders 2'),
                                current_user_id='u').status == 'active'

    @pytest.mark.parametrize('status', ['draft', 'active', 'deprecated', 'retired'])
    def test_a_new_asset_takes_any_of_the_old_statuses(self, db_session, status):
        _group, key = lifecycle_service.stage_for_new(
            db_session, 'asset', None, status, default_category='active',
        )
        assert key == status
        with pytest.raises(InvalidStatusError):
            lifecycle_service.stage_for_new(db_session, 'asset', None, 'in_use')

    def test_a_bulk_row_moves_through_the_lifecycle(self, db_session):
        from src.controller.asset_bulk_manager import _bulk_status

        asset = self._asset(db_session, 'active')
        assert _bulk_status(db_session, asset, None) == 'active'
        assert _bulk_status(db_session, asset, 'draft') == 'draft'
        group = lifecycle_service.save_group(
            db_session, _looping_group(entity_type='asset'), 'admin',
        )
        asset.lifecycle_stage_group_id = group.id
        db_session.commit()
        asset.status = 'active'
        db_session.commit()
        with pytest.raises(InvalidStatusTransitionError):
            _bulk_status(db_session, asset, 'draft')


class TestIndependentReview:
    def test_changing_to_the_current_group_is_refused(self, db_session):
        pid = _product(db_session, 'retired')
        with pytest.raises(LifecycleGroupConflictError) as err:
            lifecycle_service.change_group(
                db_session, 'data_product', pid, DEFAULT_GROUP_IDS['data_product'], 'bob',
            )
        assert err.value.code == 'lifecycle_change_same_group'
        db_session.expire_all()
        assert db_session.get(DataProductDb, pid).status == 'retired'

    def test_a_group_whose_first_stage_isnt_draft_is_refused(self, db_session):
        group = _looping_group()
        group['stages'][0].update(is_initial=False)
        group['stages'][1].update(is_initial=True)  # active first: would skip review
        group['transitions'].append({'from_key': 'active', 'to_key': 'draft'})
        with pytest.raises(LifecycleGroupInvalidError) as err:
            lifecycle_service.save_group(db_session, group, 'admin')
        assert err.value.code == 'lifecycle_group_initial_not_draft'

    def test_sandbox_ranks_below_the_other_stages_for_an_elevated_reader(self):
        sandbox = SimpleNamespace(status='sandbox', lifecycle_stage_group_id=None)
        active = SimpleNamespace(status='active', lifecycle_stage_group_id=None)
        draft = SimpleNamespace(status='draft', lifecycle_stage_group_id=None)
        rank = lambda r: compute_rank(r, has_elevated_access=True)  # noqa: E731
        assert rank(draft) < rank(active) < rank(sandbox)

    def test_backfilled_rows_match_while_no_group_is_loaded(self, db_session):
        pid = _product(db_session, 'proposed', DEFAULT_GROUP_IDS['data_product'])
        lifecycle_service.invalidate()
        rows = db_session.query(DataProductDb).filter(lifecycle_service.category_filter(
            db_session, DataProductDb, 'data_product', ['review'],
        )).all()
        assert [r.id for r in rows] == [pid]

    def test_the_personal_draft_filter_judges_each_row_by_its_own_group(self, db_session):
        from src.common.version_visibility import not_others_personal_draft

        intake = lifecycle_service.save_group(db_session, _intake_group(), 'admin')
        other = _looping_group('Intake is live')
        other['stages'].append(_stage('intake', 'active', 4))
        other['transitions'] += [{'from_key': 'draft', 'to_key': 'intake'},
                                 {'from_key': 'intake', 'to_key': 'retired'}]
        other_group = lifecycle_service.save_group(db_session, other, 'admin')
        hidden = _product(db_session, 'intake', intake.id, draft_owner_id='bob@example.com')
        shown = _product(db_session, 'intake', other_group.id, draft_owner_id='bob@example.com')
        visible = {r.id for r in db_session.query(DataProductDb).filter(
            not_others_personal_draft(DataProductDb, 'alice@example.com'),
        )}
        assert shown in visible and hidden not in visible

    def test_a_status_outside_the_group_exports_a_standard_value(self, db_session):
        row = SimpleNamespace(status='archived', lifecycle_stage_group_id=None)
        status, props = lifecycle_service.export_status(db_session, 'data_contract', row)
        assert status == 'draft'
        assert props['ontosLifecycleStage'] == 'archived'

    @pytest.mark.parametrize('status, approved, expected', [
        ('draft', True, 'active'),
        # The default asset group allows every move, as before stage groups
        ('retired', True, 'active'),
        ('active', False, 'draft'),
    ])
    def test_an_asset_review_result_follows_the_assets_lifecycle(
        self, db_session, status, approved, expected,
    ):
        from src.common.workflow_executor import WorkflowExecutor
        from src.db_models.assets import AssetTypeDb
        from src.models.process_workflows import TriggerContext, TriggerType

        asset_type = AssetTypeDb(id=uuid.uuid4(), name=f'Type {uuid.uuid4().hex[:6]}')
        db_session.add(asset_type)
        asset = AssetDb(id=uuid.uuid4(), name='Orders', asset_type_id=asset_type.id,
                        status=status)
        db_session.add(asset)
        db_session.commit()
        context = TriggerContext(
            entity_type='asset', entity_id=str(asset.id), entity_name='Orders',
            trigger_type=TriggerType.ON_REQUEST_REVIEW,
        )
        workflow = SimpleNamespace(name='Review',
                                   trigger=SimpleNamespace(type=TriggerType.ON_REQUEST_REVIEW))
        WorkflowExecutor(db_session)._handle_workflow_completion(
            trigger_context=context, workflow=workflow, succeeded=approved,
        )
        db_session.expire_all()
        assert db_session.get(AssetDb, asset.id).status == expected


class TestCacheMiss:
    def test_a_group_another_worker_created_is_loaded_on_first_use(self, db_session):
        group = lifecycle_service.save_group(db_session, _looping_group(), 'admin')
        # This worker's cache is fresh but predates the group
        with lifecycle_service._lock:
            lifecycle_service._groups.pop(group.id)
        row = SimpleNamespace(status='needs_review', lifecycle_stage_group_id=group.id)
        assert lifecycle_service.allowed_target_keys(db_session, 'data_product', row) == \
            ['active']

    def test_the_category_of_a_row_reloads_on_a_miss_too(self, db_session):
        group = lifecycle_service.save_group(db_session, _intake_group(), 'admin')
        with lifecycle_service._lock:
            lifecycle_service._groups.pop(group.id)
        row = SimpleNamespace(status='live', lifecycle_stage_group_id=group.id)
        assert lifecycle_service.category_of_row(row, db_session) == 'active'

    def test_a_group_still_missing_after_the_reload_raises(self, db_session):
        from src.controller.lifecycle_service import LifecycleGroupNotFoundError

        lifecycle_service.save_group(db_session, _looping_group(), 'admin')
        row = SimpleNamespace(status='draft', lifecycle_stage_group_id='no-such-group')
        with pytest.raises(LifecycleGroupNotFoundError):
            lifecycle_service.check_transition(db_session, 'data_product', row, 'sandbox')


def _two_step_review_group(entity_type='data_contract'):
    """``draft -> review_a -> approved_x -> active``: no seeded review keys."""
    return {
        'name': 'Two step review', 'description': None, 'entity_type': entity_type,
        'is_default_for_type': False,
        'stages': [
            _stage('draft', 'draft', 0, initial=True),
            _stage('review_a', 'review', 1),
            _stage('approved_x', 'review', 2),
            _stage('active', 'active', 3),
            _stage('retired', 'retired', 4),
        ],
        'transitions': [
            {'from_key': 'draft', 'to_key': 'review_a'},
            {'from_key': 'review_a', 'to_key': 'approved_x'},
            {'from_key': 'review_a', 'to_key': 'draft'},
            {'from_key': 'approved_x', 'to_key': 'active'},
            {'from_key': 'active', 'to_key': 'retired'},
        ],
    }


class TestReviewDecisionByApproveTarget:
    def test_the_stage_approve_moves_to_no_longer_awaits_a_decision(self, db_session):
        group = lifecycle_service.save_group(db_session, _two_step_review_group(), 'admin')
        waiting = SimpleNamespace(status='review_a', lifecycle_stage_group_id=group.id)
        approved = SimpleNamespace(status='approved_x', lifecycle_stage_group_id=group.id)

        assert lifecycle_service.resolve_action(
            db_session, 'data_contract', waiting, 'approve') == 'approved_x'
        assert lifecycle_service.awaits_review_decision(db_session, 'data_contract', waiting)
        assert not lifecycle_service.awaits_review_decision(
            db_session, 'data_contract', approved)
        assert lifecycle_service.contract_publishable(db_session, approved)
        assert not lifecycle_service.contract_publishable(db_session, waiting)

    @pytest.mark.parametrize('entity_type', ['data_product', 'data_contract'])
    def test_the_default_groups_keep_approved_as_the_decided_stage(
        self, db_session, entity_type,
    ):
        def awaits(status):
            row = SimpleNamespace(status=status, lifecycle_stage_group_id=None)
            return lifecycle_service.awaits_review_decision(db_session, entity_type, row)

        assert [awaits(s) for s in ('proposed', 'under_review', 'approved', 'active')] == [
            True, True, False, False,
        ]


class TestCategoryChangeInUse:
    def test_a_stage_with_entities_cant_leave_the_active_category(self, db_session):
        group = lifecycle_service.save_group(db_session, _looping_group(), 'admin')
        _product(db_session, 'active', group.id, publication_scope='organization')
        changed = _looping_group()
        changed['stages'][1]['category'] = 'draft'
        changed['stages'][2]['category'] = 'active'  # keep one active stage
        with pytest.raises(LifecycleGroupConflictError) as err:
            lifecycle_service.save_group(db_session, changed, 'admin', group_id=group.id)
        assert err.value.code == 'lifecycle_stage_category_in_use'
        assert err.value.params == {
            'key': 'active', 'fromCategory': 'active', 'toCategory': 'draft', 'count': 1,
        }

    def test_a_stage_in_use_may_move_between_draft_and_review(self, db_session):
        group = lifecycle_service.save_group(db_session, _looping_group(), 'admin')
        _product(db_session, 'needs_review', group.id)
        changed = _looping_group()
        changed['stages'][2]['category'] = 'draft'
        saved = lifecycle_service.save_group(db_session, changed, 'admin', group_id=group.id)
        assert {s.key: s.category for s in saved.stages}['needs_review'] == 'draft'

    def test_an_empty_stage_may_leave_the_active_category(self, db_session):
        group = lifecycle_service.save_group(db_session, _looping_group(), 'admin')
        _product(db_session, 'draft', group.id)
        changed = _looping_group()
        changed['stages'][1]['category'] = 'review'
        changed['stages'][2]['category'] = 'active'
        saved = lifecycle_service.save_group(db_session, changed, 'admin', group_id=group.id)
        assert {s.key: s.category for s in saved.stages}['active'] == 'review'


class TestRoundTripByGroupId:
    def test_a_renamed_group_is_found_by_its_exported_id(self, db_session):
        group = lifecycle_service.save_group(db_session, _looping_group(), 'admin')
        row = SimpleNamespace(status='needs_review', lifecycle_stage_group_id=group.id)
        _status, props = lifecycle_service.export_status(db_session, 'data_product', row)
        renamed = _looping_group('Authority resolution v2')
        lifecycle_service.save_group(db_session, renamed, 'admin', group_id=group.id)

        custom = [{'property': k, 'value': v} for k, v in props.items()]
        assert lifecycle_service.imported_status(
            db_session, 'data_product', 'proposed', custom,
        ) == (group.id, 'needs_review', None)
        assert custom == []

    def test_an_unknown_id_falls_back_to_the_name(self, db_session):
        group = lifecycle_service.save_group(db_session, _looping_group(), 'admin')
        custom = [
            {'property': 'ontosLifecycleStage', 'value': 'needs_review'},
            {'property': 'ontosLifecycleStageGroup', 'value': 'Authority resolution'},
            {'property': 'ontosLifecycleStageGroupId', 'value': 'from-another-install'},
        ]
        assert lifecycle_service.imported_status(
            db_session, 'data_product', 'proposed', custom,
        ) == (group.id, 'needs_review', None)

    def test_the_default_group_exports_its_seeded_id(self, db_session):
        row = SimpleNamespace(status='draft', lifecycle_stage_group_id=None)
        _status, props = lifecycle_service.export_status(db_session, 'data_contract', row)
        assert props['ontosLifecycleStageGroupId'] == DEFAULT_GROUP_IDS['data_contract']


class TestChangeGroupSideEffects:
    def test_an_asset_is_reindexed_and_a_tag_sync_is_requested(self, db_session, monkeypatch):
        from src.common import app_state, uc_tag_sync_trigger
        from src.db_models.assets import AssetTypeDb

        search = MagicMock()
        monkeypatch.setitem(app_state._managers_registry, 'search_manager', search)
        requests = []
        monkeypatch.setattr(uc_tag_sync_trigger, 'request_uc_tag_sync_after_transition',
                            lambda *args: requests.append(args))
        group = lifecycle_service.save_group(
            db_session, _looping_group(entity_type='asset'), 'admin',
        )
        asset_type = AssetTypeDb(id=uuid.uuid4(), name=f'Type {uuid.uuid4().hex[:6]}')
        db_session.add(asset_type)
        asset = AssetDb(id=uuid.uuid4(), name='Orders', asset_type_id=asset_type.id,
                        status='deprecated')
        db_session.add(asset)
        db_session.commit()

        lifecycle_service.change_group(db_session, 'asset', str(asset.id), group.id, 'bob')

        item = search.upsert_item.call_args.args[0]
        assert item.id == f'asset::{asset.id}'
        assert requests == [('asset', str(asset.id), 'deprecated', 'draft')]


class TestCreateInAGroupWithoutDraft:
    def test_a_product_created_without_a_status_starts_in_the_default_groups_first_stage(
        self, db_session, product_manager,
    ):
        default = _intake_group()
        default['is_default_for_type'] = True
        lifecycle_service.save_group(db_session, default, 'admin')
        created = product_manager.create_product({
            'id': str(uuid.uuid4()), 'name': 'Intake by default', 'version': '1.0.0',
        }, db=db_session)
        assert created.status == 'intake'

    def test_a_contract_created_without_a_status_starts_in_its_groups_first_stage(
        self, db_session,
    ):
        from pathlib import Path

        from src.controller.data_contracts_manager import DataContractsManager
        from src.models.data_contracts_api import DataContractCreate

        group = lifecycle_service.save_group(
            db_session, _intake_group('data_contract'), 'admin',
        )
        mgr = DataContractsManager(data_dir=Path('/tmp'))
        mgr._queue_delivery = lambda *a, **k: None
        mgr._update_search_index = lambda *a, **k: None
        payload = DataContractCreate(name='Intake contract', version='1.0.0',
                                     lifecycle_stage_group_id=group.id)
        created = mgr.create_contract_with_relations(
            db=db_session, contract_data=payload, current_user='alice@example.com',
        )
        assert (created.lifecycle_stage_group_id, created.status) == (group.id, 'intake')


class TestSqlFiltersOnAStaleCache:
    """A group another worker created while this worker's cache is still fresh."""

    def _stale(self, group_id):
        with lifecycle_service._lock:
            lifecycle_service._groups.pop(group_id)

    def test_the_category_filter_sees_the_new_groups_stages(self, db_session):
        group = lifecycle_service.save_group(db_session, _intake_group(), 'admin')
        pid = _product(db_session, 'live', group.id)
        self._stale(group.id)
        rows = db_session.query(DataProductDb).filter(lifecycle_service.category_filter(
            db_session, DataProductDb, 'data_product', ['active'],
        )).all()
        assert pid in {r.id for r in rows}

    def test_the_first_stage_filter_judges_rows_by_the_new_group(self, db_session):
        group = lifecycle_service.save_group(db_session, _intake_group(), 'admin')
        pid = _product(db_session, 'intake', group.id)
        self._stale(group.id)
        rows = db_session.query(DataProductDb).filter(lifecycle_service.first_stage_filter(
            DataProductDb, 'data_product', db_session,
        )).all()
        assert pid in {r.id for r in rows}
