"""Metric view definition change requests: draft, pre-checks, delivery, audit (#1124 phase 3).

Unity Catalog is a mocked workspace client (the user's); Git is a fake working
copy; the workflow is replaced by direct calls to ``on_workflow_completed``
(the integration tests run the real one).
"""
import json
import uuid
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from databricks.sdk.errors import NotFound, PermissionDenied
from databricks.sdk.service.catalog import TableType

from src.common.metric_views import parse_metric_view_definition
from src.controller import delivery_service as delivery_module
from src.controller import metric_view_change_requests_manager as module
from src.controller.delivery_service import (
    DeliveryChangeType, DeliveryMode, DeliveryPayload, DeliveryService,
)
from src.controller.metric_view_baselines_manager import MetricViewBaselinesManager
from src.controller.metric_view_change_requests_manager import (
    ChangeRequestError, MetricViewChangeRequestsManager, build_ddl, delivery_filename,
    is_group_principal, validate_proposal,
)
from src.controller.semantic_links_manager import SemanticLinksManager
from src.db_models.assets import AssetDb, AssetTypeDb
from src.db_models.business_owners import BusinessOwnerDb
from src.db_models.business_roles import BusinessRoleDb
from src.db_models.metric_view_baselines import MetricViewBaselineDb
from src.db_models.metric_view_change_requests import MetricViewChangeRequestDb
from src.db_models.notifications import NotificationDb
from src.models.metric_view_change_requests import MetricViewChangeRequestCreate
from src.models.semantic_links import EntitySemanticLinkCreate

VIEW = 'main.sales.orders_mv'
BASE = """\
version: 1.1
source: main.sales.orders
dimensions:
  - name: Region
    expr: region
measures:
  - name: Total Revenue
    expr: SUM(amount)
"""
PROPOSED = BASE.replace('SUM(amount)', 'SUM(net_amount)')
MATERIALIZED = PROPOSED + """\
materialization:
  schedule: every 6 hours
  mode: relaxed
  materialized_views:
    - name: baseline
      type: unaggregated
"""
OWNER = 'owner@example.com'
REQUESTER = 'modeller@example.com'
APPROVER = 'steward@example.com'


def _table(definition=BASE, owner=OWNER, **extra):
    return SimpleNamespace(table_type=TableType.METRIC_VIEW, view_definition=definition,
                           owner=owner, **extra)


@pytest.fixture
def ws():
    """The requester's workspace client: the metric view, and its sources by name."""
    client = MagicMock()
    tables = {VIEW: _table()}

    def get(full_name):
        if full_name not in tables:
            raise NotFound('no such table')
        return tables[full_name]

    client.tables.get.side_effect = get
    client.tables_by_name = tables
    client.policies.list_policies.return_value = iter([])
    return client


@pytest.fixture
def asset(db_session):
    asset_type = AssetTypeDb(name=f'Metric View-{uuid.uuid4().hex[:6]}', category='semantic')
    db_session.add(asset_type)
    db_session.flush()
    row = AssetDb(name='orders_mv', asset_type_id=asset_type.id, platform='databricks',
                  location=VIEW)
    db_session.add(row)
    role = db_session.query(BusinessRoleDb).filter_by(name='Data Owner').first()
    if role is None:
        role = BusinessRoleDb(id=uuid.uuid4(), name='Data Owner')
        db_session.add(role)
        db_session.flush()
    db_session.add(BusinessOwnerDb(
        id=uuid.uuid4(), object_type='asset', object_id=str(row.id),
        user_email=OWNER, role_id=role.id, is_active=True,
    ))
    db_session.flush()
    return row


@pytest.fixture
def links(db_session):
    return SemanticLinksManager(db_session, semantic_models_manager=MagicMock())


@pytest.fixture
def manager(db_session, links):
    return MetricViewChangeRequestsManager(db_session, links)


@pytest.fixture(autouse=True)
def audits(monkeypatch):
    entries = []
    from src.controller import audit_manager
    monkeypatch.setattr(audit_manager, 'log_system_action',
                        lambda **kwargs: entries.append(kwargs))
    return entries


