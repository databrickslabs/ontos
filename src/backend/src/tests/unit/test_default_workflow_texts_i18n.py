"""The user-facing texts of the default workflows have translations.

The UI translates a default workflow's wizard texts (user_action step name,
title, description and field labels) and the messages of its fail steps (an
execution's error) while they are exactly the shipped English text, which it
finds in the ``workflowDefaults`` namespace of the English locale. A text changed here without its locale entry would silently stay in
English; a locale missing a key would fall back to English.
"""
import json
from pathlib import Path

import pytest
import yaml

SRC = Path(__file__).resolve().parents[4]
WORKFLOWS = SRC / 'backend' / 'src' / 'data' / 'default_workflows.yaml'
LOCALES = SRC / 'frontend' / 'src' / 'i18n' / 'locales'
LANGUAGES = ['de', 'en', 'es', 'fr', 'it', 'ja', 'nl', 'pt']


def _strings(node, path=()):
    if isinstance(node, str):
        yield '.'.join(path), node
    elif isinstance(node, dict):
        for key, value in node.items():
            yield from _strings(value, (*path, key))


def _locale(lang):
    return dict(_strings(json.loads((LOCALES / lang / 'workflowDefaults.json').read_text())))


def _wizard_texts():
    for workflow in yaml.safe_load(WORKFLOWS.read_text())['workflows']:
        for step in workflow.get('steps') or []:
            if step.get('type') != 'user_action':
                continue
            if step.get('name'):
                yield workflow['id'], step['name']
            config = step.get('config') or {}
            for field in ('title', 'description'):
                if config.get(field):
                    yield workflow['id'], config[field]
            for required in config.get('required_fields') or []:
                if required.get('label'):
                    yield workflow['id'], required['label']


def _fail_messages():
    for workflow in yaml.safe_load(WORKFLOWS.read_text())['workflows']:
        for step in workflow.get('steps') or []:
            if step.get('type') == 'fail' and (step.get('config') or {}).get('message'):
                yield workflow['id'], step['config']['message']


def test_every_fail_message_of_the_default_workflows_has_an_entry():
    english = set(_locale('en').values())
    missing = [(wf, text) for wf, text in _fail_messages() if text.strip() not in english]

    assert list(_fail_messages())
    assert missing == []


def test_no_two_entries_have_the_same_english_text():
    # The UI finds a text's key by its English text: a duplicate would hide one
    texts = list(_locale('en').values())

    assert len(texts) == len(set(texts))


def test_every_wizard_text_of_the_default_workflows_has_an_entry():
    english = set(_locale('en').values())
    missing = [(wf, text) for wf, text in _wizard_texts() if text.strip() not in english]

    assert list(_wizard_texts())
    assert missing == []


@pytest.mark.parametrize('lang', [lang for lang in LANGUAGES if lang != 'en'])
def test_every_language_has_the_same_keys_and_no_empty_text(lang):
    english, other = _locale('en'), _locale(lang)

    assert set(other) == set(english)
    assert all(value.strip() for value in other.values())
