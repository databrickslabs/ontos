"""Maturity levels for table and view assets (#1316).

The asset entity dict combines the asset's Ontos fields with the column fields
of the Unity Catalog table it points to (one ``tables.get`` per evaluation).
When the table can't be read the UC fields stay absent and the gates that use
them say why with a code.
"""
import json
import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

import pytest
from databricks.sdk.errors import NotFound, PermissionDenied
from databricks.sdk.service.catalog import ColumnInfo, TableInfo

from src.common.compliance_dsl import evaluate_rule_on_object
from src.controller.entity_dict_builder import (
    UC_TABLE_FIELDS,
    UnsupportedMaturityAssetTypeError,
    build_asset_dict,
    uc_table_name,
)
from src.controller.maturity_evaluator import (
    MaturityEvaluator,
    evaluate_asset_maturity_on_change,
)
from src.db_models.assets import AssetDb, AssetTypeDb
from src.db_models.business_owners import BusinessOwnerDb
from src.db_models.business_roles import BusinessRoleDb
from src.db_models.compliance import CompliancePolicyDb
from src.db_models.data_domains import DataDomain
from src.db_models.domain_associations import EntityDomainAssociationDb
from src.db_models.entity_relationships import EntityRelationshipDb
from src.db_models.maturity import MaturitySnapshotDb
from src.db_models.quality import QualityItemDb
from src.db_models.semantic_links import EntitySemanticLinkDb
from src.db_models.tags import EntityTagAssociationDb, TagDb, TagNamespaceDb
from src.models.process_workflows import EntityType
from src.repositories.maturity_repository import maturity_repo

FQN = 'main.sales.orders'


def _type(db, name):
    existing = db.query(AssetTypeDb).filter_by(name=name).first()
    if existing:
        return existing
    asset_type = AssetTypeDb(id=uuid.uuid4(), name=name)
    db.add(asset_type)
    db.flush()
    return asset_type


def _asset(db, type_name='Table', *, platform='databricks', location=FQN, **fields):
    asset = AssetDb(
        id=uuid.uuid4(), name=fields.pop('name', 'orders'),
        asset_type_id=_type(db, type_name).id, platform=platform, location=location,
        status='active', **fields,
    )
    db.add(asset)
    db.flush()
    return asset


def _table(columns):
    return TableInfo(full_name=FQN, columns=[
        ColumnInfo(name=name, comment=comment, type_text='string') for name, comment in columns
    ])


def _ws(table=None, error=None):
    ws = MagicMock()
    if error is not None:
        ws.tables.get.side_effect = error
    else:
        ws.tables.get.return_value = table
    return ws


def _level(db, order, name, rules, entity_type='Asset'):
    level = maturity_repo.create(db, name=name, level_order=order, entity_type=entity_type)
    for idx, rule in enumerate(rules):
        policy = CompliancePolicyDb(
            id=str(uuid.uuid4()), name=f'{name} gate {idx}', rule=rule, is_active=True,
        )
        db.add(policy)
        db.flush()
        maturity_repo.add_gate(db, maturity_level_id=level.id,
                               compliance_policy_id=policy.id, display_order=idx)
    db.flush()
    db.refresh(level)
    return level


# --- uc_table_name -----------------------------------------------------------

@pytest.mark.parametrize('platform,location,expected', [
    ('databricks', 'main.sales.orders', 'main.sales.orders'),
    ('Databricks', 'main.sales.orders', 'main.sales.orders'),
    ('Unity Catalog', 'main.sales.orders', 'main.sales.orders'),
    ('Snowflake', 'main.sales.orders', None),
    ('databricks', 'main.sales', None),
    ('databricks', 's3://bucket/path.parquet', None),
    ('databricks', None, None),
    (None, 'main.sales.orders', None),
])
def test_uc_table_name_needs_databricks_and_a_three_part_name(platform, location, expected):
    assert uc_table_name(platform, location) == expected


# --- build_asset_dict --------------------------------------------------------