@pytest.fixture
def review(monkeypatch):
    """The review workflow: an execution paused for approval, as the default one does."""
    from src.common import workflow_triggers
    from src.models.process_workflows import ExecutionStatus

    registry = MagicMock()
    registry.on_request_definition_change.return_value = [
        SimpleNamespace(id='exec-1', status=ExecutionStatus.PAUSED)
    ]
    monkeypatch.setattr(workflow_triggers, 'get_trigger_registry', lambda db: registry)
    return registry


def _draft(manager, asset, ws, definition=PROPOSED):
    return manager.create_draft(
        asset.id, ws, MetricViewChangeRequestCreate(definition=definition, justification='Net'),
        REQUESTER,
    )


def _code(excinfo):
    return excinfo.value.code


class TestValidateProposal:
    def test_unparseable_yaml_is_refused_with_its_position(self):
        with pytest.raises(ChangeRequestError) as e:
            validate_proposal('version: 1.1\nsource: [unclosed\n')

        assert _code(e) == 'metric_view_definition_invalid_yaml'
        assert e.value.http_status == 422
        assert set(e.value.params) == {'line', 'column'}

    @pytest.mark.parametrize('text, code', [
        ('- a\n- b\n', 'metric_view_definition_invalid'),
        ('version: 1.1\nmeasures: []\n', 'metric_view_definition_source_missing'),
        (BASE.replace('SUM(amount)', "CONCAT('$$', x)"), 'metric_view_definition_dollar_quote'),
        (BASE.replace('name: Total Revenue', 'name: region'), 'metric_view_duplicate_field'),
    ])
    def test_a_proposal_unity_catalog_would_refuse_is_refused(self, text, code):
        with pytest.raises(ChangeRequestError) as e:
            validate_proposal(text)

        assert _code(e) == code

    def test_a_valid_proposal_is_parsed(self):
        spec = validate_proposal(PROPOSED)

        assert [m['expr'] for m in spec['measures']] == ['SUM(net_amount)']


def test_the_ddl_replaces_the_whole_definition_with_quoted_names():
    ddl = build_ddl('main.sales.orders`mv', PROPOSED)

    assert ddl.startswith('ALTER VIEW `main`.`sales`.`orders``mv` AS $$\n')
    assert ddl.endswith('SUM(net_amount)\n$$')
    assert PROPOSED.rstrip() in ddl


def test_delivery_files_are_named_by_the_view_and_stay_in_their_folder():
    assert delivery_filename('Main.Sales.Orders_MV', 'sql') == 'main.sales.orders_mv.sql'
    assert '/' not in delivery_filename('main.sales/../x', 'yaml')


@pytest.mark.parametrize('owner, group', [
    ('owner@example.com', False),
    ('7f0c1a2b-3c4d-4e5f-8a9b-0c1d2e3f4a5b', False),
    ('data-engineers', True),
    (None, False),
])
def test_a_group_owner_is_neither_an_email_nor_an_application_id(owner, group):
    assert is_group_principal(owner) is group


class TestDraft:
    def test_a_draft_keeps_the_base_definition_its_digest_and_owner(
        self, db_session, manager, asset, ws, audits
    ):
        draft = _draft(manager, asset, ws)

        row = db_session.get(MetricViewChangeRequestDb, draft.id)
        assert row.status == 'draft' and row.requested_by == REQUESTER
        assert row.base_definition == BASE and row.base_owner == OWNER
        assert row.metric_view_fqn == VIEW
        assert len(row.base_digest) == 64 and row.base_digest != row.proposed_digest
        assert draft.base_metric_view['measures'][0]['expr'] == 'SUM(amount)'
        assert draft.proposed_metric_view['measures'][0]['expr'] == 'SUM(net_amount)'
        assert draft.ddl.startswith('ALTER VIEW `main`.`sales`.`orders_mv` AS $$')
        assert [a['action'] for a in audits] == ['METRIC_VIEW_CHANGE_REQUEST_CREATED']
        assert audits[0]['details'] == {
            'request_id': str(row.id), 'asset_id': str(asset.id), 'metric_view_fqn': VIEW,
            'base_digest': row.base_digest, 'proposed_digest': row.proposed_digest,
        }

    def test_a_proposal_equal_to_the_current_definition_is_refused(self, manager, asset, ws):
        # The same definition as Unity Catalog stores it (fields -> dimensions)
        with pytest.raises(ChangeRequestError) as e:
            _draft(manager, asset, ws, BASE.replace('dimensions:', 'fields:'))

        assert _code(e) == 'metric_view_definition_unchanged'

    def test_an_unparseable_current_definition_is_refused(self, manager, asset, ws):
        ws.tables_by_name[VIEW] = _table('not: [valid')

        with pytest.raises(ChangeRequestError) as e:
            _draft(manager, asset, ws)

        assert _code(e) == 'metric_view_base_unreadable'

    def test_removing_a_linked_field_is_a_warning(self, manager, asset, ws, links):
        links.add(EntitySemanticLinkCreate(
            entity_type='uc_column', entity_id=f'{VIEW}.Region',
            iri='http://example.com/glossary#Region',
        ), created_by='steward@example.com')
        without_region = PROPOSED.replace('  - name: Region\n    expr: region\n', '')

        draft = _draft(manager, asset, ws, without_region)

        assert [(w.code, w.params) for w in draft.warnings] == [
            ('metric_view_linked_field_removed', {'field': 'Region', 'links': 1}),
        ]


