"""Policy rules are checked when a policy is created or updated."""
import os

os.environ['TESTING'] = 'true'
os.environ['SKIP_STARTUP_TASKS'] = 'true'

import uuid
from unittest.mock import MagicMock

import pytest
from fastapi import HTTPException

from src.common.compliance_entities import validate_rule
from src.db_models.compliance import CompliancePolicyDb
from src.models.compliance import CompliancePolicy, CompliancePolicyCreate
from src.routes import compliance_routes

VALID = "MATCH (prod:data_product) ASSERT prod.owner != ''"
BROKEN = "MATCH (obj:Object) ASSERT obj.status == 'active'"


class TestValidateRule:

    @pytest.mark.parametrize('rule', [
        VALID,
        "MATCH (obj:Object) ASSERT obj.name != ''",
        "MATCH (tbl:table) WHERE tbl.catalog = 'main' ASSERT HAS_TAG('owner')",
    ])
    def test_working_rules_have_no_warnings(self, rule):
        assert validate_rule(rule) == []

    def test_unparseable_rule_raises(self):
        with pytest.raises(ValueError, match='Unexpected token'):
            validate_rule(BROKEN)

    @pytest.mark.parametrize('match_type', ['Dataset', 'glossary_term'])
    def test_unsupported_match_type_is_a_warning(self, match_type):
        [warning] = validate_rule(f"MATCH (x:{match_type}) ASSERT x.name != ''")

        assert f"MATCH type '{match_type}' is not supported" in warning
        assert 'data_product' in warning

    def test_rule_without_match_is_valid(self):
        # Maturity gates and workflow policy checks evaluate such rules per entity.
        assert validate_rule("ASSERT obj.has_owner = True") == []

    def test_missing_assert_is_a_warning(self):
        assert validate_rule("asset.tags['pii'] == 'true'") == [
            "The rule has no ASSERT clause, so every entity passes.",
        ]


def _create(db, rule):
    return compliance_routes.create_policy(
        request=MagicMock(client=None),
        db=db,
        audit_manager=MagicMock(),
        current_user=None,
        policy=CompliancePolicyCreate(name='P', description='d', rule=rule),
        _=True,
    )


@pytest.mark.asyncio
async def test_create_rejects_unparseable_rule(db_session):
    with pytest.raises(HTTPException) as exc:
        await _create(db_session, BROKEN)

    assert exc.value.status_code == 422
    assert 'Unexpected token' in exc.value.detail
    assert db_session.query(CompliancePolicyDb).filter_by(rule=BROKEN).count() == 0


@pytest.mark.asyncio
async def test_create_saves_rule_with_warnings(db_session):
    rule = "MATCH (d:Dataset) ASSERT d.owner != ''"

    body = await _create(db_session, rule)

    assert db_session.get(CompliancePolicyDb, body['id']).rule == rule
    assert len(body['warnings']) == 1
    assert "MATCH type 'Dataset'" in body['warnings'][0]


@pytest.mark.asyncio
async def test_create_returns_no_warnings_for_working_rule(db_session):
    body = await _create(db_session, VALID)

    assert body['warnings'] == []


@pytest.mark.asyncio
async def test_update_rejects_unparseable_rule_and_keeps_the_old_one(db_session):
    policy = CompliancePolicyDb(id=str(uuid.uuid4()), name='P', description='d', rule=VALID)
    db_session.add(policy)
    db_session.flush()

    with pytest.raises(HTTPException) as exc:
        await compliance_routes.update_policy(
            policy_id=policy.id,
            request=MagicMock(client=None),
            db=db_session,
            audit_manager=MagicMock(),
            current_user=None,
            policy=CompliancePolicy(id=policy.id, name='P', description='d', rule=BROKEN),
            _=True,
        )

    assert exc.value.status_code == 422
    db_session.refresh(policy)
    assert policy.rule == VALID
