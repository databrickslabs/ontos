# Set test environment variables BEFORE any app imports
import os
os.environ['TESTING'] = 'true'
os.environ['SKIP_STARTUP_TASKS'] = 'true'

import pytest
from pathlib import Path
from unittest.mock import MagicMock, patch

from src.common.workflow_triggers import TriggerRegistry
from src.models.process_workflows import (
    TriggerType,
    EntityType,
    ExecutionStatus,
    WorkflowExecution,
)


def _make_execution(status: ExecutionStatus, step_results=None) -> MagicMock:
    """Create a mock WorkflowExecution."""
    exe = MagicMock(spec=WorkflowExecution)
    exe.status = status
    exe.step_results = step_results or {}
    exe.current_step_id = 'step-1'
    return exe


# =========================================================================
# 1. TriggerRegistry.on_publish() — fires correct trigger type
# =========================================================================

class TestOnPublishTrigger:
    """on_publish fires ON_PUBLISH with correct entity data and is non-blocking by default."""

    def test_on_publish_fires_correct_trigger_type(self, db_session):
        """on_publish must create a TriggerEvent with TriggerType.ON_PUBLISH."""
        registry = TriggerRegistry(db=db_session)

        with patch.object(registry, 'fire_trigger', return_value=[]) as mock_fire:
            registry.on_publish(
                entity_type=EntityType.DATA_PRODUCT,
                entity_id='prod-1',
                entity_name='My Product',
                entity_data={'name': 'My Product', 'status': 'active'},
                user_email='owner@example.com',
            )

        event = mock_fire.call_args[0][0]
        assert event.trigger_type == TriggerType.ON_PUBLISH
        assert event.entity_type == EntityType.DATA_PRODUCT
        assert event.entity_id == 'prod-1'
        assert event.entity_name == 'My Product'
        assert event.user_email == 'owner@example.com'

    def test_on_publish_is_non_blocking_by_default(self, db_session):
        """on_publish must default to blocking=False (non-blocking / fire-and-forget)."""
        registry = TriggerRegistry(db=db_session)

        with patch.object(registry, 'fire_trigger', return_value=[]) as mock_fire:
            registry.on_publish(
                entity_type=EntityType.DATA_PRODUCT,
                entity_id='prod-1',
            )

        assert mock_fire.call_args[1]['blocking'] is False

    def test_on_publish_can_be_called_blocking(self, db_session):
        """on_publish accepts blocking=True override."""
        registry = TriggerRegistry(db=db_session)

        with patch.object(registry, 'fire_trigger', return_value=[]) as mock_fire:
            registry.on_publish(
                entity_type=EntityType.DATA_CONTRACT,
                entity_id='contract-1',
                blocking=True,
            )

        assert mock_fire.call_args[1]['blocking'] is True

    def test_on_publish_returns_executions(self, db_session):
        """on_publish returns the list of WorkflowExecution objects from fire_trigger."""
        registry = TriggerRegistry(db=db_session)
        mock_execs = [
            _make_execution(ExecutionStatus.SUCCEEDED),
        ]

        with patch.object(registry, 'fire_trigger', return_value=mock_execs):
            result = registry.on_publish(
                entity_type=EntityType.DATA_PRODUCT,
                entity_id='prod-1',
            )

        assert result == mock_execs
        assert len(result) == 1

    def test_on_publish_passes_entity_data(self, db_session):
        """on_publish forwards entity_data into the TriggerEvent."""
        registry = TriggerRegistry(db=db_session)
        data = {'name': 'Product X', 'status': 'active', 'version': '2.0'}

        with patch.object(registry, 'fire_trigger', return_value=[]) as mock_fire:
            registry.on_publish(
                entity_type=EntityType.DATA_PRODUCT,
                entity_id='prod-x',
                entity_data=data,
            )

        event = mock_fire.call_args[0][0]
        assert event.entity_data == data


