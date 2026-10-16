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

from src.common.workflow_executor import NotificationStepHandler, StepContext
from src.common.workflow_notification_texts import (
    DEFAULT_TEMPLATE_MESSAGE,
    DEFAULT_TEMPLATE_TITLE,
    TEMPLATE_MESSAGES,
    TEMPLATE_TITLES,
    placeholders,
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


def _shipped_notification_messages():
    workflows = yaml.safe_load(WORKFLOWS.read_text())['workflows']
    return [
        (wf['id'], step['id'], step['config']['custom_message'])
        for wf in workflows for step in wf['steps']
        if step.get('type') == 'notification' and (step.get('config') or {}).get('custom_message')
    ]


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


def test_english_has_no_other_texts():
    en = _locale('en')
    expected = set(shipped_messages().values())
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
