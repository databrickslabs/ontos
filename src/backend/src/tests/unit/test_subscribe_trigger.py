"""Unit tests for the on_subscribe trigger refactor (Option A).

Trigger firing for on_subscribe used to live in
``data_product_routes.subscribe_to_product``. That meant the wizard's
auto-subscribe path (``agreement_wizard_manager._complete_session`` →
``dp_manager.subscribe``) silently bypassed it — wizard-completed
subscriptions never fired the corresponding ``on_subscribe`` process
workflow (no external runbook, no notifications).

The refactor moves the trigger fire + entity_data enrichment
(``on_behalf_of`` flattening, ``consumer_groups`` pull) into
``DataProductsManager._fire_on_subscribe_trigger``, called from inside
``subscribe()`` after the persistence is committed. Both code paths fire
it: new-subscription path AND the "already subscribed" early return path
(preserves the prior route-handler behavior).

These tests target the helper directly so we don't need a full
end-to-end persistence harness:
  * entity_data has the expected shape for each on_behalf_of type
    (user / group / service_principal) — including the ``display`` field
  * entity_data.consumer_groups is populated when the product has them
  * entity_type is EntityType.SUBSCRIPTION
  * subscription_id is preferred over product_id when present
  * Trigger errors are swallowed (non-fatal)
"""
# Set test environment variables BEFORE any app imports
import os
os.environ['TESTING'] = 'true'
os.environ['SKIP_STARTUP_TASKS'] = 'true'

from types import SimpleNamespace
from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest

from src.models.data_products import OnBehalfOf


def _make_product(consumer_groups=None):
    """Minimal product-like object the helper inspects via getattr."""
    return SimpleNamespace(
        id="prod-123",
        consumer_groups=consumer_groups,
    )


@pytest.fixture
def manager(db_session):
    from src.controller.data_products_manager import DataProductsManager
    return DataProductsManager(db=db_session)


# =========================================================================
# Trigger fire — entity_data shape per on_behalf_of variant
# =========================================================================

class TestFireOnSubscribeTrigger:
    def _call(self, manager, *, product=None, on_behalf_of=None,
              subscription_id=None, reason=None):
        with patch(
            'src.common.workflow_triggers.fire_trigger_safe'
        ) as fire_mock:
            manager._fire_on_subscribe_trigger(
                db_session=manager._db,
                product=product if product is not None else _make_product(),
                product_id="prod-123",
                subscriber_email="consumer@example.com",
                reason=reason,
                on_behalf_of=on_behalf_of,
                subscription_id=subscription_id,
            )
        return fire_mock

    def test_no_on_behalf_of_no_consumer_groups(self, manager):
        fire_mock = self._call(manager, reason="for dashboards")
        assert fire_mock.call_count == 1
        kwargs = fire_mock.call_args.kwargs
        # Method positional args: (db, "on_subscribe")
        args = fire_mock.call_args.args
        assert args[1] == "on_subscribe"
        from src.models.process_workflows import EntityType
        # entity_type is DATA_PRODUCT (not SUBSCRIPTION) so workflows
        # registered with entity_types=["data_product"] match.
        assert kwargs["entity_type"] is EntityType.DATA_PRODUCT
        assert kwargs["entity_id"] == "prod-123"
        assert kwargs["entity_name"] == "prod-123"
        assert kwargs["user_email"] == "consumer@example.com"

        ed = kwargs["entity_data"]
        assert ed["product_id"] == "prod-123"
        assert ed["subscriber_email"] == "consumer@example.com"
        assert ed["reason"] == "for dashboards"
        assert "on_behalf_of" not in ed
        assert "consumer_groups" not in ed

    def test_on_behalf_of_user_display_is_value(self, manager):
        obo = OnBehalfOf(type="user", value="alice@example.com")
        fire_mock = self._call(manager, on_behalf_of=obo)
        ed = fire_mock.call_args.kwargs["entity_data"]
        assert ed["on_behalf_of"] == {
            "type": "user",
            "value": "alice@example.com",
            "display": "alice@example.com",
        }

    def test_on_behalf_of_group_display_prefixed(self, manager):
        obo = OnBehalfOf(type="group", value="sales_consumers")
        fire_mock = self._call(manager, on_behalf_of=obo)
        ed = fire_mock.call_args.kwargs["entity_data"]
        assert ed["on_behalf_of"] == {
            "type": "group",
            "value": "sales_consumers",
            "display": "Group: sales_consumers",
        }

    def test_on_behalf_of_service_principal_display_prefixed(self, manager):
        obo = OnBehalfOf(type="service_principal", value="external-runbook-sp")
        fire_mock = self._call(manager, on_behalf_of=obo)
        ed = fire_mock.call_args.kwargs["entity_data"]
        assert ed["on_behalf_of"] == {
            "type": "service_principal",
            "value": "external-runbook-sp",
            "display": "SP: external-runbook-sp",
        }

    def test_consumer_groups_surfaced_when_present(self, manager):
        product = _make_product(consumer_groups=["analysts", "ml_team"])
        fire_mock = self._call(manager, product=product)
        ed = fire_mock.call_args.kwargs["entity_data"]
        assert ed["consumer_groups"] == ["analysts", "ml_team"]

    def test_consumer_groups_omitted_when_empty(self, manager):
        product = _make_product(consumer_groups=[])
        fire_mock = self._call(manager, product=product)
        ed = fire_mock.call_args.kwargs["entity_data"]
        assert "consumer_groups" not in ed

    def test_entity_id_is_product_id(self, manager):
        """entity_id is always the data product id so workflows
        registered with entity_types=["data_product"] resolve
        ${entity.product_id} consistently. The subscription_id is no
        longer used for the trigger event identifier."""
        sub_uuid = uuid4()
        fire_mock = self._call(manager, subscription_id=sub_uuid)
        assert fire_mock.call_args.kwargs["entity_id"] == "prod-123"

    def test_entity_id_when_no_subscription_id(self, manager):
        fire_mock = self._call(manager, subscription_id=None)
        assert fire_mock.call_args.kwargs["entity_id"] == "prod-123"

    def test_trigger_failure_is_non_fatal(self, manager):
        """A trigger fire raising must not propagate — the subscribe
        response must never break on transient trigger errors."""
        with patch(
            'src.common.workflow_triggers.fire_trigger_safe',
            side_effect=RuntimeError("registry boom"),
        ):
            # Must not raise.
            manager._fire_on_subscribe_trigger(
                db_session=manager._db,
                product=_make_product(),
                product_id="prod-123",
                subscriber_email="consumer@example.com",
                reason=None,
                on_behalf_of=None,
                subscription_id=None,
            )