class TestSubmitPreChecks:
    def test_submit_fires_the_trigger_and_puts_the_request_in_review(
        self, db_session, manager, asset, ws, review, audits
    ):
        draft = _draft(manager, asset, ws)

        submitted = manager.submit(asset.id, draft.id, ws, REQUESTER)

        assert submitted.status == 'in_review'
        assert submitted.workflow_execution_id == 'exec-1'
        kwargs = review.on_request_definition_change.call_args.kwargs
        assert kwargs['entity_type'].value == 'metric_view'
        assert kwargs['entity_id'] == str(asset.id)
        assert kwargs['user_email'] == REQUESTER
        assert kwargs['entity_data']['request_id'] == str(draft.id)
        assert kwargs['entity_data']['proposed_digest'] == draft.proposed_digest
        assert audits[-1]['action'] == 'METRIC_VIEW_CHANGE_REQUEST_SUBMITTED'

    def test_a_stale_base_is_refused(self, db_session, manager, asset, ws, review):
        draft = _draft(manager, asset, ws)
        ws.tables_by_name[VIEW] = _table(BASE.replace('region', 'country'))

        with pytest.raises(ChangeRequestError) as e:
            manager.submit(asset.id, draft.id, ws, REQUESTER)

        assert _code(e) == 'metric_view_base_stale' and e.value.http_status == 409
        assert db_session.get(MetricViewChangeRequestDb, draft.id).status == 'draft'
        review.on_request_definition_change.assert_not_called()

    def test_an_owner_change_on_a_materialized_view_is_refused(self, manager, asset, ws, review):
        ws.tables_by_name[VIEW] = _table(BASE + MATERIALIZED[len(PROPOSED):])
        draft = _draft(manager, asset, ws, MATERIALIZED)
        ws.tables_by_name[VIEW] = _table(BASE + MATERIALIZED[len(PROPOSED):],
                                         owner='other@example.com')

        with pytest.raises(ChangeRequestError) as e:
            manager.submit(asset.id, draft.id, ws, REQUESTER)

        assert _code(e) == 'metric_view_owner_changed'

    def test_a_group_owner_with_materialization_is_refused(self, manager, asset, ws, review):
        ws.tables_by_name[VIEW] = _table(owner='data-engineers')
        draft = _draft(manager, asset, ws, MATERIALIZED)

        with pytest.raises(ChangeRequestError) as e:
            manager.submit(asset.id, draft.id, ws, REQUESTER)

        assert _code(e) == 'metric_view_materialized_group_owner'
        assert e.value.params == {'owner': 'data-engineers'}

    @pytest.mark.parametrize('source, kind', [
        (SimpleNamespace(row_filter=object(), columns=[]), 'row_filter'),
        (SimpleNamespace(row_filter=None, columns=[SimpleNamespace(mask=object())]),
         'column_mask'),
        (SimpleNamespace(row_filter=None, columns=[]), 'abac_policy'),
    ])
    def test_a_secured_source_of_a_materialized_view_is_refused(
        self, manager, asset, ws, review, source, kind
    ):
        ws.tables_by_name['main.sales.orders'] = source
        if kind == 'abac_policy':
            ws.policies.list_policies.return_value = iter([SimpleNamespace(name='mask_pii')])
        draft = _draft(manager, asset, ws, MATERIALIZED)

        with pytest.raises(ChangeRequestError) as e:
            manager.submit(asset.id, draft.id, ws, REQUESTER)

        assert _code(e) == 'metric_view_materialized_source_secured'
        assert e.value.params == {'source': 'main.sales.orders', 'kind': kind}

    def test_a_source_the_user_cannot_see_is_a_warning_not_a_refusal(
        self, manager, asset, ws, review
    ):
        draft = _draft(manager, asset, ws, MATERIALIZED)

        submitted = manager.submit(asset.id, draft.id, ws, REQUESTER)

        assert submitted.status == 'in_review'
        assert [(w.code, w.params) for w in submitted.warnings] == [
            ('metric_view_source_not_checked', {'source': 'main.sales.orders'}),
        ]

    def test_only_the_requester_submits_and_only_a_draft(self, manager, asset, ws, review):
        draft = _draft(manager, asset, ws)

        with pytest.raises(ChangeRequestError) as e:
            manager.submit(asset.id, draft.id, ws, 'someone@example.com')
        assert _code(e) == 'metric_view_change_request_not_requester'

        manager.submit(asset.id, draft.id, ws, REQUESTER)
        with pytest.raises(ChangeRequestError) as e:
            manager.submit(asset.id, draft.id, ws, REQUESTER)
        assert _code(e) == 'metric_view_change_request_not_draft'

    def test_without_an_approval_the_request_stays_a_draft(
        self, db_session, manager, asset, ws, review
    ):
        review.on_request_definition_change.return_value = []
        draft = _draft(manager, asset, ws)

        with pytest.raises(ChangeRequestError) as e:
            manager.submit(asset.id, draft.id, ws, REQUESTER)

        assert _code(e) == 'metric_view_change_no_approval'
        assert db_session.get(MetricViewChangeRequestDb, draft.id).status == 'draft'


