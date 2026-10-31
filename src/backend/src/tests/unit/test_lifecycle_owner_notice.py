"""The owner lifecycle notices (#998): their texts and the payload they read.

The ``entity_deprecated`` / ``entity_retired`` templates of a notification step
send one line per fact (the template's message, then the reason, the sunset
date and the replacement when set), each with its i18n key and params. The
on_status_change payload of a deprecation or retirement carries those fields
(``lifecycle_trigger_data``).
"""
import os

os.environ['TESTING'] = 'true'
os.environ['SKIP_STARTUP_TASKS'] = 'true'

import json
import re
from datetime import date
from pathlib import Path
from unittest.mock import patch
from uuid import uuid4

import pytest

from src.common.workflow_executor import NotificationStepHandler, StepContext
from src.controller.lifecycle_fields import lifecycle_trigger_data
from src.db_models.data_contracts import DataContractDb
from src.db_models.data_products import DataProductDb

LOCALES = Path(__file__).resolve().parents[4] / 'frontend' / 'src' / 'i18n' / 'locales'
LANGUAGES = ['de', 'en', 'es', 'fr', 'it', 'ja', 'nl', 'pt']
PLACEHOLDER = re.compile(r'\{\{\s*([^}]+?)\s*\}\}')

DEPRECATED = {
    'name': 'Orders', 'status': 'deprecated', 'deprecation_reason': 'Superseded',
    'sunset_date': '2026-12-31', 'replacement_id': 'p-2', 'replacement_name': 'Orders v2',
}


def _strings(node, path=()):
    if isinstance(node, str):
        yield '.'.join(path), node
    elif isinstance(node, dict):
        for key, value in node.items():
            yield from _strings(value, (*path, key))


def _texts(lang):
    data = json.loads((LOCALES / lang / 'notifications.json').read_text())
    return {f'notifications:{key}': text for key, text in _strings(data)}


def _rendered(sent, lang):
    texts = _texts(lang)
    return '\n'.join(
        PLACEHOLDER.sub(lambda m: str(line['params'][m.group(1)]), texts[line['key']])
        for line in sent.data['i18n']['descriptionLines']
    )


def _sent(db, template, entity, **config):
    context = StepContext(
        entity=entity, entity_type='data_product', entity_id='p-1', entity_name='Orders',
        user_email='steward@example.com', trigger_context=None, execution_id='ex-1',
        workflow_id='wf-1', workflow_name='Owner Deprecation Notice', step_results={},
    )
    handler = NotificationStepHandler(
        db=db, config={'channels': ['in_app'], 'recipients': 'owner@example.com',
                       'template': template, **config},
    )
    with patch('src.repositories.notification_repository.notification_repo') as repo:
        result = handler.execute(context)
    assert result.passed, result.error
    return repo.create.call_args.kwargs['obj_in']


def test_a_deprecation_notice_has_a_line_per_field(db_session):
    sent = _sent(db_session, 'entity_deprecated', DEPRECATED)

    assert sent.title == 'Deprecation Notice'
    assert sent.type == 'warning'
    assert sent.description == (
        "data_product 'Orders' has been deprecated.\nReason: Superseded\n"
        "Sunset date: 2026-12-31\nReplacement: Orders v2"
    )
    i18n = sent.data['i18n']
    assert i18n['title'] == 'notifications:workflowDefaults.templates.entity_deprecated.title'
    assert [(line['key'], line['params']) for line in i18n['descriptionLines']] == [
        ('notifications:workflowDefaults.templates.entity_deprecated.message',
         {'entity_type': 'data_product', 'entity_name': 'Orders'}),
        ('notifications:lifecycle.ownerNotice.reason', {'reason': 'Superseded'}),
        ('notifications:lifecycle.ownerNotice.sunsetDate', {'sunsetDate': '2026-12-31'}),
        ('notifications:lifecycle.ownerNotice.replacement',
         {'replacementName': 'Orders v2', 'replacementId': 'p-2'}),
    ]
    # The English texts of the keys are the stored ones
    assert _rendered(sent, 'en') == sent.description
    assert _rendered(sent, 'pt') == (
        "data_product 'Orders' foi marcado como obsoleto.\nMotivo: Superseded\n"
        "Data de desativação: 2026-12-31\nSubstituto: Orders v2"
    )


def test_a_retirement_notice_leaves_out_what_is_not_set(db_session):
    sent = _sent(db_session, 'entity_retired', {'name': 'Orders', 'status': 'retired'})

    assert sent.title == 'Retirement Notice'
    assert sent.description == "data_product 'Orders' has been retired."
    assert len(sent.data['i18n']['descriptionLines']) == 1


def test_a_custom_message_replaces_the_lines(db_session):
    sent = _sent(
        db_session, 'entity_deprecated', DEPRECATED,
        custom_message="'${entity_name}' is going away: ${entity.deprecation_reason}",
    )

    assert sent.description == "'Orders' is going away: Superseded"
    assert 'descriptionLines' not in sent.data['i18n']


@pytest.mark.parametrize('lang', LANGUAGES)
def test_every_language_has_the_lines_with_their_placeholders(lang):
    en, other = _texts('en'), _texts(lang)
    keys = [key for key in en if key.startswith('notifications:lifecycle.ownerNotice.')]
    assert len(keys) == 3
    for key in keys:
        assert other.get(key, '').strip(), key
        assert set(PLACEHOLDER.findall(other[key])) == set(PLACEHOLDER.findall(en[key])), key


# --- The on_status_change payload ---------------------------------------------

def _product(db, **values):
    product = DataProductDb(id=str(uuid4()), **{'name': 'Orders', **values})
    db.add(product)
    db.flush()
    return product


def test_the_payload_of_a_deprecation_and_a_retirement(db_session):
    replacement = _product(db_session, status='active', name='Orders v2')
    product = _product(
        db_session, status='retired', deprecation_reason='Superseded',
        sunset_date=date(2026, 12, 31), replacement_product_id=replacement.id,
    )

    for status in ('deprecated', 'retired'):
        assert lifecycle_trigger_data(db_session, 'data_product', product, status) == {
            'deprecation_reason': 'Superseded', 'sunset_date': '2026-12-31',
            'replacement_product_id': replacement.id,
            'replacement_id': replacement.id, 'replacement_name': 'Orders v2',
        }


def test_no_payload_for_other_statuses(db_session):
    product = _product(db_session, status='active', deprecation_reason='Old reason')

    assert lifecycle_trigger_data(db_session, 'data_product', product, 'active') == {}


def test_a_contract_payload_and_a_missing_replacement(db_session):
    contract = DataContractDb(
        id=str(uuid4()), name='orders', version='1.0.0', status='deprecated',
        version_family_id=str(uuid4()), deprecation_reason='Superseded',
        replacement_contract_id='gone',
    )
    db_session.add(contract)
    db_session.flush()

    assert lifecycle_trigger_data(db_session, 'data_contract', contract, 'deprecated') == {
        'deprecation_reason': 'Superseded', 'sunset_date': None,
        'replacement_contract_id': 'gone',
        'replacement_id': 'gone', 'replacement_name': 'gone',
    }