def test_builder_has_the_asset_ontos_fields(db_session):
    expires = datetime.now(timezone.utc) + timedelta(days=30)
    asset = _asset(
        db_session, description='Orders placed in the shop',
        properties={'tier': 'gold', 'retention days': 30, 'source_path': FQN},
        tags=['pii'], certification_level=2, certification_expires_at=expires,
        certified_at=datetime.now(timezone.utc),
    )
    asset_id = str(asset.id)
    role = BusinessRoleDb(id=uuid.uuid4(), name=f'Owner {uuid.uuid4().hex[:6]}')
    domain = DataDomain(id=str(uuid.uuid4()), name=f'Sales {uuid.uuid4().hex[:6]}',
                        created_by='admin@example.com')
    db_session.add_all([role, domain])
    db_session.flush()
    db_session.add_all([
        BusinessOwnerDb(object_type='asset', object_id=asset_id, user_email='a@example.com',
                        role_id=role.id, is_active=True),
        BusinessOwnerDb(object_type='asset', object_id=asset_id, user_email='gone@example.com',
                        role_id=role.id, is_active=False),
        EntityDomainAssociationDb(domain_id=domain.id, entity_type='asset',
                                  entity_id=asset_id, is_primary=True),
        EntityRelationshipDb(source_type='Table', source_id=asset_id,
                             target_type='BusinessTerm', target_id=str(uuid.uuid4()),
                             relationship_type='hasTerm'),
        EntitySemanticLinkDb(entity_type='asset', entity_id=asset_id,
                             iri='urn:glossary:order'),
        QualityItemDb(entity_type='asset', entity_id=asset_id, dimension='completeness',
                      source='manual', score_percent=99.0),
    ])
    db_session.flush()

    d = build_asset_dict(db_session, asset_id)

    assert d['entity_type'] == 'Asset' and d['asset_type'] == 'Table'
    assert d['id'] == asset_id and d['name'] == 'orders'
    assert d['has_description'] is True and d['status'] == 'active'
    assert d['owners'] == ['a@example.com'] and d['owner_count'] == 1 and d['has_owner']
    assert d['domain_id'] == domain.id and d['domain_name'] == domain.name
    assert d['domain_count'] == 1 and d['has_domain']
    assert d['certification_level'] == 2 and d['is_certified']
    assert d['effective_certification'] == 2
    assert d['certification_expires_at'] is not None and d['certified_at'] is not None
    assert d['is_certification_expired'] is False
    assert d['properties']['tier'] == 'gold' and d['property_count'] == 3
    # One level of property access in rules: obj.prop_tier
    assert d['prop_tier'] == 'gold' and 'prop_retention days' not in d
    assert d['business_term_count'] == 1 and d['has_business_terms']
    assert d['semantic_link_count'] == 1 and d['has_semantic_links']
    assert d['tag_count'] == 1 and d['has_tags']
    assert d['quality_check_count'] == 1 and d['has_quality_checks']


def test_builder_reads_assigned_asset_tags(db_session):
    # 'tier' is also assigned below: counted once, with the assigned value
    asset = _asset(db_session, tags=['pii', 'tier'])
    ns = TagNamespaceDb(name=f'gov-{uuid.uuid4().hex[:8]}')
    db_session.add(ns)
    db_session.flush()
    tag = TagDb(name='tier', namespace_id=ns.id, status='active')
    db_session.add(tag)
    db_session.flush()
    db_session.add(EntityTagAssociationDb(
        tag_id=tag.id, entity_id=str(asset.id), entity_type='asset', assigned_value='gold',
    ))
    db_session.flush()

    d = build_asset_dict(db_session, str(asset.id))

    assert d['tags']['tier'] == 'gold' and d['tags']['pii'] is True
    assert d['tag_count'] == 2 and d['has_tags']
    assert evaluate_rule_on_object("ASSERT HAS_TAG('tier')", d)[0] is True
    assert evaluate_rule_on_object("ASSERT HAS_TAG('pii')", d)[0] is True
    assert evaluate_rule_on_object("ASSERT HAS_TAG('missing')", d)[0] is False


def test_builder_without_owner_domain_or_certification(db_session):
    asset = _asset(db_session, platform=None, location=None,
                   certification_expires_at=datetime.now(timezone.utc) - timedelta(days=1))

    d = build_asset_dict(db_session, str(asset.id), get_workspace_client=lambda: _ws())

    assert d['has_owner'] is False and d['owner'] is None and d['owners'] == []
    assert d['has_domain'] is False and d['domain_id'] is None
    assert d['certification_level'] == 0 and d['is_certified'] is False
    assert d['is_certification_expired'] is True
    assert d['has_description'] is False and d['property_count'] == 0
    # Not UC-backed: no table read, no UC fields, no status
    assert d['uc_table_name'] is None and d['uc_table_status'] is None
    assert not UC_TABLE_FIELDS & d.keys()


