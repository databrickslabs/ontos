"""Saving or running a policy with tag actions needs write access to tags.

ASSIGN_TAG / REMOVE_TAG write tag associations, so a user with compliance
access but no tag access could otherwise change tags, including governed
ones, through a policy.
"""
import os

os.environ['TESTING'] = 'true'
os.environ['SKIP_STARTUP_TASKS'] = 'true'

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from fastapi import HTTPException

from src.common.features import FeatureAccessLevel
from src.controller.authorization_manager import AuthorizationManager
from src.controller.compliance_manager import rule_changes_tags
from src.routes.compliance_routes import require_tag_write_for_tag_actions

TAGGING = "MATCH (p:data_product) ASSERT p.status = 'active' ON_FAIL ASSIGN_TAG review: 'needed'"
UNTAGGING = "MATCH (p:data_product) ASSERT p.status = 'active' ON_PASS REMOVE_TAG review"
PLAIN = "MATCH (p:data_product) ASSERT p.status = 'active' ON_FAIL FAIL 'Not active'"


def _auth(tags_level):
    auth = MagicMock()
    auth.get_user_effective_permissions.return_value = {'tags': tags_level}
    auth.has_permission.side_effect = (
        lambda perms, feature, level: AuthorizationManager.has_permission(None, perms, feature, level)
    )
    return auth


USER = SimpleNamespace(username='author@example.com', groups=['compliance-editors'])


@pytest.mark.parametrize('rule, expected', [
    (TAGGING, True), (UNTAGGING, True), (PLAIN, False), ('MATCH (p:data_product', False), (None, False),
])
def test_rule_changes_tags(rule, expected):
    assert rule_changes_tags(rule) is expected


@pytest.mark.parametrize('level', [FeatureAccessLevel.NONE, FeatureAccessLevel.READ_ONLY])
def test_tag_actions_need_write_access_to_tags(level):
    with pytest.raises(HTTPException) as err:
        require_tag_write_for_tag_actions(TAGGING, _auth(level), USER)

    assert err.value.status_code == 403
    assert 'requires write access to tags' in err.value.detail


def test_tag_actions_are_allowed_with_write_access_to_tags():
    require_tag_write_for_tag_actions(UNTAGGING, _auth(FeatureAccessLevel.READ_WRITE), USER)


def test_rules_without_tag_actions_need_no_tag_access():
    auth = _auth(FeatureAccessLevel.NONE)

    require_tag_write_for_tag_actions(PLAIN, auth, USER)

    auth.get_user_effective_permissions.assert_not_called()