# =========================================================================
# 2. TriggerRegistry.on_unpublish() — fires correct trigger type
# =========================================================================

class TestOnUnpublishTrigger:
    """on_unpublish fires ON_UNPUBLISH with correct entity data and is non-blocking by default."""

    def test_on_unpublish_fires_correct_trigger_type(self, db_session):
        """on_unpublish must create a TriggerEvent with TriggerType.ON_UNPUBLISH."""
        registry = TriggerRegistry(db=db_session)

        with patch.object(registry, 'fire_trigger', return_value=[]) as mock_fire:
            registry.on_unpublish(
                entity_type=EntityType.DATA_CONTRACT,
                entity_id='contract-1',
                entity_name='My Contract',
                entity_data={'name': 'My Contract', 'status': 'draft'},
                user_email='admin@example.com',
            )

        event = mock_fire.call_args[0][0]
        assert event.trigger_type == TriggerType.ON_UNPUBLISH
        assert event.entity_type == EntityType.DATA_CONTRACT
        assert event.entity_id == 'contract-1'
        assert event.entity_name == 'My Contract'
        assert event.user_email == 'admin@example.com'

    def test_on_unpublish_is_non_blocking_by_default(self, db_session):
        """on_unpublish must default to blocking=False."""
        registry = TriggerRegistry(db=db_session)

        with patch.object(registry, 'fire_trigger', return_value=[]) as mock_fire:
            registry.on_unpublish(
                entity_type=EntityType.DATA_PRODUCT,
                entity_id='prod-1',
            )

        assert mock_fire.call_args[1]['blocking'] is False

    def test_on_unpublish_can_be_called_blocking(self, db_session):
        """on_unpublish accepts blocking=True override."""
        registry = TriggerRegistry(db=db_session)

        with patch.object(registry, 'fire_trigger', return_value=[]) as mock_fire:
            registry.on_unpublish(
                entity_type=EntityType.DATA_PRODUCT,
                entity_id='prod-1',
                blocking=True,
            )

        assert mock_fire.call_args[1]['blocking'] is True

    def test_on_unpublish_returns_executions(self, db_session):
        """on_unpublish returns the list of WorkflowExecution objects."""
        registry = TriggerRegistry(db=db_session)
        mock_execs = [
            _make_execution(ExecutionStatus.SUCCEEDED),
            _make_execution(ExecutionStatus.SUCCEEDED),
        ]

        with patch.object(registry, 'fire_trigger', return_value=mock_execs):
            result = registry.on_unpublish(
                entity_type=EntityType.DATA_CONTRACT,
                entity_id='contract-1',
            )

        assert result == mock_execs
        assert len(result) == 2


# =========================================================================
# 3. Default YAML workflows exist for on-publish and on-unpublish
# =========================================================================

