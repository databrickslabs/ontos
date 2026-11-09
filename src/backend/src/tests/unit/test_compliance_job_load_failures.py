"""The compliance job and runs fail when entities can't be read (#813).

On a database that missed a migration, loading data contracts raised
``UndefinedColumn``; the loader only logged it, so every contract policy
"succeeded" with 0 entities and a 0% score, and the job exited 0. A type that
can't be loaded now fails the runs on it with a code the UI translates, and
the job checks the schema revision before it runs and exits non-zero when a
policy could not be evaluated.
"""
import os

os.environ['TESTING'] = 'true'
os.environ['SKIP_STARTUP_TASKS'] = 'true'

import sys
import uuid
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from zipfile import ZipFile

import pytest
from sqlalchemy import create_engine, text

import src.workflows.compliance_checks.compliance_checks as job
from src.common.compliance_entities import AppEntityLoader, EntityLoadError
from src.controller.compliance_manager import ComplianceManager
from src.db_models.compliance import CompliancePolicyDb, ComplianceResultDb
from src.db_models.data_products import DataProductDb
from src.utils.workspace_deployer import WorkspaceDeployer

_BACKEND_DIR = Path(job.__file__).resolve().parent.parent.parent.parent
_ALEMBIC_DIR = _BACKEND_DIR / 'alembic'

_REPOS = {
    'data_product': 'src.repositories.data_products_repository.data_product_repo.get_multi',
    'data_contract': 'src.repositories.data_contracts_repository.data_contract_repo.get_multi',
    'domain': 'src.repositories.data_domain_repository.data_domain_repo.get_multi',
    'review': 'src.repositories.data_asset_reviews_repository.data_asset_review_repo.get_multi',
}


def _undefined_column(db, **_):
    # What a table behind the ORM gives on Postgres: the query fails
    db.execute(text('SELECT no_such_column FROM compliance_policies'))


@pytest.mark.parametrize('entity_type', sorted(_REPOS))
def test_a_type_that_cant_be_loaded_raises_with_a_code(db_session, entity_type):
    with patch(_REPOS[entity_type], side_effect=_undefined_column), \
            pytest.raises(EntityLoadError) as e:
        list(AppEntityLoader(db_session).load_entities([entity_type]))

    assert str(e.value) == f'Could not load the {entity_type} entities'
    assert e.value.error_code == 'entities_load_failed'
    assert e.value.error_params == {'entityType': entity_type}


def test_the_other_types_still_load(db_session):
    product = DataProductDb(
        id=str(uuid.uuid4()), api_version='v1.0.0', kind='DataProduct',
        status='active', name=f'loads-{uuid.uuid4().hex[:8]}', version='1.0.0',
    )
    db_session.add(product)
    db_session.flush()

    # Only the types a rule matches are loaded: a broken contracts table
    # doesn't stop the rules on products
    with patch(_REPOS['data_contract'], side_effect=_undefined_column):
        loaded = list(AppEntityLoader(db_session).load_entities(['data_product']))

    assert product.id in [entity['id'] for entity in loaded]


def _contract_policy(db):
    policy = CompliancePolicyDb(
        id=str(uuid.uuid4()), name=f'Contracts active {uuid.uuid4().hex[:8]}',
        rule="MATCH (c:data_contract) ASSERT obj.status = 'active' ON_FAIL FAIL 'Not active'",
        category='Governance', severity='high', is_active=True,
    )
    db.add(policy)
    db.flush()
    return policy


def test_a_run_on_a_type_that_cant_be_loaded_fails(db_session):
    policy = _contract_policy(db_session)

    with patch('src.common.workspace_client.get_workspace_client', return_value=None), \
            patch(_REPOS['data_contract'], side_effect=_undefined_column):
        run = ComplianceManager().run_policy_inline(db_session, policy=policy)

    # It "succeeded" with 0 passed, 0 failed and a 0% score
    assert run.status == 'failed'
    assert run.error_message == 'Could not load the data_contract entities'
    assert 'no_such_column' not in run.error_message
    results = db_session.query(ComplianceResultDb).filter(ComplianceResultDb.run_id == run.id)
    assert results.count() == 0


# --- Schema revision check of the job ---

def _engine_at(tmp_path, *revisions):
    engine = create_engine(f"sqlite:///{tmp_path / 'job.db'}")
    with engine.begin() as conn:
        conn.execute(text('CREATE TABLE alembic_version (version_num VARCHAR(32) NOT NULL)'))
        for revision in revisions:
            conn.execute(text('INSERT INTO alembic_version VALUES (:r)'), {'r': revision})
    return engine


def _head():
    from alembic.script import ScriptDirectory
    return ScriptDirectory(str(_ALEMBIC_DIR)).get_current_head()


def test_a_database_at_the_head_passes(tmp_path, capsys):
    job.check_schema_revision(_engine_at(tmp_path, _head()), _ALEMBIC_DIR)

    assert f'Database schema at revision {_head()}' in capsys.readouterr().out