class _FakeGit:
    def __init__(self, cloned=True, fail=False):
        self.is_cloned = cloned
        self.fail = fail
        self.files = {}

    def save_text(self, filename, text, subdir=None):
        if self.fail:
            return False
        self.files[f'{subdir}/{filename}'] = text
        return True


@pytest.fixture
def delivery(monkeypatch):
    """Delivery settings and the Git working copy; Manual only unless a test says so."""
    settings = SimpleNamespace(DELIVERY_MODE_INDIRECT=False, DELIVERY_MODE_MANUAL=True,
                               DELIVERY_MODE_DIRECT=False, DELIVERY_DIRECT_DRY_RUN=False)
    git = _FakeGit()
    from src.common import config
    monkeypatch.setattr(config, 'get_settings', lambda: settings)
    monkeypatch.setattr(delivery_module, 'get_settings', lambda: settings)
    monkeypatch.setattr(delivery_module, '_delivery_service',
                        DeliveryService(settings=settings, git_service=git))
    return SimpleNamespace(settings=settings, git=git)


def _in_review(db_session, manager, asset, ws):
    draft = _draft(manager, asset, ws)
    return manager.submit(asset.id, draft.id, ws, REQUESTER)


def _notifications(db_session, title_key):
    return [
        n for n in db_session.query(NotificationDb).all()
        if json.loads(n.data or '{}').get('i18n', {}).get('title') == title_key
    ]


