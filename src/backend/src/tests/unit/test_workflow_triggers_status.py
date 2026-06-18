# Set test environment variables BEFORE any app imports
import os
os.environ['TESTING'] = 'true'
os.environ['SKIP_STARTUP_TASKS'] = 'true'

import pytest
from unittest.mock import MagicMock, patch, PropertyMock

from src.common.workflow_triggers import TriggerRegistry
from src.models.process_workflows import (
    TriggerType,
    EntityType,
    ExecutionStatus,
    WorkflowExecution,
)
from src.common.workflow_executor import StepContext


def _make_execution(status: ExecutionStatus, step_results=None) -> MagicMock:
    """Create a mock WorkflowExecution."""
    exe = MagicMock(spec=WorkflowExecution)
    exe.status = status
    exe.step_results = step_results or {}
    exe.current_step_id = 'step-1'
    return exe


# =========================================================================
# TriggerRegistry.before_status_change() — User Stories 1, 2
# =========================================================================

class TestBeforeStatusChange:
    """US1/2: Workflows can gate status transitions."""

    def test_before_status_change_returns_true_when_no_workflows(self, db_session):
        """No matching workflows → all_passed=True, empty executions."""
        registry = TriggerRegistry(db=db_session)

        with patch.object(registry, 'fire_trigger', return_value=[]):
            all_passed, executions = registry.before_status_change(
                entity_type=EntityType.DATA_PRODUCT,
                entity_id='prod-1',
                from_status='draft',
                to_status='active',
            )

        assert all_passed is True
        assert executions == []

    def test_before_status_change_returns_true_when_all_succeed(self, db_session):
        """All workflows pass → all_passed=True."""
        registry = TriggerRegistry(db=db_session)
        mock_execs = [
            _make_execution(ExecutionStatus.SUCCEEDED),
            _make_execution(ExecutionStatus.SUCCEEDED),
        ]

        with patch.object(registry, 'fire_trigger', return_value=mock_execs):
            all_passed, executions = registry.before_status_change(
                entity_type=EntityType.DATA_PRODUCT,
                entity_id='prod-1',
                from_status='approved',
                to_status='active',
            )

        assert all_passed is True
        assert len(executions) == 2

    def test_before_status_change_returns_false_when_any_fail(self, db_session):
        """Any workflow fails → all_passed=False."""
        registry = TriggerRegistry(db=db_session)
        mock_execs = [
            _make_execution(ExecutionStatus.SUCCEEDED),
            _make_execution(ExecutionStatus.FAILED),
        ]

        with patch.object(registry, 'fire_trigger', return_value=mock_execs):
            all_passed, executions = registry.before_status_change(
                entity_type=EntityType.DATA_PRODUCT,
                entity_id='prod-1',
                from_status='draft',
                to_status='active',
            )

        assert all_passed is False
        assert len(executions) == 2

    def test_before_status_change_fires_with_correct_trigger_type(self, db_session):
        """Must fire BEFORE_STATUS_CHANGE, not ON_STATUS_CHANGE."""
        registry = TriggerRegistry(db=db_session)

        with patch.object(registry, 'fire_trigger', return_value=[]) as mock_fire:
            registry.before_status_change(
                entity_type=EntityType.DATA_CONTRACT,
                entity_id='contract-1',
                from_status='draft',
                to_status='proposed',
                entity_name='Test Contract',
                user_email='user@example.com',
            )

        event = mock_fire.call_args[0][0]
        assert event.trigger_type == TriggerType.BEFORE_STATUS_CHANGE
        assert event.entity_type == EntityType.DATA_CONTRACT
        assert event.from_status == 'draft'
        assert event.to_status == 'proposed'

    def test_before_status_change_fires_blocking(self, db_session):
        """Must fire synchronously (blocking=True)."""
        registry = TriggerRegistry(db=db_session)

        with patch.object(registry, 'fire_trigger', return_value=[]) as mock_fire:
            registry.before_status_change(
                entity_type=EntityType.DATA_PRODUCT,
                entity_id='p-1',
                from_status='draft',
                to_status='active',
            )

        assert mock_fire.call_args[1]['blocking'] is True


# =========================================================================
# Manager wiring — User Stories 1, 2, 20
# =========================================================================

