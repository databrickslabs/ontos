"""Wizard sessions are scoped to the user who started them.

A session holds the requester's answers, so listing, reading, submitting and
aborting are limited to its owner. Reading other users' sessions needs
``settings-workflows`` READ_ONLY (the level that reads agreements), aborting
them needs ADMIN; nobody else may submit steps. Non-owners get a 404, the same
answer as for a missing session.
"""
import os

os.environ['TESTING'] = 'true'
os.environ['SKIP_STARTUP_TASKS'] = 'true'

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException

from src.common.features import FeatureAccessLevel
from src.repositories.agreement_wizard_sessions_repository import agreement_wizard_sessions_repo
from src.routes.approvals_routes import (
    SubmitStepBody,
    abort_approval_session,
    get_approval_session,
    list_approval_sessions,
    submit_approval_step,
)

OWNER = 'owner@example.com'
OTHER = 'other@example.com'


def _user(email):
    return MagicMock(email=email)


def _levels(granted_level=None):
    """Patch the permission lookup: True for levels up to ``granted_level``."""
    order = [FeatureAccessLevel.READ_ONLY, FeatureAccessLevel.READ_WRITE, FeatureAccessLevel.ADMIN]

    async def has_level(feature_id, required_level, user_details, request):
        if granted_level is None:
            return False
        return order.index(required_level) <= order.index(granted_level)

    return patch('src.routes.approvals_routes._has_feature_level', side_effect=has_level)


def _stored_session(created_by=OWNER):
    return patch.object(
        agreement_wizard_sessions_repo, 'get',
        return_value=SimpleNamespace(id='s1', created_by=created_by, entity_type='data_product'),
    )


def _get(caller, granted_level=None, created_by=OWNER):
    wizard_manager = MagicMock()
    wizard_manager.get_session.return_value = {'session_id': 's1', 'step_results': []}
    with _stored_session(created_by), _levels(granted_level):
        return asyncio.run(get_approval_session(
            request=MagicMock(), session_id='s1', db=MagicMock(),
            current_user=_user(caller), wizard_manager=wizard_manager,
            user_details=MagicMock(),
        )), wizard_manager


def _submit(caller, granted_level=None):
    wizard_manager = MagicMock()
    wizard_manager.submit_step.return_value = {'complete': False}
    with _stored_session(), _levels(granted_level), \
            patch('src.routes.approvals_routes._resolve_trigger_type_for_session', return_value=None):
        return asyncio.run(submit_approval_step(
            request=MagicMock(), session_id='s1', db=MagicMock(),
            body=SubmitStepBody(step_id='step-1', payload={}),
            current_user=_user(caller), wizard_manager=wizard_manager,
            user_details=MagicMock(),
        )), wizard_manager


def _abort(caller, granted_level=None):
    wizard_manager = MagicMock()
    wizard_manager.abort_session.return_value = True
    with _stored_session(), _levels(granted_level), \
            patch('src.routes.approvals_routes._resolve_trigger_type_for_session', return_value=None):
        return asyncio.run(abort_approval_session(
            request=MagicMock(), session_id='s1', db=MagicMock(),
            current_user=_user(caller), wizard_manager=wizard_manager,
            user_details=MagicMock(),
        )), wizard_manager


def _list(caller, granted_level=None):
    wizard_manager = MagicMock()
    wizard_manager.list_sessions.return_value = {'sessions': [], 'total': 0}
    with _levels(granted_level):
        result = asyncio.run(list_approval_sessions(
            request=MagicMock(), current_user=_user(caller), limit=50,
            wizard_manager=wizard_manager, user_details=MagicMock(),
        ))
    return result, wizard_manager


# --- get ---

def test_the_owner_reads_their_session():
    result, _ = _get(OWNER)

    assert result['session_id'] == 's1'


def test_the_owner_is_matched_case_insensitively():
    result, _ = _get('Owner@Example.com')

    assert result['session_id'] == 's1'


def test_another_user_gets_a_404_for_someone_elses_session():
    with pytest.raises(HTTPException) as exc:
        _get(OTHER)

    assert exc.value.status_code == 404