class TestDecisionAndDelivery:
    def test_manual_delivery_sends_the_ddl_to_the_owners(
        self, db_session, manager, asset, ws, review, delivery, audits
    ):
        request = _in_review(db_session, manager, asset, ws)

        manager.on_workflow_completed(str(request.id), approved=True, responded_by=APPROVER,
                                      execution_id='exec-1')

        row = db_session.get(MetricViewChangeRequestDb, request.id)
        assert row.status == 'delivered' and row.delivery_mode == 'manual'
        assert row.decided_by == APPROVER and row.decided_at and row.delivered_at
        notes = _notifications(db_session, module.MANUAL_TITLE_KEY)
        assert [n.recipient for n in notes] == [OWNER]
        ddl = build_ddl(VIEW, PROPOSED)
        assert ddl in notes[0].description
        assert json.loads(notes[0].data)['i18n']['params'] == {'fqn': VIEW, 'ddl': ddl}
        assert [a['action'] for a in audits][-2:] == [
            'METRIC_VIEW_CHANGE_REQUEST_APPROVED', 'METRIC_VIEW_CHANGE_REQUEST_DELIVERED',
        ]
        assert audits[-1]['details']['base_digest'] == row.base_digest
        assert audits[-1]['details']['proposed_digest'] == row.proposed_digest

    def test_indirect_delivery_writes_the_yaml_and_the_ddl(
        self, db_session, manager, asset, ws, review, delivery
    ):
        delivery.settings.DELIVERY_MODE_INDIRECT = True
        delivery.settings.DELIVERY_MODE_MANUAL = False
        request = _in_review(db_session, manager, asset, ws)

        manager.on_workflow_completed(str(request.id), approved=True, responded_by=APPROVER)

        row = db_session.get(MetricViewChangeRequestDb, request.id)
        assert row.status == 'delivered' and row.delivery_mode == 'indirect'
        assert delivery.git.files == {
            'metric_views/main.sales.orders_mv.yaml': PROPOSED,
            'metric_views/main.sales.orders_mv.sql': build_ddl(VIEW, PROPOSED) + '\n',
        }
        assert row.delivery_reference == (
            'metric_views/main.sales.orders_mv.yaml, metric_views/main.sales.orders_mv.sql'
        )
        assert _notifications(db_session, module.MANUAL_TITLE_KEY) == []

    def test_direct_alone_falls_back_to_manual(
        self, db_session, manager, asset, ws, review, delivery
    ):
        delivery.settings.DELIVERY_MODE_MANUAL = False
        delivery.settings.DELIVERY_MODE_DIRECT = True
        request = _in_review(db_session, manager, asset, ws)

        manager.on_workflow_completed(str(request.id), approved=True, responded_by=APPROVER)

        assert db_session.get(MetricViewChangeRequestDb, request.id).delivery_mode == 'manual'

    @pytest.mark.parametrize('git, code', [
        (_FakeGit(cloned=False), 'metric_view_delivery_git_unavailable'),
        (_FakeGit(fail=True), 'metric_view_delivery_write_failed'),
    ])
    def test_a_failed_delivery_leaves_the_request_failed_and_the_baseline_alone(
        self, db_session, manager, asset, ws, review, delivery, audits, git, code
    ):
        delivery.settings.DELIVERY_MODE_INDIRECT = True
        delivery_module._delivery_service.set_git_service(git)
        MetricViewBaselinesManager(db_session).check(
            VIEW, parse_metric_view_definition(BASE), asset_id=asset.id)
        baseline_digest = db_session.query(MetricViewBaselineDb).one().digest
        request = _in_review(db_session, manager, asset, ws)

        manager.on_workflow_completed(str(request.id), approved=True, responded_by=APPROVER)

        row = db_session.get(MetricViewChangeRequestDb, request.id)
        assert row.status == 'failed' and row.error_code == code
        assert manager.get(asset.id, request.id).error.code == code
        # Neither the owners' notification (savepoint) nor a baseline change
        assert _notifications(db_session, module.MANUAL_TITLE_KEY) == []
        baseline = db_session.query(MetricViewBaselineDb).one()
        assert baseline.digest == baseline_digest and baseline.request_id is None
        assert [n.recipient for n in _notifications(db_session, module.FAILED_TITLE_KEY)] \
            == [REQUESTER]
        assert audits[-1]['action'] == 'METRIC_VIEW_CHANGE_REQUEST_DELIVERY_FAILED'
        assert audits[-1]['success'] is False and audits[-1]['details']['error_code'] == code

    def test_a_rejection_delivers_nothing(
        self, db_session, manager, asset, ws, review, delivery, audits
    ):
        request = _in_review(db_session, manager, asset, ws)

        manager.on_workflow_completed(str(request.id), approved=False, responded_by=APPROVER)

        row = db_session.get(MetricViewChangeRequestDb, request.id)
        assert row.status == 'rejected' and row.delivered_at is None
        assert _notifications(db_session, module.MANUAL_TITLE_KEY) == []
        assert audits[-1]['action'] == 'METRIC_VIEW_CHANGE_REQUEST_REJECTED'

    def test_the_requesters_own_approval_is_not_delivered(
        self, db_session, manager, asset, ws, review, delivery
    ):
        request = _in_review(db_session, manager, asset, ws)

        manager.on_workflow_completed(str(request.id), approved=True,
                                      responded_by=REQUESTER.upper())

        row = db_session.get(MetricViewChangeRequestDb, request.id)
        assert row.status == 'rejected' and row.error_code == 'own_change_request_approval'
        assert _notifications(db_session, module.MANUAL_TITLE_KEY) == []

    def test_a_cancelled_request_ignores_a_late_decision(
        self, db_session, manager, asset, ws, review, delivery
    ):
        request = _in_review(db_session, manager, asset, ws)
        manager.cancel(asset.id, request.id, REQUESTER)

        manager.on_workflow_completed(str(request.id), approved=True, responded_by=APPROVER)

        assert db_session.get(MetricViewChangeRequestDb, request.id).status == 'cancelled'
        assert _notifications(db_session, module.MANUAL_TITLE_KEY) == []


