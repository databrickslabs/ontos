"""MATCH types ignore case and underscores; a run that matches nothing warns (#1150 A and B).

B: ``MATCH (p:DataProduct)`` was lowercased to ``dataproduct``, which no loader
handles, so the rule matched nothing while ``data_product`` worked (one-word
types such as ``Table`` were already lowercased to a known type). Known types
are now matched ignoring case and underscores; unknown types stay unknown.

A: a run whose rule selects no entity ended as a plain ``succeeded`` run with
0 results and a 0 % score, and nothing said why. It still succeeds (it is not
a failure of the run, and the job does not exit 1 for it), with the coded
warning ``no_entities_matched`` that the UI translates.
"""
import os

os.environ['TESTING'] = 'true'
os.environ['SKIP_STARTUP_TASKS'] = 'true'

import uuid
from types import SimpleNamespace
from unittest.mock import patch

import pytest

import src.workflows.compliance_checks.compliance_checks as job
from src.common import compliance_entities
from src.common.compliance_entities import (
    AppEntityLoader,
    UnityCatalogLoader,
    normalize_match_type,
    parse_entity_filter,
    validate_rule,
)
from src.controller.compliance_manager import ComplianceManager
from src.db_models.compliance import CompliancePolicyDb, ComplianceResultDb
from src.db_models.data_asset_reviews import DataAssetReviewRequestDb
from src.db_models.data_products import DataProductDb
from src.routes import compliance_routes

NO_CLIENT = 'src.common.workspace_client.get_workspace_client'

# --- B: MATCH type normalization -------------------------------------------

SPELLINGS = [
    ('DataProduct', 'data_product'),
    ('dataProduct', 'data_product'),
    ('DATA_PRODUCT', 'data_product'),
    ('Data_Product', 'data_product'),
    ('data_product', 'data_product'),
    ('dataproduct', 'data_product'),
    ('DataContract', 'data_contract'),
    ('Domain', 'domain'),
    ('Review', 'review'),
    ('Table', 'table'),
    ('VIEW', 'view'),
    ('Catalog', 'catalog'),
    ('Volume', 'volume'),
]


@pytest.mark.parametrize('written,canonical', SPELLINGS)
def test_known_types_are_matched_ignoring_case_and_underscores(written, canonical):
    assert normalize_match_type(written) == canonical
    rule = f"MATCH (x:{written}) ASSERT x.name != ''"
    assert parse_entity_filter(rule).entity_types == [canonical]


@pytest.mark.parametrize('written', ['Dataset', 'Product', 'GlossaryTerm', 'glossary_term'])
def test_unknown_types_stay_unknown(written):
    # Only the spelling of a loaded type is normalized (and data_asset_review, below)
    entity_types = parse_entity_filter(f"MATCH (x:{written}) ASSERT x.name != ''").entity_types
    known = UnityCatalogLoader.SUPPORTED_TYPES + AppEntityLoader.SUPPORTED_TYPES
    assert entity_types == [written.lower()]
    assert not set(entity_types) & set(known)


@pytest.mark.parametrize('written', ['Object', 'object', 'OBJECT'])
def test_object_still_means_every_type(written):
    entity_types = parse_entity_filter(f"MATCH (o:{written}) ASSERT o.name != ''").entity_types
    assert 'data_product' in entity_types and 'table' in entity_types


def test_the_validator_accepts_a_camel_case_type():
    assert validate_rule("MATCH (p:DataProduct) ASSERT p.status = 'active'") == []


def test_the_validator_still_flags_an_unknown_type_as_written():
    [warning] = validate_rule("MATCH (d:Dataset) ASSERT d.name != ''")
    assert warning['code'] == 'unsupported_match_type'
    assert warning['params']['type'] == 'Dataset'


def test_no_two_known_types_share_a_key():
    # Types are looked up ignoring case and underscores: two loaded types with the same
    # key would make one of them unreachable
    known = UnityCatalogLoader.SUPPORTED_TYPES + AppEntityLoader.SUPPORTED_TYPES
    assert len(compliance_entities._LOADED_TYPES_BY_KEY) == len(known)
    # and an alias doesn't hide a loaded type
    aliases = {compliance_entities._type_key(a) for a in compliance_entities._TYPE_ALIASES}
    assert not aliases & set(compliance_entities._LOADED_TYPES_BY_KEY)


@pytest.mark.parametrize('written', ['data_asset_review', 'DataAssetReview'])
def test_the_workflow_name_of_reviews_names_reviews(written):
    # Workflows call the type data_asset_review; runs and gates resolve it the same way
    assert normalize_match_type(written) == 'review'
    assert validate_rule(f"MATCH (r:{written}) ASSERT r.status = 'approved'") == []


@pytest.fixture
def product(db_session):
    product = DataProductDb(
        id=str(uuid.uuid4()), api_version='v1.0.0', kind='DataProduct',
        status='draft', name=f'p-{uuid.uuid4().hex[:8]}', version='1.0.0',
    )
    db_session.add(product)
    db_session.flush()
    return product


def _run(db, rule):
    policy = CompliancePolicyDb(
        id=str(uuid.uuid4()), name=f'policy-{uuid.uuid4().hex[:8]}', rule=rule,
        category='Governance', severity='low', is_active=True,
    )
    db.add(policy)
    db.flush()
    with patch(NO_CLIENT, return_value=None):
        run = ComplianceManager().run_policy_inline(db, policy=policy)
    results = db.query(ComplianceResultDb).filter(ComplianceResultDb.run_id == run.id).all()
    return run, {r.object_id: r for r in results}