def test_builder_merges_the_uc_table_column_fields(db_session):
    asset = _asset(db_session)
    ws = _ws(_table([('id', 'Order id'), ('amount', None)]))

    d = build_asset_dict(db_session, str(asset.id), get_workspace_client=lambda: ws)

    ws.tables.get.assert_called_once_with(full_name=FQN)
    assert d['uc_table_status'] == 'read' and d['uc_fields_available'] is True
    assert d['column_count'] == 2 and d['columns_without_comment_count'] == 1
    assert d['column_comment_ratio'] == 0.5
    assert [c['name'] for c in d['columns']] == ['id', 'amount']


@pytest.mark.parametrize('error,status', [
    (NotFound('Table does not exist: main.sales.orders'), 'not_found'),
    (PermissionDenied('User does not have SELECT on secret_catalog'), 'permission_denied'),
    (RuntimeError('connection reset by 10.0.0.12'), 'read_failed'),
])
def test_unreadable_table_leaves_uc_fields_absent(db_session, error, status):
    asset = _asset(db_session)

    d = build_asset_dict(db_session, str(asset.id), get_workspace_client=lambda: _ws(error=error))

    assert d['uc_table_status'] == status and d['uc_fields_available'] is False
    assert not UC_TABLE_FIELDS & d.keys()
    # The exception text isn't kept anywhere in the dict
    assert str(error) not in json.dumps(d, default=str)


@pytest.mark.parametrize('provider', [None, lambda: None])
def test_no_workspace_client_leaves_uc_fields_absent(db_session, provider):
    asset = _asset(db_session)

    d = build_asset_dict(db_session, str(asset.id), get_workspace_client=provider)

    assert d['uc_table_status'] == 'client_unavailable'
    assert not UC_TABLE_FIELDS & d.keys()


def test_workspace_client_that_fails_to_build_is_unavailable(db_session):
    asset = _asset(db_session)

    def broken():
        raise RuntimeError('no credentials')

    d = build_asset_dict(db_session, str(asset.id), get_workspace_client=broken)

    assert d['uc_table_status'] == 'client_unavailable'


@pytest.mark.parametrize('type_name', ['Dashboard', 'Column', 'Business Term'])
def test_other_asset_types_are_refused_with_a_code(db_session, type_name):
    asset = _asset(db_session, type_name)

    with pytest.raises(UnsupportedMaturityAssetTypeError) as exc:
        build_asset_dict(db_session, str(asset.id))

    assert exc.value.code == 'maturity_asset_type_unsupported'
    assert exc.value.params == {'assetType': type_name}


def test_unknown_or_malformed_asset_id_is_not_found(db_session):
    assert build_asset_dict(db_session, str(uuid.uuid4())) is None
    assert build_asset_dict(db_session, 'not-a-uuid') is None


# --- evaluation --------------------------------------------------------------

def test_gates_are_evaluated_on_a_view_asset(db_session):
    asset = _asset(db_session, 'View', description='All orders')
    _level(db_session, 1, 'Described', ['ASSERT obj.has_description = True'])
    _level(db_session, 2, 'Documented columns', ['ASSERT obj.column_comment_ratio >= 0.8'])
    _level(db_session, 3, 'Certified', ['ASSERT obj.is_certified = True'])
    ws = _ws(_table([('id', 'Order id'), ('amount', 'Amount')]))

    report = MaturityEvaluator(ws).evaluate(
        db_session, entity_type='Asset', entity_id=str(asset.id), persist=False,
    )

    assert report.achieved_level_order == 2 and report.achieved_level_name == 'Documented columns'
    assert [lv.achieved for lv in report.levels] == [True, True, False]
    assert report.notices == []
    assert report.levels[2].gates[0].message_code is None


def test_shared_all_levels_do_not_apply_to_assets(db_session):
    asset = _asset(db_session)
    _level(db_session, 1, 'Has contract', ['ASSERT obj.has_contract = True'], entity_type='all')
    _level(db_session, 1, 'Described', ['ASSERT obj.name != \'\''])

    report = MaturityEvaluator(_ws(_table([]))).evaluate(
        db_session, entity_type='Asset', entity_id=str(asset.id), persist=False,
    )

    assert [lv.level_name for lv in report.levels] == ['Described']
    assert report.total_levels == 1 and report.achieved_level_order == 1
    # Products keep seeing the shared levels
    names = [lv.name for lv in maturity_repo.get_all_ordered(db_session, entity_type='DataProduct')]
    assert names == ['Has contract']


