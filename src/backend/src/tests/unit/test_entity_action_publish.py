"""entity_action publish re-checks the live entity status before publishing,
and fires on_publish / on_unpublish when the publication changes."""
import os

os.environ['TESTING'] = 'true'
os.environ['SKIP_STARTUP_TASKS'] = 'true'

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from src.common.workflow_executor import EntityActionStepHandler, StepContext


def _publish(entity_type, status, config=None, registry=None, **published):
    db = MagicMock()
    entity = SimpleNamespace(
        name='E', status=status, publication_scope='none', published_at=None, published_by=None,
    )
    for name, value in published.items():
        setattr(entity, name, value)
    handler = EntityActionStepHandler(db, config or {'action': 'publish', 'scope_source': 'from_request'})
    context = StepContext(
        entity={'requested_scope': 'organization'},
        entity_type=entity_type,
        entity_id='e-1',
        entity_name='E',
        user_email='steward@example.com',
        trigger_context=None,
        execution_id='x-1',
        workflow_id='w-1',
        workflow_name='Publication Request Review',
        step_results={},
    )
    lookup = patch.object(
        EntityActionStepHandler, '_get_db_entity', return_value=(entity, entity_type),
    )
    triggers = patch(
        'src.common.workflow_triggers.get_trigger_registry', return_value=registry or MagicMock(),
    )
    with lookup, triggers:
        result = handler.execute(context)
    return result, entity, db


@pytest.mark.parametrize('entity_type, status', [
    ('data_product', 'active'),
    ('data_product', 'ACTIVE'),
    ('data_contract', 'approved'),
    ('data_contract', 'active'),
])
def test_publishable_entities_are_published(entity_type, status):
    result, entity, db = _publish(entity_type, status)

    assert result.passed is True, result.error
    assert entity.publication_scope == 'organization'
    assert entity.published_at is not None
    assert entity.published_by == 'steward@example.com'
    db.commit.assert_called_once()


@pytest.mark.parametrize('entity_type, status', [
    ('data_product', 'deprecated'),
    ('data_product', 'approved'),
    ('data_contract', 'draft'),
    ('data_contract', 'retired'),
])
def test_entities_that_changed_status_since_the_request_are_not_published(entity_type, status):
    result, entity, db = _publish(entity_type, status)

    assert result.passed is False
    assert f"in status '{status}'" in result.error
    assert entity.publication_scope == 'none'
    db.commit.assert_not_called()


def test_setting_scope_none_is_allowed_in_any_status():
    config = {'action': 'set_publication_scope', 'scope_source': 'fixed', 'fixed_scope': 'none'}

    result, entity, _ = _publish('data_product', 'deprecated', config)

    assert result.passed is True, result.error
    assert entity.publication_scope == 'none'


def test_setting_scope_none_clears_the_publication_metadata():
    config = {'action': 'set_publication_scope', 'scope_source': 'fixed', 'fixed_scope': 'none'}

    result, entity, _ = _publish(
        'data_product', 'deprecated', config, publication_scope='organization',
        published_at='2026-01-01T00:00:00Z', published_by='publisher@example.com',
    )

    assert result.passed is True, result.error
    assert entity.publication_scope == 'none'
    assert entity.published_at is None
    assert entity.published_by is None


# --- on_publish / on_unpublish -----------------------------------------------

_UNPUBLISH = {'action': 'set_publication_scope', 'scope_source': 'fixed', 'fixed_scope': 'none'}


@pytest.mark.parametrize('entity_type', ['data_product', 'data_contract'])
def test_publishing_fires_on_publish_once(entity_type):
    from src.models.process_workflows import EntityType

    registry = MagicMock()
    status = 'active'
    result, _, _ = _publish(entity_type, status, registry=registry)

    assert result.passed is True, result.error
    registry.on_publish.assert_called_once()
    kwargs = registry.on_publish.call_args.kwargs
    assert kwargs['entity_type'] == EntityType(entity_type)
    assert kwargs['entity_id'] == 'e-1'
    assert kwargs['entity_data']['publication_scope'] == 'organization'
    assert kwargs['user_email'] == 'steward@example.com'
    registry.on_unpublish.assert_not_called()


def test_changing_the_scope_of_a_published_entity_fires_nothing():
    registry = MagicMock()
    result, entity, _ = _publish(
        'data_product', 'active', registry=registry, publication_scope='domain',
    )

    assert result.passed is True, result.error
    assert entity.publication_scope == 'organization'
    registry.on_publish.assert_not_called()
    registry.on_unpublish.assert_not_called()


def test_unpublishing_fires_on_unpublish_only_when_it_was_published():
    published = MagicMock()
    _publish('data_contract', 'active', _UNPUBLISH, registry=published,
             publication_scope='organization')
    not_published = MagicMock()
    _publish('data_contract', 'active', _UNPUBLISH, registry=not_published)

    published.on_unpublish.assert_called_once()
    assert published.on_unpublish.call_args.args[1] == 'e-1'
    published.on_publish.assert_not_called()
    not_published.on_unpublish.assert_not_called()


def test_no_trigger_when_the_publication_is_refused():
    registry = MagicMock()
    result, _, _ = _publish('data_product', 'deprecated', registry=registry)

    assert result.passed is False
    registry.on_publish.assert_not_called()


def test_a_trigger_error_keeps_the_publication_and_is_logged_as_an_error(caplog):
    registry = MagicMock()
    registry.on_publish.side_effect = RuntimeError('workflow engine down')

    with caplog.at_level('ERROR'):
        result, entity, db = _publish('data_product', 'active', registry=registry)

    assert result.passed is True, result.error
    assert entity.publication_scope == 'organization'
    db.commit.assert_called_once()
    assert any('Publication trigger failed' in r.getMessage() and r.levelname == 'ERROR'
               for r in caplog.records)
    # The step result says the workflows didn't run
    assert result.data['trigger_failed'] == 'on_publish'
    assert 'the on_publish workflows did not run' in result.message


def test_a_publication_whose_trigger_ran_reports_no_failure():
    result, _, _ = _publish('data_product', 'active', registry=MagicMock())

    assert 'trigger_failed' not in result.data
    assert result.message == 'Published with scope organization'


def test_assets_have_no_publication_trigger():
    registry = MagicMock()
    result, _, _ = _publish('asset', 'active', registry=registry)

    assert result.passed is True, result.error
    registry.on_publish.assert_not_called()
