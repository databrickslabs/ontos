"""Explicit principal forms resolve before the reserved tokens and role names
(#1151 item 5).

A group named like a token (``reviewer``, ``admins``) or a role (``Data Steward``)
used to resolve to that token or role. ``group:<name>`` / ``user:<x>`` / an email /
a role UUID now win; plain names keep the old order. The explicit forms keep
their prefix in what is stored (an email stays bare), so the delivery doesn't read
them as a role name either.
"""
import os

os.environ['TESTING'] = 'true'
os.environ['SKIP_STARTUP_TASKS'] = 'true'

import uuid
from types import SimpleNamespace

import pytest

from src.common.workflow_executor import _resolve_role_to_users
from src.db_models.settings import AppRoleDb


def _context(reviewer_email=None):
    entity = {'reviewer_email': reviewer_email} if reviewer_email else {}
    return SimpleNamespace(
        user_email='requester@example.com', entity=entity, entity_type='concept',
        entity_id='concept-1', entity_name='C',
    )


@pytest.fixture
def roles(db_session):
    made = {}
    for name in ('Admin', 'Data Steward'):
        role = AppRoleDb(id=str(uuid.uuid4()), name=name)
        db_session.add(role)
        made[name] = role
    db_session.flush()
    return made


def test_a_group_named_reviewer_is_that_group(db_session, roles):
    out = _resolve_role_to_users(
        db_session, 'group:reviewer', _context(reviewer_email='rita@example.com'),
    )
    assert out == [('group:reviewer', None)]


def test_the_reviewer_token_still_means_the_chosen_reviewer(db_session, roles):
    ctx = _context(reviewer_email='rita@example.com')
    assert _resolve_role_to_users(db_session, 'reviewer', ctx) == [('rita@example.com', None)]


def test_token_and_group_side_by_side(db_session, roles):
    ctx = _context(reviewer_email='rita@example.com')
    out = _resolve_role_to_users(db_session, 'reviewer,group:reviewer', ctx)
    assert out == [('rita@example.com', None), ('group:reviewer', None)]


@pytest.mark.parametrize('name', ['admins', 'data_stewards', 'requester', 'owner'])
def test_a_group_named_like_a_legacy_token_is_that_group(db_session, roles, name):
    out = _resolve_role_to_users(db_session, f'group:{name}', _context())
    assert out == [(f'group:{name}', None)]


def test_a_group_named_like_an_app_role_is_that_group(db_session, roles):
    out = _resolve_role_to_users(db_session, 'group:Data Steward', _context())
    assert out == [('group:Data Steward', None)]


def test_a_user_named_like_an_app_role_is_that_user(db_session, roles):
    out = _resolve_role_to_users(db_session, 'user:DataSteward', _context())
    assert out == [('user:DataSteward', None)]


def test_a_user_named_like_a_token_is_that_user(db_session, roles):
    out = _resolve_role_to_users(
        db_session, 'user:reviewer', _context(reviewer_email='rita@example.com'),
    )
    assert out == [('user:reviewer', None)]


def test_a_role_uuid_resolves_to_the_role(db_session, roles):
    role = roles['Data Steward']
    assert _resolve_role_to_users(db_session, role.id, _context()) == [(role.name, role.id)]


@pytest.mark.parametrize('spec', ['group:', 'user:', 'group:  '])
def test_an_empty_explicit_form_resolves_to_nobody(db_session, roles, spec):
    assert _resolve_role_to_users(db_session, spec, _context()) == []


def test_plain_names_keep_the_old_resolution(db_session, roles):
    admin = roles['Admin']
    steward = roles['Data Steward']
    ctx = _context()
    assert _resolve_role_to_users(db_session, 'admins', ctx) == [('Admin', admin.id)]
    assert _resolve_role_to_users(db_session, 'Data Steward', ctx) == [
        ('Data Steward', steward.id),
    ]
    # A bare group name that is no token or role is still addressed as written
    assert _resolve_role_to_users(db_session, 'Producers', ctx) == [('Producers', None)]
    assert _resolve_role_to_users(db_session, 'user:a@example.com', ctx) == [
        ('a@example.com', None),
    ]


def test_a_group_with_an_at_sign_is_that_group(db_session, roles):
    out = _resolve_role_to_users(db_session, 'group:team@corp', _context())
    assert out == [('group:team@corp', None)]


def test_the_same_principal_in_other_case_is_one_target(db_session, roles):
    out = _resolve_role_to_users(
        db_session, 'Ana@Example.com,ana@example.com,user:Bob,user:bob', _context(),
    )
    assert out == [('Ana@Example.com', None), ('user:Bob', None)]


def test_a_group_name_with_a_comma_is_one_group(db_session, roles):
    """The designer writes the comma as %2C (and % as %25)."""
    out = _resolve_role_to_users(
        db_session, 'group:Sales%2C EMEA,group:100%25 Ops', _context(),
    )
    assert out == [('group:Sales, EMEA', None), ('group:100% Ops', None)]