def test_gate_on_uc_fields_says_the_table_could_not_be_read(db_session):
    asset = _asset(db_session)
    _level(db_session, 1, 'Owned', ['ASSERT obj.name != \'\''])
    _level(db_session, 2, 'Documented', [
        'ASSERT obj.column_count > 0',
        'ASSERT obj.has_owner = True',
    ])
    error = PermissionDenied('User lacks USE CATALOG on main')

    report = MaturityEvaluator(_ws(error=error)).evaluate(
        db_session, entity_type='Asset', entity_id=str(asset.id), persist=False,
    )

    uc_gate, owner_gate = report.levels[1].gates
    assert uc_gate.passed is False
    assert uc_gate.message_code == 'maturity_uc_table_permission_denied'
    assert uc_gate.message_params == {'tableName': FQN}
    assert str(error) not in (uc_gate.message or '')
    # A failed gate that doesn't use UC fields keeps its own message
    assert owner_gate.passed is False and owner_gate.message_code is None
    assert [n.code for n in report.notices] == ['maturity_uc_table_permission_denied']
    assert str(error) not in report.model_dump_json()
    # Nothing is stored from a read that failed (see the tests below)
    assert db_session.query(MaturitySnapshotDb).filter_by(entity_id=str(asset.id)).count() == 0


# --- a UC read failure never lowers the stored level -------------------------

def _ladder_with_a_uc_gate(db):
    _level(db, 1, 'Named', ["ASSERT obj.name != ''"])
    _level(db, 2, 'Has columns', ['ASSERT obj.column_count > 0'])


@pytest.mark.parametrize('error', [
    PermissionDenied('User does not have SELECT on main.sales.orders'),
    NotFound('Table does not exist'),
    RuntimeError('connection reset by 10.0.0.12'),
])
def test_uc_read_failure_keeps_the_stored_level(db_session, error):
    asset = _asset(db_session)
    _ladder_with_a_uc_gate(db_session)
    eid = str(asset.id)

    with patch('src.common.workflow_triggers.TriggerRegistry') as registry:
        MaturityEvaluator(_ws(_table([('id', 'Order id')]))).evaluate(
            db_session, entity_type='Asset', entity_id=eid, persist=True,
        )
        events_before = registry.return_value.on_maturity_change.call_count

        report = MaturityEvaluator(_ws(error=error)).evaluate(
            db_session, entity_type='Asset', entity_id=eid, persist=True,
        )

        assert registry.return_value.on_maturity_change.call_count == events_before

    # The response keeps the stored level and says why the fields are missing
    assert report.achieved_level_order == 2 and report.achieved_level_name == 'Has columns'
    assert report.notices and report.notices[0].code.startswith('maturity_uc_table_')
    # No snapshot, no event: the history still ends at level 2
    snapshots = db_session.query(MaturitySnapshotDb).filter_by(entity_id=eid).all()
    assert [s.achieved_level_order for s in snapshots] == [2]


def test_uc_read_failure_before_any_level_stores_nothing(db_session):
    asset = _asset(db_session)
    _ladder_with_a_uc_gate(db_session)

    with patch('src.common.workflow_triggers.TriggerRegistry') as registry:
        report = MaturityEvaluator(_ws(error=NotFound('gone'))).evaluate(
            db_session, entity_type='Asset', entity_id=str(asset.id), persist=True,
        )

    assert report.achieved_level_order is None
    assert db_session.query(MaturitySnapshotDb).filter_by(entity_id=str(asset.id)).count() == 0
    assert not registry.return_value.on_maturity_change.called


def test_level_is_stored_again_once_the_table_reads(db_session):
    asset = _asset(db_session)
    _ladder_with_a_uc_gate(db_session)
    eid = str(asset.id)
    MaturityEvaluator(_ws(_table([('id', 'Order id')]))).evaluate(
        db_session, entity_type='Asset', entity_id=eid, persist=True,
    )
    MaturityEvaluator(_ws(error=RuntimeError('timeout'))).evaluate(
        db_session, entity_type='Asset', entity_id=eid, persist=True,
    )

    report = MaturityEvaluator(_ws(_table([('id', 'Order id')]))).evaluate(
        db_session, entity_type='Asset', entity_id=eid, persist=True,
    )

    assert report.achieved_level_order == 2 and report.notices == []
    snapshots = db_session.query(MaturitySnapshotDb).filter_by(entity_id=eid).all()
    assert [s.achieved_level_order for s in snapshots] == [2, 2]


