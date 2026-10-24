"""Comment routes: admin check, permissions endpoint and the audit entry of a new comment."""
import os

os.environ['TESTING'] = 'true'
os.environ['SKIP_STARTUP_TASKS'] = 'true'

import asyncio
import json
import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException

from src.common import authorization
from src.common.features import FeatureAccessLevel
from src.controller.comments_manager import CommentsManager

from src.models.comments import CommentCreate
from src.models.users import UserInfo
from src.routes import comments_routes

USER = UserInfo(email='alice@example.com', username='alice', user='Alice',
                ip='127.0.0.1', groups=['data-producers'])


def _no_admin():
    return patch.object(comments_routes, 'is_user_feature_admin', new=AsyncMock(return_value=False))


def _stored_comment(db_session, author='alice@example.com'):
    from src.controller.comments_manager import CommentsManager

    manager = CommentsManager()
    comment = manager.create_comment(
        db_session, user_email=author, is_admin=True,
        data=CommentCreate(entity_type='data_product', entity_id='p-1', comment='Final?'),
    )
    return manager, str(comment.id)


def test_the_permissions_endpoint_answers(db_session):
    manager, comment_id = _stored_comment(db_session)
    admin = _no_admin()

    with admin:
        result = asyncio.run(comments_routes.check_comment_permissions(
            comment_id=comment_id, request=MagicMock(), db=db_session, current_user=USER,
            manager=manager, _=True,
        ))

    assert result == {'can_modify': True, 'is_admin': False}


def test_creating_a_comment_writes_a_serializable_audit_entry():
    comment_id = uuid.uuid4()
    manager = MagicMock()
    manager.create_comment.return_value = SimpleNamespace(id=comment_id)
    audit_manager = MagicMock()
    payload = CommentCreate(entity_type='data_product', entity_id='p-1', comment='Final?')
    admin = _no_admin()

    with admin, patch.object(comments_routes, 'team_repo') as teams:
        teams.get_teams_for_user.return_value = []
        asyncio.run(comments_routes.create_comment(
            entity_type='data_product', entity_id='p-1', payload=payload, request=MagicMock(),
            db=MagicMock(), current_user=USER, audit_manager=audit_manager,
            audit_user=USER, manager=manager, _=True,
        ))

    details = audit_manager.log_action.call_args.kwargs['details']
    # The audit log stores the details as JSON
    assert json.loads(json.dumps(details))['comment_id'] == str(comment_id)


# --- Who counts as a comments admin ---------------------------------------


def _create_global_comment(db_session, groups, role_level):
    """Create a comment with no audience as a user whose role gives `role_level` on comments."""
    user = UserInfo(email='alice@example.com', username='alice', user='Alice', ip=None,
                    groups=groups)
    request = MagicMock()
    request.app.state.authorization_manager.get_user_effective_permissions.return_value = {
        'comments': role_level,
    }
    request.app.state.settings_manager.get_applied_role_override_for_user.return_value = None
    payload = CommentCreate(entity_type='data_product', entity_id='p-1', comment='Hello')
    settings = SimpleNamespace(APP_ADMIN_DEFAULT_GROUPS='["admins"]')
    with patch.object(authorization, 'get_settings', return_value=settings), \
            patch.object(authorization, 'get_user_team_role_overrides',
                         new=AsyncMock(return_value=None)):
        return asyncio.run(comments_routes.create_comment(
            entity_type='data_product', entity_id='p-1', payload=payload, request=request,
            db=db_session, current_user=user, audit_manager=MagicMock(), audit_user=user,
            manager=CommentsManager(), _=True,
        ))


def test_a_workspace_admin_can_create_a_global_comment(db_session):
    result = _create_global_comment(db_session, ['admins'], FeatureAccessLevel.READ_WRITE)

    assert result.comment == 'Hello'


def test_a_user_whose_role_has_admin_on_comments_can_create_a_global_comment(db_session):
    result = _create_global_comment(db_session, ['data-stewards'], FeatureAccessLevel.ADMIN)

    assert result.comment == 'Hello'


def test_a_user_without_admin_on_comments_cannot_create_a_global_comment(db_session):
    with pytest.raises(HTTPException) as exc:
        _create_global_comment(db_session, ['data-producers'], FeatureAccessLevel.READ_WRITE)

    assert exc.value.status_code == 403


# --- The manager finds comments by the id the routes pass (a string) --------


def test_a_comment_is_found_and_checked_by_its_string_id(db_session):
    manager, comment_id = _stored_comment(db_session)

    assert str(manager.get_comment(db_session, comment_id=comment_id).id) == comment_id
    assert manager.can_user_modify_comment(
        db_session, comment_id=comment_id, user_email='alice@example.com',
    ) is True
    assert manager.can_user_modify_comment(
        db_session, comment_id=comment_id, user_email='bob@example.com',
    ) is False


def test_a_comment_is_updated_and_deleted_by_its_string_id(db_session):
    from src.models.comments import CommentUpdate

    manager, comment_id = _stored_comment(db_session)

    updated = manager.update_comment(
        db_session, comment_id=comment_id, user_email='alice@example.com',
        data=CommentUpdate(comment='Final, yes.'),
    )
    assert updated.comment == 'Final, yes.'
    assert manager.delete_comment(
        db_session, comment_id=comment_id, user_email='alice@example.com',
    ) is True


def test_an_id_that_is_not_a_uuid_is_not_found(db_session):
    from src.controller.comments_manager import CommentsManager

    manager = CommentsManager()

    assert manager.get_comment(db_session, comment_id='c-1') is None
    assert manager.can_user_modify_comment(
        db_session, comment_id='c-1', user_email='alice@example.com',
    ) is False
