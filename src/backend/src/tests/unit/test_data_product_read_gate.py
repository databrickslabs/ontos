"""Unit tests for the direct-read gate on data products (ONT-NEG-011).

A consumer could read an unpublished (draft) product by id via
GET /api/data-products/{id}. The gate must allow published products to
everyone but restrict unpublished ones to admins and owners.
"""
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from src.routes.data_product_routes import _caller_can_read_product


def _request(*, is_admin: bool):
    auth_manager = MagicMock()
    auth_manager.get_user_effective_permissions.return_value = {}
    auth_manager.has_permission.return_value = is_admin
    request = MagicMock()
    request.app.state.authorization_manager = auth_manager
    request.app.state.settings_manager = None
    return request


def _user(email="consumer@example.com"):
    return SimpleNamespace(email=email, groups=[])


class TestProductReadGate:
    def test_published_product_readable_by_anyone(self):
        manager = MagicMock()
        # Even if the accessible set is empty, a published product is readable.
        manager.list_products.return_value = []
        product = SimpleNamespace(id="p1", status="active")

        assert _caller_can_read_product(
            _request(is_admin=False), MagicMock(), _user(), manager, product
        ) is True
        # Published short-circuit: we never needed to scope the listing.
        manager.list_products.assert_not_called()

    def test_draft_denied_for_non_owner_non_admin(self):
        manager = MagicMock()
        manager.list_products.return_value = []  # caller owns nothing
        product = SimpleNamespace(id="p1", status="draft")

        assert _caller_can_read_product(
            _request(is_admin=False), MagicMock(), _user(), manager, product
        ) is False

    def test_draft_allowed_for_feature_admin(self):
        manager = MagicMock()
        product = SimpleNamespace(id="p1", status="draft")

        assert _caller_can_read_product(
            _request(is_admin=True), MagicMock(), _user(), manager, product
        ) is True

    def test_draft_allowed_for_owner_in_accessible_set(self):
        manager = MagicMock()
        manager.list_products.return_value = [SimpleNamespace(id="p1")]  # caller owns it
        product = SimpleNamespace(id="p1", status="draft")

        assert _caller_can_read_product(
            _request(is_admin=False), MagicMock(), _user(), manager, product
        ) is True
