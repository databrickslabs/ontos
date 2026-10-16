"""Notification steps send i18n keys for their built-in texts.

The bell shows a notification step's title and message in the user's language
when they are built in: the template's title and message, or a custom message
still as shipped in ``default_workflows.yaml``. The keys are under
``notifications:workflowDefaults``; a text changed here without its locale entry
would silently stay in English, and a locale missing a key would fall back to
English.
"""
import os

os.environ['TESTING'] = 'true'
os.environ['SKIP_STARTUP_TASKS'] = 'true'

import json
import re
from pathlib import Path
from unittest.mock import patch

import pytest
import yaml

from src.common.workflow_executor import (
    _ENTITY_TYPE_LABELS,
    ApprovalStepHandler,
    NotificationStepHandler,
    StepContext,
)
from src.common.workflow_notification_texts import (
    APPROVAL_TITLE,
    DEFAULT_TEMPLATE_MESSAGE,
    DEFAULT_TEMPLATE_TITLE,
    TEMPLATE_MESSAGES,
    TEMPLATE_TITLES,
    placeholders,
    shipped_approval_messages,
    shipped_messages,
)

SRC = Path(__file__).resolve().parents[4]
WORKFLOWS = SRC / 'backend' / 'src' / 'data' / 'default_workflows.yaml'
LOCALES = SRC / 'frontend' / 'src' / 'i18n' / 'locales'
LANGUAGES = ['de', 'en', 'es', 'fr', 'it', 'ja', 'nl', 'pt']
I18N_PLACEHOLDER = re.compile(r'\{\{\s*([^}]+?)\s*\}\}')


def _strings(node, path=()):
    if isinstance(node, str):
        yield '.'.join(path), node
    elif isinstance(node, dict):
        for key, value in node.items():
            yield from _strings(value, (*path, key))


def _locale(lang):
    data = json.loads((LOCALES / lang / 'notifications.json').read_text())
    return dict(_strings(data['workflowDefaults'], ('notifications:workflowDefaults',)))


def _i18next(text):
    """A shipped text as written in the locale: ${variable} becomes {{variable}}."""
    return re.sub(r'\$\{([^}]+)\}', lambda m: '{{' + m.group(1).strip() + '}}', text)


def _shipped(step_type, field):
    workflows = yaml.safe_load(WORKFLOWS.read_text())['workflows']
    return [
        (wf['id'], step['id'], step['config'][field])
        for wf in workflows for step in wf['steps']
        if step.get('type') == step_type and (step.get('config') or {}).get(field)
    ]


def _shipped_notification_messages():
    return _shipped('notification', 'custom_message')


def _shipped_approval_messages():
    return _shipped('approval', 'message')


# --- The locales and the shipped texts -------------------------------------

def test_every_shipped_message_has_its_english_text():
    en = _locale('en')
    messages = _shipped_notification_messages()
    assert messages
    for workflow_id, step_id, text in messages:
        key = shipped_messages()[text]
        assert key == f'notifications:workflowDefaults.messages.{workflow_id}.{step_id}'
        assert en.get(key) == _i18next(text), key


def test_shipped_messages_are_distinct():
    texts = [text for _, _, text in _shipped_notification_messages()]
    assert len(texts) == len(set(texts))


def test_shipped_messages_use_flat_variables():
    # i18next reads a dot in {{a.b}} as a path into the params
    for _, _, text in _shipped_notification_messages():
        assert all('.' not in name for name in placeholders(text)), text


def test_template_texts_have_their_english_text():
    en = _locale('en')
    prefix = 'notifications:workflowDefaults.templates'
    braces = lambda t: t.replace('{entity_type}', '{{entity_type}}').replace('{entity_name}', '{{entity_name}}')
    for template, title in {**TEMPLATE_TITLES, 'default': DEFAULT_TEMPLATE_TITLE}.items():
        assert en.get(f'{prefix}.{template}.title') == title
    for template, message in {**TEMPLATE_MESSAGES, 'default': DEFAULT_TEMPLATE_MESSAGE}.items():
        assert en.get(f'{prefix}.{template}.message') == braces(message)


def test_every_shipped_approval_message_has_its_english_text():
    en = _locale('en')
    messages = _shipped_approval_messages()
    assert messages
    for workflow_id, step_id, text in messages:
        key = shipped_approval_messages()[text]
        assert key == f'notifications:workflowDefaults.approvalMessages.{workflow_id}.{step_id}'
        assert en.get(key) == _i18next(text), key
        assert all('.' not in name for name in placeholders(text)), text