class TestBaselineOnReadBack:
    def test_the_delivered_definition_becomes_the_baseline_when_read_back(
        self, db_session, manager, asset, ws, review, delivery, audits
    ):
        baselines = MetricViewBaselinesManager(db_session)
        baselines.check(VIEW, parse_metric_view_definition(BASE), asset_id=asset.id)
        request = _in_review(db_session, manager, asset, ws)
        manager.on_workflow_completed(str(request.id), approved=True, responded_by=APPROVER)
        # Approved and delivered, not applied yet: the baseline hasn't moved
        assert db_session.query(MetricViewBaselineDb).one().request_id is None

        # The owner ran the DDL; Unity Catalog stores its normalized form
        stored = PROPOSED.replace('version: 1.1', 'version: "1.1"')
        baseline, drift = baselines.check(VIEW, parse_metric_view_definition(stored),
                                          asset_id=asset.id)

        row = db_session.get(MetricViewChangeRequestDb, request.id)
        assert drift.state == 'in_sync'
        assert baseline.request_id == str(request.id)
        assert baseline.approved_at == row.decided_at
        assert baseline.digest == row.proposed_digest
        assert row.applied_at is not None and row.status == 'delivered'
        assert audits[-1]['action'] == 'METRIC_VIEW_CHANGE_REQUEST_APPLIED'

    def test_another_out_of_band_definition_is_drift(
        self, db_session, manager, asset, ws, review, delivery
    ):
        baselines = MetricViewBaselinesManager(db_session)
        baselines.check(VIEW, parse_metric_view_definition(BASE), asset_id=asset.id)
        request = _in_review(db_session, manager, asset, ws)
        manager.on_workflow_completed(str(request.id), approved=True, responded_by=APPROVER)

        _, drift = baselines.check(
            VIEW, parse_metric_view_definition(BASE.replace('SUM(amount)', 'SUM(gross)')),
            asset_id=asset.id,
        )

        assert drift.state == 'drifted'
        assert db_session.get(MetricViewChangeRequestDb, request.id).applied_at is None


def test_the_delivery_service_writes_both_files_of_a_metric_view():
    git = _FakeGit()
    service = DeliveryService(settings=MagicMock(), git_service=git)

    results = service.deliver(DeliveryPayload(
        change_type=DeliveryChangeType.METRIC_VIEW_UPDATE, entity_type='MetricView',
        entity_id=VIEW, data={'fqn': VIEW, 'definition': PROPOSED, 'ddl': 'ALTER VIEW x'},
    ), modes=[DeliveryMode.INDIRECT])

    result = results.results[0]
    assert result.success
    assert result.details == {'files': ['main.sales.orders_mv.yaml', 'main.sales.orders_mv.sql'],
                              'subdir': 'metric_views'}
    assert git.files['metric_views/main.sales.orders_mv.sql'] == 'ALTER VIEW x\n'


