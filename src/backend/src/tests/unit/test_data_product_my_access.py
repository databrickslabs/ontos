"""GET /api/data-products/{id}/my-access (#1613).

The product page showed Edit to every data-products writer on an editable
product, even one who reads it only as its reviewer; the save then failed
with 403. ``can_write`` follows the ownership rule of the PUT route.
"""
import asyncio
from types import SimpleNamespace
from unittest.mock import MagicMock

from src.common.features import FeatureAccessLevel
from src.routes.data_product_routes import get_my_product_access


def _auth(levels):
    """An auth manager granting exactly ``levels`` on data-products."""
    auth = MagicMock()
    auth.get_user_effective_permissions.return_value = {}
    auth.has_permission.side_effect = lambda _eff, _feature, level: level in levels
    return auth


def _request(auth):
    request = MagicMock()
    request.app.state.authorization_manager = auth
    request.app.state.settings_manager = None
    request.headers = {}
    return request


def _draft(owner="owner@example.com"):
    return SimpleNamespace(
        id="p1", status="under_review", draft_owner_id=owner,
        owner_team_id=None, project_id=None,
    )


def _call(levels, product, email):
    auth = _auth(levels)
    user = SimpleNamespace(email=email, groups=[])
    return asyncio.run(get_my_product_access(
        request=_request(auth), db=MagicMock(), current_user=user,
        auth_manager=auth, product=product, _=True,
    ))


RW = {FeatureAccessLevel.READ_ONLY, FeatureAccessLevel.READ_WRITE}
ADMIN = RW | {FeatureAccessLevel.ADMIN}


def test_writer_who_does_not_own_the_product_cannot_write():
    # e.g. the reviewer of a product under review: reads it, can't edit it
    assert _call(RW, _draft(), "reviewer@example.com") == {"can_write": False}


def test_draft_owner_with_write_can_write():
    assert _call(RW, _draft(), "Owner@Example.com") == {"can_write": True}


def test_owner_without_write_permission_cannot_write():
    levels = {FeatureAccessLevel.READ_ONLY}
    assert _call(levels, _draft(), "owner@example.com") == {"can_write": False}


def test_data_products_admin_can_write_any_product():
    assert _call(ADMIN, _draft(), "admin@example.com") == {"can_write": True}


def test_failure_denies():
    auth = MagicMock()
    auth.get_user_effective_permissions.side_effect = RuntimeError("boom")
    user = SimpleNamespace(email="owner@example.com", groups=[])
    result = asyncio.run(get_my_product_access(
        request=_request(auth), db=MagicMock(), current_user=user,
        auth_manager=auth, product=_draft(), _=True,
    ))
    assert result == {"can_write": False}
