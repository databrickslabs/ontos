"""Texts and i18n keys of the status change decision notices (#1321)."""
import pytest

from src.common.workflow_notification_texts import (
    STATUS_CHANGE_DECISION_TEMPLATES, status_change_decision_notice,
)

RESULTS = [
    {'passed': True, 'decision': 'approved', 'message': 'Earlier approval'},
    {'passed': False, 'decision': 'rejected', 'message': 'Denied reason'},
    {'passed': False, 'decision': 'clarify', 'message': 'Which region?'},
]


def _notice(template, results=RESULTS, entity_type='data_product'):
    return status_change_decision_notice(
        template, entity_type, 'Decision Product', 'p-1', 'proposed',
        'steward@example.com', results,
    )


@pytest.mark.parametrize('template, title, expected_step_value', [
    ('status_change_approved', 'Status Change Approved', 'approved'),
    ('status_change_denied', 'Status Change Denied', 'rejected'),
    ('status_change_clarification', 'Status Change - Clarification Needed', 'clarify'),
])
def test_each_decision_template_names_its_title_and_message(
    template, title, expected_step_value,
):
    results = [{'decision': expected_step_value, 'message': 'The message'}]

    built_title, text, data = _notice(template, results)

    assert built_title == title
    assert "'Decision Product' to 'proposed'" in text
    assert "'steward@example.com'" in text
    assert text.endswith('Approver message: The message')
    assert data['i18n']['params']['message'] == 'The message'


def test_the_message_is_the_decision_of_this_notice_not_another_one():
    _, text, data = _notice('status_change_denied')

    assert text.endswith('Approver message: Denied reason')
    assert 'Earlier approval' not in text
    assert data['i18n']['params']['approver'] == 'steward@example.com'


def test_without_a_message_the_text_has_no_message_line_and_the_base_key():
    _, text, data = _notice('status_change_approved', results=[{'decision': 'approved'}])

    assert 'Approver message' not in text
    assert data['i18n']['description'] == 'notifications:statusChangeDecision.approved'
    assert data['i18n']['title'] == 'notifications:statusChangeDecision.approvedTitle'
    assert 'message' not in data['i18n']['params']


def test_the_keys_and_namespace_of_the_frontend_translation():
    _, _, data = _notice('status_change_approved')

    assert data['i18n']['title'] == 'notifications:statusChangeDecision.approvedTitle'
    assert data['i18n']['description'] == 'notifications:statusChangeDecision.approvedWithMessage'
    assert data['i18n']['statusNamespace'] == 'data-products'
    assert data['i18n']['params'] == {
        'name': 'Decision Product', 'toStatus': 'proposed',
        'approver': 'steward@example.com', 'message': 'Earlier approval',
    }


def test_contracts_use_the_contract_status_labels():
    _, _, data = _notice('status_change_denied', entity_type='data_contract')

    assert data['i18n']['statusNamespace'] == 'data-contracts'


def test_a_custom_template_is_not_a_decision_notice():
    assert status_change_decision_notice(
        'request_approved', 'data_product', 'P', 'p-1', 'proposed', 'a@b.c', RESULTS,
    ) is None
    assert set(STATUS_CHANGE_DECISION_TEMPLATES) == {
        'status_change_approved', 'status_change_denied', 'status_change_clarification',
    }


def test_the_denied_message_survives_a_callers_own_decision_text():
    # Callers send 'denied' / 'cancelled' as the decision; the outcome is the executor's
    results = [{'outcome': 'rejected', 'decision': 'denied', 'message': 'Not now'}]

    _, text, _ = _notice('status_change_denied', results)

    assert text.endswith('Approver message: Not now')
