"""Comment routes: the permissions endpoint works and creating a comment is audited."""
import os

os.environ['TESTING'] = 'true'
os.environ['SKIP_STARTUP_TASKS'] = 'true'

import asyncio
import json
import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from src.models.comments import CommentCreate
from src.models.users import UserInfo
from src.routes import comments_routes

USER = UserInfo(email='alice@example.com', username='alice', user='Alice',
                ip='127.0.0.1', groups=['data-producers'])


def _no_admin():
    return (
        patch.object(
            comments_routes, 'get_user_groups', AsyncMock(return_value=['data-producers']),
        ),
        patch.object(comments_routes, 'is_user_admin', return_value=False),
    )


def test_the_permissions_endpoint_answers():
    manager = MagicMock()
    manager.can_user_modify_comment.return_value = True
    groups, admin = _no_admin()

    with groups, admin:
        result = asyncio.run(comments_routes.check_comment_permissions(
            comment_id='c-1', request=MagicMock(), db=MagicMock(), current_user=USER,
            manager=manager, _=True,
        ))

    assert result == {'can_modify': True, 'is_admin': False}
    kwargs = manager.can_user_modify_comment.call_args.kwargs
    assert (kwargs['comment_id'], kwargs['user_email']) == ('c-1', 'alice@example.com')


def test_creating_a_comment_writes_a_serializable_audit_entry():
    comment_id = uuid.uuid4()
    manager = MagicMock()
    manager.create_comment.return_value = SimpleNamespace(id=comment_id)
    audit_manager = MagicMock()
    payload = CommentCreate(entity_type='data_product', entity_id='p-1', comment='Final?')
    groups, admin = _no_admin()

    with groups, admin, patch.object(comments_routes, 'team_repo') as teams:
        teams.get_teams_for_user.return_value = []
        asyncio.run(comments_routes.create_comment(
            entity_type='data_product', entity_id='p-1', payload=payload, request=MagicMock(),
            db=MagicMock(), current_user=USER, audit_manager=audit_manager,
            audit_user=USER, manager=manager, _=True,
        ))

    details = audit_manager.log_action.call_args.kwargs['details']
    # The audit log stores the details as JSON
    assert json.loads(json.dumps(details))['comment_id'] == str(comment_id)