def test_english_has_no_other_texts():
    en = _locale('en')
    expected = set(shipped_messages().values()) | set(shipped_approval_messages().values())
    expected |= {key for key in en if key.startswith('notifications:workflowDefaults.approval.')}
    expected |= {f'notifications:workflowDefaults.templates.{t}.title' for t in [*TEMPLATE_TITLES, 'default']}
    expected |= {f'notifications:workflowDefaults.templates.{t}.message' for t in [*TEMPLATE_MESSAGES, 'default']}
    assert set(en) == expected


@pytest.mark.parametrize('lang', [l for l in LANGUAGES if l != 'en'])
def test_every_language_has_the_same_texts(lang):
    en, other = _locale('en'), _locale(lang)
    assert set(other) == set(en)
    for key, text in other.items():
        assert text.strip(), key
        assert set(I18N_PLACEHOLDER.findall(text)) == set(I18N_PLACEHOLDER.findall(en[key])), key


# --- The notification step -------------------------------------------------

def _context(**overrides):
    values = dict(
        entity={'name': 'orders'}, entity_type='data_contract', entity_id='c-1',
        entity_name='orders', user_email='requester@example.com', trigger_context=None,
        execution_id='ex-1', workflow_id='wf-1', workflow_name='Contract Deploy Request',
        step_results={},
    )
    values.update(overrides)
    return StepContext(**values)


def _sent(db, config, context):
    with patch('src.repositories.notification_repository.notification_repo') as repo:
        result = NotificationStepHandler(db=db, config={'channels': ['in_app'], **config}).execute(context)
    assert result.passed, result.error
    return repo.create.call_args.kwargs['obj_in']


DEPLOY_APPROVED = "Your request to deploy the data contract '${entity_name}' has been approved."


def test_a_shipped_message_is_sent_with_its_key(db_session):
    sent = _sent(db_session, {
        'recipients': 'requester', 'template': 'request_approved', 'custom_message': DEPLOY_APPROVED,
    }, _context())

    assert sent.description == "Your request to deploy the data contract 'orders' has been approved."
    assert sent.data == {'i18n': {
        'title': 'notifications:workflowDefaults.templates.request_approved.title',
        'description': 'notifications:workflowDefaults.messages.contract-deploy-request.notify-approved',
        'params': {'entity_name': 'orders'},
    }}


def test_an_edited_message_is_sent_as_written(db_session):
    sent = _sent(db_session, {
        'recipients': 'requester', 'template': 'request_approved',
        'custom_message': "Deploy of '${entity_name}' approved, see the runbook.",
    }, _context())

    assert sent.description == "Deploy of 'orders' approved, see the runbook."
    # The title is still the template's
    assert sent.data == {'i18n': {'title': 'notifications:workflowDefaults.templates.request_approved.title'}}


def test_a_template_message_is_sent_with_its_key(db_session):
    sent = _sent(db_session, {'recipients': 'requester', 'template': 'request_submitted'},
                 _context(entity_name=None))

    assert sent.description == "Your request for data_contract 'c-1' has been submitted and is pending review."
    assert sent.data == {'i18n': {
        'title': 'notifications:workflowDefaults.templates.request_submitted.title',
        'description': 'notifications:workflowDefaults.templates.request_submitted.message',
        'params': {'entity_type': 'data_contract', 'entity_name': 'c-1'},
    }}


def test_an_unknown_template_uses_the_default_texts(db_session):
    sent = _sent(db_session, {'recipients': 'requester', 'template': 'success'}, _context())

    assert sent.title == 'Workflow Notification'
    assert sent.data['i18n']['title'] == 'notifications:workflowDefaults.templates.default.title'
    assert sent.data['i18n']['description'] == 'notifications:workflowDefaults.templates.default.message'


# --- The approval step's notification ----------------------------------------

def _approval(db, config, context):
    with patch('src.repositories.notification_repository.notification_repo') as repo:
        result = ApprovalStepHandler(db, {'approvers': 'steward@co.com', **config}).execute(context)
    assert result.passed, result.error
    return repo.create.call_args.kwargs['obj_in']


def _access_request(**entity):
    return _context(
        entity_type='access_grant', entity_id='req-1', entity_name='req-1',
        entity={
            'entity_type': 'data_product', 'entity_id': 'p-1', 'entity_name': 'Sales Pipeline',
            'permission_level': 'READ', 'requested_duration_days': 30,
            'reason': 'Quarterly report', **entity,
        },
    )