def test_asset_level_change_fires_on_maturity_change_as_table(db_session):
    asset = _asset(db_session)
    _level(db_session, 1, 'Named', ['ASSERT obj.name != \'\''])

    with patch('src.common.workflow_triggers.TriggerRegistry') as registry:
        MaturityEvaluator(_ws(_table([]))).evaluate(
            db_session, entity_type='Asset', entity_id=str(asset.id), persist=True,
            evaluated_by='owner@example.com',
        )

    kwargs = registry.return_value.on_maturity_change.call_args.kwargs
    assert kwargs['entity_type'] == EntityType.TABLE
    # Same convention as the self-service table events: the UC full name
    assert kwargs['entity_id'] == FQN
    assert kwargs['entity_data']['asset_id'] == str(asset.id)
    assert kwargs['from_level'] is None and kwargs['to_level'] == 1
    assert kwargs['entity_data']['uc_table_name'] == FQN
    assert kwargs['user_email'] == 'owner@example.com'


def test_asset_without_uc_name_fires_with_the_asset_id(db_session):
    asset = _asset(db_session, 'View', platform=None, location=None)
    _level(db_session, 1, 'Named', ['ASSERT obj.name != \'\''])

    with patch('src.common.workflow_triggers.TriggerRegistry') as registry:
        MaturityEvaluator(_ws()).evaluate(
            db_session, entity_type='Asset', entity_id=str(asset.id), persist=True,
        )

    kwargs = registry.return_value.on_maturity_change.call_args.kwargs
    assert kwargs['entity_type'] == EntityType.VIEW
    assert kwargs['entity_id'] == str(asset.id)
    assert kwargs['entity_data']['asset_id'] == str(asset.id)
    assert kwargs['entity_data']['uc_table_name'] is None


def test_unreadable_table_still_fires_with_its_uc_name(db_session):
    asset = _asset(db_session)
    _level(db_session, 1, 'Named', ['ASSERT obj.name != \'\''])

    with patch('src.common.workflow_triggers.TriggerRegistry') as registry:
        MaturityEvaluator(_ws(error=NotFound('gone'))).evaluate(
            db_session, entity_type='Asset', entity_id=str(asset.id), persist=True,
        )

    assert registry.return_value.on_maturity_change.call_args.kwargs['entity_id'] == FQN


# --- gate errors -------------------------------------------------------------

SECRET = 'LENGTH expects 1 argument'


@pytest.mark.parametrize('rule', [
    'ASSERT LENGTH(obj.name, obj.status) > 0',  # raises while it is evaluated
    'ASSERT obj.name ==== (',  # can't be parsed
    'obj.name != ""',  # no ASSERT
])
def test_gate_error_is_coded_and_keeps_the_exception_out(db_session, rule, caplog):
    asset = _asset(db_session)
    _level(db_session, 1, 'Broken', [rule])

    with caplog.at_level('ERROR', logger='src.controller.maturity_evaluator'):
        report = MaturityEvaluator(_ws(_table([]))).evaluate(
            db_session, entity_type='Asset', entity_id=str(asset.id), persist=True,
        )

    gate = report.levels[0].gates[0]
    assert gate.passed is False
    assert gate.message_code == 'maturity_gate_error'
    assert gate.message_params == {'gateName': 'Broken gate 0'}
    assert gate.message == 'Gate Broken gate 0 could not be evaluated.'
    assert report.achieved_level_order is None
    snapshot = db_session.query(MaturitySnapshotDb).filter_by(entity_id=str(asset.id)).one()
    stored = json.loads(snapshot.gate_results_json)[0]
    assert stored['message_code'] == 'maturity_gate_error'
    assert stored['message_params'] == {'gateName': 'Broken gate 0'}
    for text in (snapshot.gate_results_json, report.model_dump_json()):
        assert SECRET not in text and 'DSL evaluation error' not in text
        assert 'Evaluation error' not in text and 'Unexpected token' not in text
    # The error is in the server log
    assert any('could not be evaluated: ' in r.getMessage() for r in caplog.records)


def test_gate_error_on_a_product_is_coded_too(db_session):
    from src.db_models.data_products import DataProductDb

    product_id = str(uuid.uuid4())
    db_session.add(DataProductDb(id=product_id, name='p', status='draft',
                                 version_family_id=product_id))
    db_session.flush()
    _level(db_session, 1, 'Broken', ['ASSERT LENGTH(obj.name, obj.status) > 0'],
           entity_type='DataProduct')

    report = MaturityEvaluator(_ws()).evaluate(
        db_session, entity_type='DataProduct', entity_id=product_id, persist=False,
    )

    gate = report.levels[0].gates[0]
    assert gate.message_code == 'maturity_gate_error' and SECRET not in (gate.message or '')


