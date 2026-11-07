"""The compliance-checks job doesn't run maturity gate policies (#1150).

Maturity gates are evaluated by the maturity evaluator against one entity.
Run by the job they match no entity and leave a 0-entity run.
"""
import os

os.environ['TESTING'] = 'true'
os.environ['SKIP_STARTUP_TASKS'] = 'true'

import json

import pytest
from sqlalchemy import create_engine, text

import src.workflows.compliance_checks.compliance_checks as job


@pytest.fixture
def engine(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'job.db'}")
    with engine.begin() as conn:
        conn.execute(text(
            'CREATE TABLE compliance_policies (id VARCHAR PRIMARY KEY, name VARCHAR, '
            'description VARCHAR, rule VARCHAR, category VARCHAR, severity VARCHAR, '
            'is_active BOOLEAN)'
        ))
        conn.execute(text(
            'CREATE TABLE maturity_gates (id VARCHAR PRIMARY KEY, '
            'compliance_policy_id VARCHAR NOT NULL)'
        ))
        for pid, name, category in [
            ('normal', 'Normal policy', 'Governance'),
            ('gate', 'Gate policy', 'Governance'),
            # A gate that is not in the Maturity category is still a gate
            ('maturity-not-gate', 'Maturity but no gate', 'Maturity'),
        ]:
            conn.execute(text(
                "INSERT INTO compliance_policies VALUES (:i, :n, '', 'ASSERT 1 = 1', :c, 'high', 1)"
            ), {'i': pid, 'n': name, 'c': category})
        conn.execute(text("INSERT INTO maturity_gates VALUES ('g1', 'gate')"))
    return engine


def _ids(policies):
    return sorted(p['id'] for p in policies)


def test_a_gate_policy_is_skipped_and_the_others_run(engine):
    policies = job.load_policies(engine, 'active', None, None)

    assert _ids(policies) == ['maturity-not-gate', 'normal']


def test_a_gate_is_skipped_also_when_asked_for_by_id(engine):
    policies = job.load_policies(engine, json.dumps(['gate', 'normal']), None, None)

    assert _ids(policies) == ['normal']


def test_all_filter_skips_gates_too(engine):
    assert _ids(job.load_policies(engine, 'all', None, None)) == ['maturity-not-gate', 'normal']