def _render(text, lang_texts, count=None):
    """A text as i18next renders it, from the given locale texts."""
    key = text.get('key')
    if not key:
        return text['text']
    if count is not None:
        key = f"{key}_{'one' if count == 1 else 'other'}"
    template = lang_texts[key]
    params = {
        name: _render(value, lang_texts) if isinstance(value, dict) else str(value)
        for name, value in (text.get('params') or {}).items()
    }
    return I18N_PLACEHOLDER.sub(lambda m: params[m.group(1)], template)


def _rendered(sent, lang):
    texts = _locale(lang)
    return '\n'.join(
        _render(line, texts, (line.get('params') or {}).get('count'))
        for line in sent.data['i18n']['descriptionLines']
    )


def test_an_approval_is_sent_with_the_keys_of_its_lines(db_session):
    sent = _approval(db_session, {}, _access_request())

    # The stored English texts are as before
    assert sent.title == APPROVAL_TITLE == 'Approval Required'
    assert sent.description == (
        "Requester: requester@example.com\n"
        "Resource: Data Product · Sales Pipeline\n"
        "Permission: READ\n"
        "Duration: 30 days\n"
        "Reason: Quarterly report"
    )
    i18n = sent.data['i18n']
    assert i18n['title'] == 'notifications:workflowDefaults.approval.title'
    assert [line.get('key') for line in i18n['descriptionLines']] == [
        f'notifications:workflowDefaults.approval.lines.{key}'
        for key in ['requester', 'resource', 'permission', 'duration', 'reason']
    ]
    resource = i18n['descriptionLines'][1]['params']
    assert resource['resourceType']['key'] == 'notifications:workflowDefaults.approval.entityTypes.data_product'
    assert resource['resourceName'] == 'Sales Pipeline'
    assert i18n['descriptionLines'][3]['params'] == {'count': 30}

    # English renders the stored description; Portuguese translates the labels
    assert _rendered(sent, 'en') == sent.description
    assert _rendered(sent, 'pt') == (
        "Solicitante: requester@example.com\n"
        "Recurso: Produto de dados · Sales Pipeline\n"
        "Permissão: READ\n"
        "Duração: 30 dias\n"
        "Motivo: Quarterly report"
    )


def test_a_shipped_approval_message_is_translated(db_session):
    workflow_id, step_id, message = _shipped_approval_messages()[0]
    assert workflow_id == 'certification-request-review'
    context = _context(entity_type='data_product', entity_id='p-1', entity_name='Sales Pipeline')
    sent = _approval(db_session, {'message': message}, context)

    line = sent.data['i18n']['descriptionLines'][-1]
    assert line['text'] == (
        "Workflow message: Please review the certification request for data_product 'Sales Pipeline'."
    )
    assert line['params']['message']['key'] == (
        f'notifications:workflowDefaults.approvalMessages.{workflow_id}.{step_id}'
    )
    assert line['params']['message']['params'] == {'entity_type': 'data_product', 'entity_name': 'Sales Pipeline'}
    assert _rendered(sent, 'en') == sent.description
    assert _rendered(sent, 'pt').endswith(
        "Mensagem do workflow: Revise a solicitação de certificação de data_product 'Sales Pipeline'."
    )


def test_an_edited_approval_message_is_shown_as_written(db_session):
    context = _context(entity_type='data_product', entity_id='p-1', entity_name='Sales Pipeline')
    sent = _approval(db_session, {'message': "Check '${entity_name}' against the runbook."}, context)

    line = sent.data['i18n']['descriptionLines'][-1]
    assert line['params'] == {'message': "Check 'Sales Pipeline' against the runbook."}
    assert _rendered(sent, 'pt').endswith(
        "Mensagem do workflow: Check 'Sales Pipeline' against the runbook."
    )


def test_an_unknown_requester_and_unknown_lines(db_session):
    context = _context(
        entity_type='data_contract', entity_id='c-1', entity_name='orders', user_email=None,
        entity={'name': 'orders', 'justification': 'Needed for the audit'},
    )
    sent = _approval(db_session, {}, context)

    assert sent.description == (
        "Requester: Unknown\nResource: Data Contract · orders\nJustification: Needed for the audit"
    )
    assert _rendered(sent, 'en') == sent.description
    assert _rendered(sent, 'pt') == (
        "Solicitante: Desconhecido\nRecurso: Contrato de dados · orders\n"
        "Justificativa: Needed for the audit"
    )


def test_every_entity_type_label_has_its_english_text():
    en = _locale('en')
    for entity_type, label in {**_ENTITY_TYPE_LABELS, 'entity': 'Entity'}.items():
        assert en.get(f'notifications:workflowDefaults.approval.entityTypes.{entity_type}') == label