class TestDataProductsManagerGating:
    """US1/20: DataProductsManager blocks transitions when workflow fails."""

    def test_transition_blocked_raises_valueerror(self, db_session):
        """Blocked workflow raises ValueError with details."""
        from src.controller.data_products_manager import DataProductsManager
        from src.db_models.data_products import DataProductDb
        import uuid

        # Create a product in 'approved' status
        product = DataProductDb(
            id=str(uuid.uuid4()),
            name="Gated Product",
            version="1.0.0",
            status="approved",
        )
        db_session.add(product)
        db_session.commit()

        mock_ws = MagicMock()
        mgr = DataProductsManager(db=db_session, ws_client=mock_ws)

        # Mock the trigger registry to block the transition
        failed_exec = _make_execution(
            ExecutionStatus.FAILED,
            step_results={'step-1': {'error': 'Missing required approval'}},
        )

        with patch('src.common.workflow_triggers.get_trigger_registry') as mock_get_reg:
            mock_registry = MagicMock()
            mock_get_reg.return_value = mock_registry
            mock_registry.before_status_change.return_value = (False, [failed_exec])

            with pytest.raises(ValueError, match="blocked by workflow"):
                mgr.transition_status(product.id, 'active', 'test@example.com')

    def test_transition_allowed_when_workflow_passes(self, db_session):
        """Passing workflow allows transition to proceed."""
        from src.controller.data_products_manager import DataProductsManager
        from src.db_models.data_products import DataProductDb
        import uuid

        product = DataProductDb(
            id=str(uuid.uuid4()),
            name="Allowed Product",
            version="1.0.0",
            status="approved",
        )
        db_session.add(product)
        db_session.commit()

        mock_ws = MagicMock()
        mgr = DataProductsManager(db=db_session, ws_client=mock_ws)

        passed_exec = _make_execution(ExecutionStatus.SUCCEEDED)

        with patch('src.common.workflow_triggers.get_trigger_registry') as mock_get_reg:
            mock_registry = MagicMock()
            mock_get_reg.return_value = mock_registry
            mock_registry.before_status_change.return_value = (True, [passed_exec])
            # Also mock on_status_change so it doesn't try to fire post-transition triggers
            mock_registry.on_status_change.return_value = []

            result = mgr.transition_status(product.id, 'active', 'test@example.com')

        assert result is not None
        # Verify status was actually changed
        db_session.refresh(product)
        assert product.status == 'active'


class TestDataContractsManagerGating:
    """US2: DataContractsManager blocks transitions when workflow fails."""

    def test_contract_transition_blocked_raises_valueerror(self, db_session):
        """Blocked workflow on contract status change raises ValueError."""
        from src.controller.data_contracts_manager import DataContractsManager
        from src.db_models.data_contracts import DataContractDb
        import uuid
        from pathlib import Path

        contract = DataContractDb(
            id=str(uuid.uuid4()),
            name="Gated Contract",
            version="1.0.0",
            status="draft",
        )
        db_session.add(contract)
        db_session.commit()

        mgr = DataContractsManager(data_dir=Path("/tmp"))

        failed_exec = _make_execution(
            ExecutionStatus.FAILED,
            step_results={'step-1': {'error': 'Schema validation failed'}},
        )

        with patch('src.common.workflow_triggers.get_trigger_registry') as mock_get_reg:
            mock_registry = MagicMock()
            mock_get_reg.return_value = mock_registry
            mock_registry.before_status_change.return_value = (False, [failed_exec])

            with pytest.raises(ValueError, match="blocked by workflow"):
                mgr.transition_status(
                    db=db_session,
                    contract_id=contract.id,
                    new_status='proposed',
                    current_user='test@example.com',
                )


