"""``request_uc_tag_sync_after_transition`` runs after the commit, so it never raises."""
from src.common import uc_tag_sync_trigger


def test_a_failing_stage_lookup_requests_nothing_and_does_not_raise(monkeypatch):
    def broken():
        raise RuntimeError("database unavailable")

    monkeypatch.setattr(uc_tag_sync_trigger, '_on_demand_statuses', broken)

    assert uc_tag_sync_trigger.request_uc_tag_sync_after_transition(
        'data_product', 'p1', 'active', 'deprecated',
    ) is None


def test_no_change_requests_nothing_without_a_lookup(monkeypatch):
    def unexpected():
        raise AssertionError("no lookup for an unchanged status")

    monkeypatch.setattr(uc_tag_sync_trigger, '_on_demand_statuses', unexpected)

    assert uc_tag_sync_trigger.request_uc_tag_sync_after_transition(
        'data_product', 'p1', 'Active', 'active',
    ) is None