def test_a_database_behind_the_head_stops_the_job(tmp_path, capsys):
    # The revision of the issue's database: version_family_id not applied yet
    engine = _engine_at(tmp_path, 'i9466e370gg2')

    with pytest.raises(job.SchemaRevisionError):
        job.check_schema_revision(engine, _ALEMBIC_DIR)

    out = capsys.readouterr().out
    assert 'ERROR: The database schema is at revision i9466e370gg2, behind' in out
    assert _head() in out


def test_a_database_without_a_revision_stops_the_job(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'empty.db'}")

    with pytest.raises(job.SchemaRevisionError):
        job.check_schema_revision(engine, _ALEMBIC_DIR)


def test_a_database_newer_than_the_code_is_reported_only(tmp_path, capsys):
    # The job was installed by an older app version; the app has migrated since
    job.check_schema_revision(_engine_at(tmp_path, 'z9_from_a_newer_app'), _ALEMBIC_DIR)

    assert 'newer than this code' in capsys.readouterr().out


def test_scripts_with_two_heads_stop_the_job(tmp_path, capsys):
    import shutil
    from alembic.script import ScriptDirectory

    scripts = tmp_path / 'alembic'
    shutil.copytree(_ALEMBIC_DIR, scripts)
    parent = ScriptDirectory(str(scripts)).get_revision(_head()).down_revision
    (scripts / 'versions' / 'zz_second_head.py').write_text(
        f"revision = 'zz_second_head'\ndown_revision = {parent!r}\n"
        "branch_labels = None\ndepends_on = None\n"
        "def upgrade():\n    pass\ndef downgrade():\n    pass\n"
    )

    with pytest.raises(job.SchemaRevisionError):
        job.check_schema_revision(_engine_at(tmp_path, _head()), scripts)

    out = capsys.readouterr().out
    assert 'ERROR: The Alembic scripts shipped with this code have more than one head' in out
    assert 'zz_second_head' in out and _head() in out


def test_without_the_scripts_the_check_is_skipped(tmp_path, capsys):
    job.check_schema_revision(_engine_at(tmp_path, 'i9466e370gg2'), None)

    assert 'schema revision not checked' in capsys.readouterr().out


def test_the_deployed_archive_carries_the_scripts(tmp_path):
    archive = tmp_path / 'backend_src.zip'
    archive.write_bytes(WorkspaceDeployer._build_python_package_archive(_BACKEND_DIR / 'src'))
    extracted = tmp_path / 'extracted'
    with ZipFile(archive) as zf:
        zf.extractall(extracted)

    # Where main() finds them after extracting the archive
    assert job._alembic_script_location(str(extracted)) == extracted / 'alembic'
    from alembic.script import ScriptDirectory
    assert ScriptDirectory(str(extracted / 'alembic')).get_current_head() == _head()


# --- Exit code of the job ---

def _run_main(monkeypatch, tmp_path, run_result, revision=None):
    monkeypatch.setattr(job, 'WorkspaceClient', lambda **_: SimpleNamespace(
        config=SimpleNamespace(host='https://example.cloud.databricks.com')))
    monkeypatch.setattr(job, '_initialize_application_config', lambda ws: None)
    monkeypatch.setattr(job, 'create_engine_from_params',
                        lambda **_: _engine_at(tmp_path, revision or _head()))
    monkeypatch.setattr(job, 'load_policies', lambda *a, **k: [{'id': 'p1', 'name': 'Contracts active'}])
    monkeypatch.setattr(job, 'run_policy', lambda *a, **k: run_result)
    monkeypatch.setattr(sys, 'argv', [
        'compliance_checks.py', '--lakebase_instance_name', 'local',
        '--postgres_host', 'localhost', '--postgres_db', 'db',
    ])
    job.main()


def test_a_policy_that_could_not_be_evaluated_fails_the_job(monkeypatch, tmp_path, capsys):
    failed = {
        'policy_id': 'p1', 'policy_name': 'Contracts active', 'status': 'failed',
        'success_count': 0, 'failure_count': 0, 'score': 0.0,
        'error': 'Could not load the data_contract entities',
    }

    with pytest.raises(SystemExit) as e:
        _run_main(monkeypatch, tmp_path, failed)

    assert e.value.code == 1
    out = capsys.readouterr().out
    assert '1 of 1 policies could not be evaluated' in out
    assert 'Contracts active: Could not load the data_contract entities' in out


def test_evaluated_policies_end_the_job_normally(monkeypatch, tmp_path):
    succeeded = {
        'policy_id': 'p1', 'policy_name': 'Contracts active', 'status': 'succeeded',
        'success_count': 3, 'failure_count': 1, 'score': 75.0, 'error': None,
    }

    # Violations are results, not a failure of the job
    _run_main(monkeypatch, tmp_path, succeeded)


def test_a_schema_mismatch_ends_the_job_without_a_traceback(monkeypatch, tmp_path, capsys):
    monkeypatch.setattr(job, 'load_policies', lambda *a, **k: pytest.fail('policies must not load'))

    # SystemExit, not SchemaRevisionError: main() stops after the ERROR line
    with pytest.raises(SystemExit) as e:
        _run_main(monkeypatch, tmp_path, None, revision='i9466e370gg2')

    assert e.value.code == 1
    assert 'ERROR:' in capsys.readouterr().out