class TestContractApproveFromProposed:
    """ONT-CUJ-013: a steward must be able to approve a proposed contract.

    Previously DATA_CONTRACT_TRANSITIONS omitted "approved" from "proposed",
    so the approve endpoint's transition_status(proposed -> approved) raised
    ValueError, which the route turned into an opaque 500.
    """

    def test_lifecycle_map_allows_proposed_to_approved(self):
        from src.models.lifecycle import DATA_CONTRACT_TRANSITIONS
        assert 'approved' in DATA_CONTRACT_TRANSITIONS['proposed']

    def test_transition_proposed_to_approved_succeeds(self, db_session):
        from src.controller.data_contracts_manager import DataContractsManager
        from src.db_models.data_contracts import DataContractDb
        import uuid
        from pathlib import Path

        contract = DataContractDb(
            id=str(uuid.uuid4()),
            name="Approvable Contract",
            version="1.0.0",
            status="proposed",
        )
        db_session.add(contract)
        db_session.commit()

        mgr = DataContractsManager(data_dir=Path("/tmp"))
        updated = mgr.transition_status(
            db=db_session,
            contract_id=contract.id,
            new_status='approved',
            current_user='steward@example.com',
        )
        assert updated.status == 'approved'

    def test_invalid_transition_still_raises_valueerror(self, db_session):
        # A genuinely invalid jump (active -> approved) must still be rejected,
        # so the route can map it to a 409 rather than silently allowing it.
        from src.controller.data_contracts_manager import DataContractsManager
        from src.db_models.data_contracts import DataContractDb
        import uuid
        from pathlib import Path

        contract = DataContractDb(
            id=str(uuid.uuid4()),
            name="Active Contract",
            version="1.0.0",
            status="active",
        )
        db_session.add(contract)
        db_session.commit()

        mgr = DataContractsManager(data_dir=Path("/tmp"))
        with pytest.raises(ValueError, match="Invalid status transition"):
            mgr.transition_status(
                db=db_session,
                contract_id=contract.id,
                new_status='approved',
                current_user='steward@example.com',
            )


# =========================================================================
# YAML validation — User Story 15
# =========================================================================

class TestDefaultWorkflowYAML:
    """US15: Default workflows load correctly and have correct status values."""

    def test_default_workflows_yaml_loads_without_error(self, db_session):
        """All default workflows should parse without errors."""
        from src.controller.workflows_manager import WorkflowsManager

        mgr = WorkflowsManager(db=db_session)
        result = mgr.load_from_yaml()

        assert isinstance(result, dict)
        assert 'created' in result or 'skipped' in result
        # Should not raise any exceptions

    def test_data_product_approval_uses_correct_statuses(self):
        """The data-product-approval workflow must use from_status=approved, to_status=active."""
        import yaml

        yaml_path = os.path.join(
            os.path.dirname(__file__),
            '..', '..', 'data', 'default_workflows.yaml',
        )
        with open(yaml_path) as f:
            data = yaml.safe_load(f)

        approval_wf = None
        for wf in data['workflows']:
            if wf['id'] == 'data-product-approval':
                approval_wf = wf
                break

        assert approval_wf is not None, "data-product-approval workflow not found in YAML"
        assert approval_wf['trigger']['from_status'] == 'approved'
        assert approval_wf['trigger']['to_status'] == 'active'

    def test_before_status_change_default_exists_and_inactive(self):
        """A default before-status-change-default workflow should exist, disabled."""
        import yaml

        yaml_path = os.path.join(
            os.path.dirname(__file__),
            '..', '..', 'data', 'default_workflows.yaml',
        )
        with open(yaml_path) as f:
            data = yaml.safe_load(f)

        gate_wf = None
        for wf in data['workflows']:
            if wf['id'] == 'before-status-change-default':
                gate_wf = wf
                break

        assert gate_wf is not None, "before-status-change-default workflow not found"
        assert gate_wf['trigger']['type'] == 'before_status_change'
        assert gate_wf['is_active'] is False


# =========================================================================
# Error message quality — User Story 20
# =========================================================================

class TestBlockedTransitionErrorMessage:
    """US20: Blocked transitions give clear error with workflow failure details."""

    def test_error_includes_from_and_to_status(self, db_session):
        """Error message should mention both the from and to status."""
        from src.controller.data_products_manager import DataProductsManager
        from src.db_models.data_products import DataProductDb
        import uuid

        product = DataProductDb(
            id=str(uuid.uuid4()),
            name="Error Test Product",
            version="1.0.0",
            status="approved",
        )
        db_session.add(product)
        db_session.commit()

        mock_ws = MagicMock()
        mgr = DataProductsManager(db=db_session, ws_client=mock_ws)

        failed_exec = _make_execution(
            ExecutionStatus.FAILED,
            step_results={'step-1': {'error': 'Compliance check failed'}},
        )

        with patch('src.common.workflow_triggers.get_trigger_registry') as mock_get_reg:
            mock_registry = MagicMock()
            mock_get_reg.return_value = mock_registry
            mock_registry.before_status_change.return_value = (False, [failed_exec])

            with pytest.raises(ValueError) as exc_info:
                mgr.transition_status(product.id, 'active', 'test@example.com')

        error_msg = str(exc_info.value)
        assert 'approved' in error_msg
        assert 'active' in error_msg
        assert 'Compliance check failed' in error_msg