def test_a_camel_case_rule_evaluates_and_fires_its_on_fail(db_session, product):
    rule = (
        f"MATCH (p:DataProduct) WHERE p.name = '{product.name}' "
        "ASSERT p.status = 'active' ON_FAIL FAIL 'Product is not active'"
    )

    run, results = _run(db_session, rule)

    assert run.status == 'succeeded'
    assert (run.success_count, run.failure_count) == (0, 1)
    assert results[product.id].passed is False
    assert results[product.id].message == 'Product is not active'
    assert compliance_routes._run_codes(run)['warning_code'] is None


def test_a_run_on_the_workflow_name_of_reviews_evaluates_reviews(db_session):
    review = DataAssetReviewRequestDb(
        requester_email='r@example.com', reviewer_email='s@example.com', status='queued',
    )
    db_session.add(review)
    db_session.flush()

    run, results = _run(db_session, "MATCH (r:data_asset_review) ASSERT r.status = 'approved'")

    assert results[review.id].passed is False
    assert compliance_routes._run_codes(run)['warning_code'] is None


# --- A: a run that matches no entities ---------------------------------------

EMPTY_RULES = {
    'unknown_type': "MATCH (d:Dataset) ASSERT d.name != ''",
    'where_selects_nothing': "MATCH (p:data_product) WHERE p.name = 'no-such-product-1150' "
                             "ASSERT p.status = 'active'",
    'no_match_clause': "ASSERT obj.status = 'active'",
}


@pytest.mark.parametrize('rule', EMPTY_RULES.values(), ids=EMPTY_RULES.keys())
def test_a_run_that_matches_nothing_succeeds_with_a_warning(db_session, rule):
    run, results = _run(db_session, rule)

    assert results == {}
    assert run.status == 'succeeded'
    assert run.error_message is None
    assert compliance_routes._run_codes(run) == {
        'error_code': None, 'error_params': None,
        'warning_code': 'no_entities_matched', 'warning_params': None,
    }


def test_a_run_with_results_has_no_warning(db_session, product):
    run, results = _run(db_session, f"MATCH (p:data_product) WHERE p.name = '{product.name}' "
                                    "ASSERT p.status = 'draft'")

    assert results[product.id].passed is True
    assert run.error_code is None
    assert compliance_routes._run_codes(run)['warning_code'] is None


def test_trailing_input_is_the_warning_when_both_apply(db_session):
    # The tail of the rule is ignored: that is what the author must fix first
    run, _ = _run(db_session, "MATCH (d:Dataset) ASSERT d.name = 'x' IS NOT NULL")

    assert compliance_routes._run_codes(run)['warning_code'] == 'rule_trailing_input'


def test_a_run_that_cannot_load_its_entities_still_fails(db_session):
    with patch.object(AppEntityLoader, 'load_entities', side_effect=_load_failed):
        run, _ = _run(db_session, "MATCH (p:data_product) ASSERT p.status = 'active'")

    assert run.status == 'failed'
    assert compliance_routes._run_codes(run)['warning_code'] is None


def _load_failed(*_args, **_kwargs):
    from src.common.compliance_entities import EntityLoadError

    error = EntityLoadError('Could not load the data_product entities')
    error.error_code, error.error_params = 'entities_load_failed', {'entityType': 'data_product'}
    raise error


# --- A: the compliance-checks job --------------------------------------------

def test_the_job_shows_the_warning_of_an_empty_run(db_session, capsys):
    policy = CompliancePolicyDb(
        id=str(uuid.uuid4()), name='Datasets described', rule=EMPTY_RULES['unknown_type'],
        category='Governance', severity='low', is_active=True,
    )
    db_session.add(policy)
    db_session.flush()

    with patch(NO_CLIENT, return_value=None):
        result = job.run_policy(
            db_session, {'id': policy.id, 'name': policy.name}, ComplianceManager(), None,
        )

    assert result['status'] == 'succeeded'
    assert '  WARNING: no_entities_matched\n' in capsys.readouterr().out


def test_an_empty_run_does_not_fail_the_job(monkeypatch, tmp_path, capsys):
    from sqlalchemy import create_engine, text

    engine = create_engine(f"sqlite:///{tmp_path / 'job.db'}")
    with engine.begin() as conn:
        conn.execute(text('CREATE TABLE alembic_version (version_num VARCHAR(32) NOT NULL)'))
    empty = {
        'policy_id': 'p1', 'policy_name': 'Datasets described', 'status': 'succeeded',
        'success_count': 0, 'failure_count': 0, 'score': 0.0, 'error': None,
        'warning': {'code': 'no_entities_matched', 'params': None},
    }
    monkeypatch.setattr(job, 'WorkspaceClient', lambda **_: SimpleNamespace(
        config=SimpleNamespace(host='https://example.cloud.databricks.com')))
    monkeypatch.setattr(job, '_initialize_application_config', lambda ws: None)
    monkeypatch.setattr(job, 'create_engine_from_params', lambda **_: engine)
    monkeypatch.setattr(job, 'check_schema_revision', lambda *a: None)
    monkeypatch.setattr(job, 'load_policies', lambda *a, **k: [{'id': 'p1', 'name': 'x'}])
    monkeypatch.setattr(job, 'run_policy', lambda *a, **k: empty)
    monkeypatch.setattr('sys.argv', [
        'compliance_checks.py', '--lakebase_instance_name', 'local',
        '--postgres_host', 'localhost', '--postgres_db', 'db',
    ])

    job.main()  # no SystemExit

    out = capsys.readouterr().out
    assert 'could not be evaluated' not in out
    assert 'Datasets described: no_entities_matched' in out