def test_cancel_is_for_the_requester_or_an_admin(db_session, manager, asset, ws):
    draft = _draft(manager, asset, ws)

    with pytest.raises(ChangeRequestError) as e:
        manager.cancel(asset.id, draft.id, 'someone@example.com')
    assert _code(e) == 'metric_view_change_request_not_requester'

    assert manager.cancel(asset.id, draft.id, 'admin@example.com', is_admin=True).status \
        == 'cancelled'
    with pytest.raises(ChangeRequestError) as e:
        manager.cancel(asset.id, draft.id, REQUESTER)
    assert _code(e) == 'metric_view_change_request_not_cancellable'


def test_a_request_of_another_asset_is_not_found(db_session, manager, asset, ws):
    draft = _draft(manager, asset, ws)

    with pytest.raises(ChangeRequestError) as e:
        manager.get(uuid.uuid4(), draft.id)

    assert _code(e) == 'metric_view_change_request_not_found' and e.value.http_status == 404


def test_reading_as_a_user_who_cannot_see_the_view_is_not_found(manager, asset, ws):
    ws.tables.get.side_effect = PermissionDenied('no access')

    from src.controller.metric_views_manager import MetricViewNotFoundError
    with pytest.raises(MetricViewNotFoundError):
        _draft(manager, asset, ws)


class TestApprovalGuard:
    """The requester never decides their own change request, whoever the approvers are."""

    def _paused(self, db, trigger_type, approvers='Admin', requester=REQUESTER):
        from src.db_models.process_workflows import (
            ProcessWorkflowDb, WorkflowExecutionDb, WorkflowStepDb,
        )
        workflow = ProcessWorkflowDb(
            id=str(uuid.uuid4()), name=f'wf-{uuid.uuid4().hex[:6]}',
            trigger_config=json.dumps({'type': trigger_type}),
        )
        db.add(workflow)
        db.flush()
        db.add(WorkflowStepDb(
            id=str(uuid.uuid4()), workflow_id=workflow.id, step_id='approve',
            step_type='approval', config=json.dumps({'approvers': approvers}), order=0,
        ))
        execution = WorkflowExecutionDb(
            id=str(uuid.uuid4()), workflow_id=workflow.id, status='paused',
            current_step_id='approve',
            trigger_context=json.dumps({'user_email': requester, 'entity_type': 'metric_view'}),
        )
        db.add(execution)
        db.add(NotificationDb(
            id=str(uuid.uuid4()), type='action_required', title='Approval Required',
            recipient='Admin', action_type='workflow_approval',
            action_payload=json.dumps({'execution_id': execution.id, 'step_id': 'approve'}),
        ))
        db.flush()
        return execution

    def _authorize(self, db, execution, email):
        from fastapi import HTTPException
        from src.models.users import UserInfo
        from src.routes import workflows_routes

        notifications = MagicMock()
        notifications.can_user_access_notification.return_value = True
        try:
            workflows_routes._assert_caller_authorized_for_execution(
                db=db, notifications_manager=notifications, execution_id=execution.id,
                user_info=UserInfo(email=email, username=email, user=email, ip='127.0.0.1',
                                   groups=['admins']),
            )
            return None
        except HTTPException as e:
            return e

    def test_the_requester_is_refused_even_on_an_admin_approval(self, db_session):
        execution = self._paused(db_session, 'on_request_definition_change')

        refused = self._authorize(db_session, execution, REQUESTER.upper())

        assert refused.status_code == 403
        assert refused.detail['code'] == 'own_change_request_approval'
        assert self._authorize(db_session, execution, APPROVER) is None

    def test_other_triggers_keep_their_rules(self, db_session):
        execution = self._paused(db_session, 'on_request_review')

        assert self._authorize(db_session, execution, REQUESTER) is None

    def test_asset_owner_approvers_are_the_owners_but_the_requester(self, db_session, asset):
        from src.common.workflow_executor import _resolve_role_to_users

        context = SimpleNamespace(
            entity={}, entity_type='metric_view', entity_id=str(asset.id),
            trigger_context=SimpleNamespace(user_email=REQUESTER), user_email=REQUESTER,
        )
        assert _resolve_role_to_users(db_session, 'AssetOwner', context) == [(OWNER, None)]

        context.trigger_context.user_email = OWNER
        resolved = _resolve_role_to_users(db_session, 'AssetOwner', context)
        assert (OWNER, None) not in resolved