def test_a_workflow_settings_reader_reads_other_users_sessions():
    result, _ = _get(OTHER, granted_level=FeatureAccessLevel.READ_ONLY)

    assert result['session_id'] == 's1'


def test_a_session_without_owner_is_only_readable_with_the_settings_level():
    with pytest.raises(HTTPException) as exc:
        _get(OTHER, created_by=None)
    assert exc.value.status_code == 404

    result, _ = _get(OTHER, granted_level=FeatureAccessLevel.READ_ONLY, created_by=None)
    assert result['session_id'] == 's1'


def test_a_missing_session_keeps_the_handlers_not_found():
    wizard_manager = MagicMock()
    wizard_manager.get_session.return_value = None
    with patch.object(agreement_wizard_sessions_repo, 'get', return_value=None), _levels():
        with pytest.raises(HTTPException) as exc:
            asyncio.run(get_approval_session(
                request=MagicMock(), session_id='missing', db=MagicMock(),
                current_user=_user(OTHER), wizard_manager=wizard_manager,
                user_details=MagicMock(),
            ))

    assert exc.value.status_code == 404


# --- submit ---

def test_the_owner_submits_steps():
    result, wizard_manager = _submit(OWNER)

    assert result == {'complete': False}
    wizard_manager.submit_step.assert_called_once()


@pytest.mark.parametrize('granted_level', [None, FeatureAccessLevel.READ_ONLY, FeatureAccessLevel.ADMIN])
def test_nobody_else_submits_steps_on_someone_elses_session(granted_level):
    with pytest.raises(HTTPException) as exc:
        _submit(OTHER, granted_level=granted_level)

    assert exc.value.status_code == 404


def test_a_rejected_submit_does_not_reach_the_manager():
    wizard_manager = MagicMock()
    with _stored_session(), _levels(), \
            patch('src.routes.approvals_routes.enforce_wizard_permission', new=AsyncMock()) as gate:
        with pytest.raises(HTTPException):
            asyncio.run(submit_approval_step(
                request=MagicMock(), session_id='s1', db=MagicMock(),
                body=SubmitStepBody(step_id='step-1', payload={}),
                current_user=_user(OTHER), wizard_manager=wizard_manager,
                user_details=MagicMock(),
            ))

    wizard_manager.submit_step.assert_not_called()
    gate.assert_not_called()


# --- abort ---

def test_the_owner_aborts_their_session():
    result, _ = _abort(OWNER)

    assert result == {'session_id': 's1', 'status': 'abandoned'}


def test_a_reader_cannot_abort_someone_elses_session():
    with pytest.raises(HTTPException) as exc:
        _abort(OTHER, granted_level=FeatureAccessLevel.READ_ONLY)

    assert exc.value.status_code == 404


def test_a_workflow_settings_admin_aborts_someone_elses_session():
    result, _ = _abort(OTHER, granted_level=FeatureAccessLevel.ADMIN)

    assert result['status'] == 'abandoned'


# --- list ---

def test_users_list_only_their_own_sessions():
    _, wizard_manager = _list(OWNER)

    wizard_manager.list_sessions.assert_called_once_with(limit=50, created_by=OWNER)


def test_a_workflow_settings_reader_lists_everyones_sessions():
    _, wizard_manager = _list(OTHER, granted_level=FeatureAccessLevel.READ_ONLY)

    wizard_manager.list_sessions.assert_called_once_with(limit=50)


def test_a_caller_without_email_lists_nothing():
    result, wizard_manager = _list(None)

    assert result == {'sessions': [], 'total': 0}
    wizard_manager.list_sessions.assert_not_called()


# --- repository filter ---

def test_list_recent_filters_by_creator_case_insensitively(db_session):
    for owner in (OWNER, 'Owner@Example.com', OTHER, None):
        agreement_wizard_sessions_repo.create(
            db_session, workflow_id='wf-1', entity_type='data_product',
            entity_id='p1', created_by=owner,
        )
    db_session.flush()

    mine = agreement_wizard_sessions_repo.list_recent(db_session, created_by=OWNER)
    everyone = agreement_wizard_sessions_repo.list_recent(db_session)

    assert sorted(s['created_by'] for s in mine) == ['Owner@Example.com', OWNER]
    assert len(everyone) == 4