class TestDefaultPublishWorkflowsYAML:
    """Default YAML workflow definitions must include publish/unpublish notifications."""

    def test_on_publish_notification_workflow_exists(self):
        """default_workflows.yaml must contain on-publish-notification workflow."""
        import yaml

        yaml_path = Path(__file__).resolve().parents[2] / 'data' / 'default_workflows.yaml'
        assert yaml_path.exists(), f"default_workflows.yaml not found at {yaml_path}"

        with open(yaml_path) as f:
            data = yaml.safe_load(f)

        workflows = data.get('workflows', data) if isinstance(data, dict) else data
        workflow_ids = [w['id'] for w in workflows]
        assert 'on-publish-notification' in workflow_ids, (
            "Missing 'on-publish-notification' in default_workflows.yaml"
        )

        # Verify trigger type
        wf = next(w for w in workflows if w['id'] == 'on-publish-notification')
        assert wf['trigger']['type'] == 'on_publish'
        assert wf['is_active'] is True
        assert wf['is_default'] is True

    def test_on_unpublish_notification_workflow_exists(self):
        """default_workflows.yaml must contain on-unpublish-notification workflow."""
        import yaml

        yaml_path = Path(__file__).resolve().parents[2] / 'data' / 'default_workflows.yaml'
        with open(yaml_path) as f:
            data = yaml.safe_load(f)

        workflows = data.get('workflows', data) if isinstance(data, dict) else data
        workflow_ids = [w['id'] for w in workflows]
        assert 'on-unpublish-notification' in workflow_ids, (
            "Missing 'on-unpublish-notification' in default_workflows.yaml"
        )

        wf = next(w for w in workflows if w['id'] == 'on-unpublish-notification')
        assert wf['trigger']['type'] == 'on_unpublish'
        assert wf['is_active'] is True
        assert wf['is_default'] is True

    def test_publish_workflows_cover_data_product_and_contract(self):
        """Both publish workflows should apply to data_product and data_contract entity types."""
        import yaml

        yaml_path = Path(__file__).resolve().parents[2] / 'data' / 'default_workflows.yaml'
        with open(yaml_path) as f:
            data = yaml.safe_load(f)

        workflows = data.get('workflows', data) if isinstance(data, dict) else data
        for wf_id in ('on-publish-notification', 'on-unpublish-notification'):
            wf = next(w for w in workflows if w['id'] == wf_id)
            entity_types = wf['trigger'].get('entity_types', [])
            assert 'data_product' in entity_types, f"{wf_id} missing data_product entity type"
            assert 'data_contract' in entity_types, f"{wf_id} missing data_contract entity type"


# =========================================================================
# 4. Backend TriggerType enum contains ON_PUBLISH and ON_UNPUBLISH
# =========================================================================

class TestTriggerTypeEnum:
    """TriggerType enum must include the publish/unpublish values."""

    def test_on_publish_in_trigger_type(self):
        assert hasattr(TriggerType, 'ON_PUBLISH')
        assert TriggerType.ON_PUBLISH.value == 'on_publish'

    def test_on_unpublish_in_trigger_type(self):
        assert hasattr(TriggerType, 'ON_UNPUBLISH')
        assert TriggerType.ON_UNPUBLISH.value == 'on_unpublish'


# =========================================================================
# 5. Frontend types include on_publish and on_unpublish (grep-based)
# =========================================================================

class TestFrontendTypes:
    """Frontend TypeScript types must include on_publish and on_unpublish."""

    def test_frontend_trigger_type_includes_on_publish(self):
        """process-workflow.ts TriggerType union must contain 'on_publish'."""
        ts_path = (
            Path(__file__).resolve().parents[4]
            / 'frontend' / 'src' / 'types' / 'process-workflow.ts'
        )
        assert ts_path.exists(), f"Frontend types file not found at {ts_path}"
        content = ts_path.read_text()
        assert "'on_publish'" in content, "on_publish missing from frontend TriggerType"

    def test_frontend_trigger_type_includes_on_unpublish(self):
        """process-workflow.ts TriggerType union must contain 'on_unpublish'."""
        ts_path = (
            Path(__file__).resolve().parents[4]
            / 'frontend' / 'src' / 'types' / 'process-workflow.ts'
        )
        content = ts_path.read_text()
        assert "'on_unpublish'" in content, "on_unpublish missing from frontend TriggerType"

    def test_frontend_workflow_labels_includes_publish_types(self):
        """workflow-labels.ts ALL_TRIGGER_TYPES must contain on_publish and on_unpublish."""
        ts_path = (
            Path(__file__).resolve().parents[4]
            / 'frontend' / 'src' / 'lib' / 'workflow-labels.ts'
        )
        assert ts_path.exists(), f"workflow-labels.ts not found at {ts_path}"
        content = ts_path.read_text()
        assert "'on_publish'" in content, "on_publish missing from workflow-labels.ts"
        assert "'on_unpublish'" in content, "on_unpublish missing from workflow-labels.ts"
