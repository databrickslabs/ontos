"""DeliveryService: POLICY_RELEASE direct apply, manual notification, file-model registry."""
from types import SimpleNamespace

from src.controller.delivery_service import (
    DeliveryChangeType,
    DeliveryMode,
    DeliveryPayload,
    DeliveryService,
)


class Grants:
    def __init__(self):
        self.calls = []

    def apply_grant(self, data, dry_run=False):
        self.calls.append(("grant", data))
        return {"success": True}

    def apply_revoke(self, data, dry_run=False):
        self.calls.append(("revoke", data))
        return {"success": True}


class Notifications:
    def __init__(self):
        self.created = []

    def create_delivery_notification(self, db, **kw):
        self.created.append(kw)
        return SimpleNamespace(id="n1")


def _svc(**kw):
    return DeliveryService(settings=SimpleNamespace(DELIVERY_DIRECT_DRY_RUN=False), **kw)


def _payload(data, db=None):
    return DeliveryPayload(change_type=DeliveryChangeType.POLICY_RELEASE, entity_type="AccessPolicyRelease",
                           entity_id="r1", data=data, db=db)


def test_direct_applies_revokes_first_and_refuses_unbounded_revoke():
    grants = Grants()
    data = {"grant": [{"principal": "a", "securable_type": "table", "securable_name": "m.s.t", "privileges": ["SELECT"]}],
            "revoke": [{"principal": "b", "securable_type": "table", "securable_name": "m.s.t", "privileges": []},
                       {"principal": "c", "securable_type": "table", "securable_name": "m.s.t", "privileges": ["MODIFY"]}]}
    res = _svc(grant_manager=grants).deliver(_payload(data), [DeliveryMode.DIRECT]).results[0]
    assert [c[0] for c in grants.calls] == ["revoke", "grant"]
    assert res.success is False and res.details["failed"] == 1 and res.details["applied"] == 2


def test_manual_creates_notification_without_orm_entity():
    notes = Notifications()
    data = {"entity": object(), "summary": "s", "sql": ["GRANT ..."]}
    res = _svc(notifications_manager=notes).deliver(_payload(data, db=object()), [DeliveryMode.MANUAL]).results[0]
    assert res.success and res.details["notification_id"] == "n1"
    assert "entity" not in notes.created[0]["data"] and notes.created[0]["change_type"] == "policy_release"


def test_file_models_import_and_register_release():
    from src.file_models import FileModelRegistry
    assert FileModelRegistry.get("AccessPolicyRelease") is not None