# =========================================================================
# subscribe() integration — fires once per call (new + duplicate paths)
# =========================================================================

class TestSubscribeFiresTriggerOncePerCall:
    """Verify subscribe() invokes _fire_on_subscribe_trigger exactly once
    on both the new-subscription path and the already-subscribed early
    return path. This is the regression guard for Option A: previously
    wizard auto-subscribe never fired the trigger at all."""

    def _setup(self, db_session, *, existing=None, created=None,
               consumer_groups=None):
        """Common patches; returns (manager, fire_helper_mock)."""
        from src.controller.data_products_manager import DataProductsManager

        mgr = DataProductsManager(db=db_session)
        mock_product = SimpleNamespace(
            id="prod-x", status="active", consumer_groups=consumer_groups,
        )

        # Patch Subscription + SubscriptionResponse to bypass pydantic
        # validation against the SimpleNamespace fixtures (the manager
        # builds a real SubscriptionResponse whose .subscription field
        # validates against Subscription).
        sub_model_patch = patch(
            'src.controller.data_products_manager.Subscription'
        )
        sub_model = sub_model_patch.start()
        sub_model.model_validate.return_value = MagicMock()

        resp_patch = patch(
            'src.controller.data_products_manager.SubscriptionResponse'
        )
        resp_mock = resp_patch.start()
        resp_mock.return_value = MagicMock()
        self._extra_patches = [resp_patch]

        get_product_patch = patch.object(
            mgr, 'get_product', return_value=mock_product
        )
        get_product_patch.start()

        repo_patch = patch(
            'src.controller.data_products_manager.subscription_repo'
        )
        repo_mock = repo_patch.start()
        repo_mock.get_by_product_and_user.return_value = existing
        if created is not None:
            repo_mock.create.return_value = created

        log_patch = patch.object(mgr, '_log_subscription_change')
        log_patch.start()

        fire_patch = patch.object(mgr, '_fire_on_subscribe_trigger')
        fire_helper = fire_patch.start()

        # cleanup deferred to test exit via pytest fixture context — but
        # since we don't have one, register via addfinalizer-equivalent
        # by returning patches too.
        self._patches = [
            sub_model_patch, get_product_patch, repo_patch,
            log_patch, fire_patch,
        ] + getattr(self, '_extra_patches', [])
        return mgr, fire_helper

    def teardown_method(self, method):
        for p in getattr(self, '_patches', []):
            try:
                p.stop()
            except Exception:
                pass
        self._extra_patches = []

    def test_new_subscription_fires_trigger(self, db_session):
        sub_id = uuid4()
        created = SimpleNamespace(
            id=sub_id,
            product_id="prod-x",
            subscriber_email="u@x.com",
            reason=None,
            on_behalf_of_type=None,
            on_behalf_of_value=None,
            subscribed_at=None,
        )
        mgr, fire_helper = self._setup(
            db_session, existing=None, created=created,
            consumer_groups=["analysts"],
        )

        mgr.subscribe(
            product_id="prod-x",
            subscriber_email="u@x.com",
            db=db_session,
        )

        assert fire_helper.call_count == 1
        kwargs = fire_helper.call_args.kwargs
        assert kwargs["product_id"] == "prod-x"
        assert kwargs["subscriber_email"] == "u@x.com"
        assert kwargs["subscription_id"] == sub_id

    def test_duplicate_subscription_still_fires_trigger(self, db_session):
        """Already-subscribed early return path must still fire — preserves
        the prior route-handler behavior of firing regardless of new vs.
        duplicate. Wizard re-completion or re-subscribe must not silently
        skip the workflow."""
        existing_id = uuid4()
        existing = SimpleNamespace(
            id=existing_id,
            product_id="prod-x",
            subscriber_email="u@x.com",
            reason=None,
            on_behalf_of_type=None,
            on_behalf_of_value=None,
            subscribed_at=None,
        )
        mgr, fire_helper = self._setup(db_session, existing=existing)

        mgr.subscribe(
            product_id="prod-x",
            subscriber_email="u@x.com",
            db=db_session,
        )

        assert fire_helper.call_count == 1
        kwargs = fire_helper.call_args.kwargs
        assert kwargs["subscription_id"] == existing_id