def test_a_failed_assertion_keeps_its_message(db_session):
    asset = _asset(db_session)
    _level(db_session, 1, 'Certified', ['ASSERT obj.is_certified = True'])

    report = MaturityEvaluator(_ws(_table([]))).evaluate(
        db_session, entity_type='Asset', entity_id=str(asset.id), persist=False,
    )

    gate = report.levels[0].gates[0]
    assert gate.message == 'Assertion failed: obj.is_certified = True'
    assert gate.message_code is None


# --- snapshot counts per entity type -------------------------------------------

def _snapshot(db, entity_type, order):
    maturity_repo.create_snapshot(
        db, entity_type=entity_type, entity_id=str(uuid.uuid4()),
        achieved_level_order=order, achieved_level_name='x',
    )


def test_asset_snapshots_do_not_count_for_product_or_shared_levels(db_session):
    _snapshot(db_session, 'Asset', 2)

    assert maturity_repo.count_snapshots_for_level(db_session, 2, 'Asset') == 1
    assert maturity_repo.count_snapshots_for_level(db_session, 2, 'DataProduct') == 0
    assert maturity_repo.count_snapshots_for_level(db_session, 2, 'DataContract') == 0
    assert maturity_repo.count_snapshots_for_level(db_session, 2, 'all') == 0


def test_product_and_contract_snapshots_do_not_count_for_asset_levels(db_session):
    _snapshot(db_session, 'DataProduct', 3)
    _snapshot(db_session, 'DataContract', 3)

    assert maturity_repo.count_snapshots_for_level(db_session, 3, 'Asset') == 0
    assert maturity_repo.count_snapshots_for_level(db_session, 3, 'DataProduct') == 1
    assert maturity_repo.count_snapshots_for_level(db_session, 3, 'DataContract') == 1
    # A shared level covers products and contracts
    assert maturity_repo.count_snapshots_for_level(db_session, 3, 'all') == 2
    assert maturity_repo.count_snapshots_for_level(db_session, 4, 'all') == 0


def test_unsupported_asset_type_propagates_from_the_evaluator(db_session):
    asset = _asset(db_session, 'Dashboard', platform=None, location=None)

    with pytest.raises(UnsupportedMaturityAssetTypeError):
        MaturityEvaluator(_ws()).evaluate(
            db_session, entity_type='Asset', entity_id=str(asset.id),
        )


# --- on change -----------------------------------------------------------------

@pytest.fixture
def same_session(db_session):
    """``get_db_session`` yields the test session (the on-change task opens its own)."""
    from contextlib import contextmanager

    @contextmanager
    def _session():
        yield db_session

    with patch('src.common.database.get_db_session', _session):
        yield db_session


def test_on_change_skips_without_asset_levels(same_session):
    asset = _asset(same_session)
    ws = _ws(_table([]))

    assert evaluate_asset_maturity_on_change(str(asset.id), workspace_client=ws) is None
    ws.tables.get.assert_not_called()


def test_on_change_skips_other_asset_types(same_session):
    asset = _asset(same_session, 'Dashboard')
    _level(same_session, 1, 'Named', ['ASSERT obj.name != \'\''])

    assert evaluate_asset_maturity_on_change(str(asset.id), workspace_client=_ws()) is None


def test_on_change_evaluates_and_stores_a_snapshot(same_session):
    asset = _asset(same_session)
    _level(same_session, 1, 'Named', ['ASSERT obj.name != \'\''])

    report = evaluate_asset_maturity_on_change(
        str(asset.id), evaluated_by='me@example.com', workspace_client=_ws(_table([])),
    )

    assert report.achieved_level_order == 1
    snapshot = same_session.query(MaturitySnapshotDb).filter_by(entity_id=str(asset.id)).one()
    assert snapshot.entity_type == 'Asset' and snapshot.evaluated_by == 'me@example.com'


def test_on_change_never_raises(same_session):
    with patch('src.controller.maturity_evaluator.maturity_repo.get_all_ordered',
               side_effect=RuntimeError('db down')):
        assert evaluate_asset_maturity_on_change(str(uuid.uuid4())) is None
