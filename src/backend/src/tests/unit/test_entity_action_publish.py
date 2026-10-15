"""entity_action publish re-checks the live entity status before publishing."""
import os

os.environ['TESTING'] = 'true'
os.environ['SKIP_STARTUP_TASKS'] = 'true'

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from src.common.workflow_executor import EntityActionStepHandler, StepContext


def _publish(entity_type, status, config=None, **published):
    db = MagicMock()
    entity = SimpleNamespace(status=status, publication_scope='none', published_at=None, published_by=None)
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
    with patch.object(EntityActionStepHandler, '_get_db_entity', return_value=(entity, entity_type)):
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
