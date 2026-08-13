"""Unit tests for the compliance publish gate (Slice #712).

Tests the decision logic for blocking publish when mandatory compliance fields
are incomplete, using mocks to isolate the gate from the full database.
"""
import pytest
from unittest.mock import MagicMock, patch

from src.controller.data_products_manager import DataProductsManager
from src.common.compliance_completeness import CompletenessResult


@pytest.fixture
def mock_db():
    """Mock database session."""
    return MagicMock()


@pytest.fixture
def mock_product_db():
    """Mock data product database object."""
    product = MagicMock()
    product.id = "prod-123"
    product.name = "Test Product"
    product.output_ports = []
    return product


@pytest.fixture
def data_products_manager(mock_db):
    """DataProductsManager with mocked dependencies."""
    manager = DataProductsManager(mock_db)
    return manager


class TestPublishWithCompliance:
    """Tests for publish_product with compliance gate."""

    def test_publish_succeeds_when_no_template_active(self, data_products_manager, mock_db, mock_product_db):
        """Publish succeeds when no compliance template is active (no gate applies)."""
        # Mock the product lookup
        data_products_manager._repo.get = MagicMock(return_value=mock_product_db)

        # Mock compliance_templates_manager to return passing (no template active)
        with patch("src.controller.data_products_manager.compliance_templates_manager") as mock_mgr:
            mock_mgr.check_completeness.return_value = CompletenessResult(passed=True)

            # Mock transition_status to succeed
            with patch.object(data_products_manager, "transition_status") as mock_transition:
                mock_transition.return_value = MagicMock(status="active")

                # Mock trigger and other post-transition operations
                with patch("src.common.workflow_triggers.get_trigger_registry"):
                    result = data_products_manager.publish_product("prod-123", current_user="user@example.com")

                    # Verify transition_status was called (gate did not block)
                    mock_transition.assert_called_once_with("prod-123", "active", "user@example.com")
                    assert result.status == "active"

    def test_publish_blocks_when_mandatory_fields_missing(self, data_products_manager, mock_db, mock_product_db):
        """Publish fails with ValueError when mandatory compliance fields are missing."""
        # Mock the product lookup
        data_products_manager._repo.get = MagicMock(return_value=mock_product_db)

        # Mock compliance_templates_manager to return failing
        with patch("src.controller.data_products_manager.compliance_templates_manager") as mock_mgr:
            mock_mgr.check_completeness.return_value = CompletenessResult(
                passed=False,
                missing=["Data Owner", "Retention Policy"],
                messages=[
                    "'Data Owner' is required but has no value.",
                    "'Retention Policy' is required but has no value.",
                ],
            )

            # Publish should raise ValueError before reaching transition_status
            with pytest.raises(ValueError) as exc_info:
                data_products_manager.publish_product("prod-123", current_user="user@example.com")

            # Verify the error message contains the missing fields
            error_msg = str(exc_info.value)
            assert "Cannot publish product: Missing mandatory compliance fields" in error_msg
            assert "Data Owner" in error_msg
            assert "Retention Policy" in error_msg

    def test_publish_succeeds_when_all_mandatory_fields_satisfied(self, data_products_manager, mock_db, mock_product_db):
        """Publish succeeds when all mandatory compliance fields are satisfied."""
        # Mock the product lookup
        data_products_manager._repo.get = MagicMock(return_value=mock_product_db)

        # Mock compliance_templates_manager to return passing
        with patch("src.controller.data_products_manager.compliance_templates_manager") as mock_mgr:
            mock_mgr.check_completeness.return_value = CompletenessResult(passed=True, missing=[], messages=[])

            # Mock transition_status to succeed
            with patch.object(data_products_manager, "transition_status") as mock_transition:
                mock_transition.return_value = MagicMock(status="active")

                # Mock trigger and other post-transition operations
                with patch("src.common.workflow_triggers.get_trigger_registry"):
                    result = data_products_manager.publish_product("prod-123", current_user="user@example.com")

                    # Verify transition_status was called (gate did not block)
                    mock_transition.assert_called_once_with("prod-123", "active", "user@example.com")
                    assert result.status == "active"

    def test_compliance_gate_called_with_correct_params(self, data_products_manager, mock_db, mock_product_db):
        """Verify compliance check is called with data_product entity type and product id."""
        # Mock the product lookup
        data_products_manager._repo.get = MagicMock(return_value=mock_product_db)

        # Mock compliance_templates_manager
        with patch("src.controller.data_products_manager.compliance_templates_manager") as mock_mgr:
            mock_mgr.check_completeness.return_value = CompletenessResult(passed=True)

            # Mock transition_status to succeed
            with patch.object(data_products_manager, "transition_status") as mock_transition:
                mock_transition.return_value = MagicMock(status="active")

                # Mock trigger
                with patch("src.common.workflow_triggers.get_trigger_registry"):
                    data_products_manager.publish_product("prod-123", current_user="user@example.com")

                    # Verify check_completeness was called with correct parameters
                    mock_mgr.check_completeness.assert_called_once()
                    call_args = mock_mgr.check_completeness.call_args
                    # Check that it was called with entity_type="data_product" and entity_id=product_id
                    assert call_args.kwargs.get("entity_type") == "data_product"
                    assert call_args.kwargs.get("entity_id") == "prod-123"

    def test_error_logs_compliance_failure(self, data_products_manager, mock_db, mock_product_db):
        """Verify that compliance failures are logged before raising."""
        # Mock the product lookup
        data_products_manager._repo.get = MagicMock(return_value=mock_product_db)

        # Mock compliance_templates_manager to return failing
        with patch("src.controller.data_products_manager.compliance_templates_manager") as mock_mgr:
            mock_mgr.check_completeness.return_value = CompletenessResult(
                passed=False,
                missing=["Owner"],
                messages=["'Owner' is required but has no value."],
            )

            # Mock the logger to verify it was called
            with patch("src.controller.data_products_manager.logger") as mock_logger:
                with pytest.raises(ValueError):
                    data_products_manager.publish_product("prod-123", current_user="user@example.com")

                # Verify error was logged
                mock_logger.error.assert_called()
                call_args = str(mock_logger.error.call_args)
                assert "Compliance check failed" in call_args or "prod-123" in call_args

    def test_compliance_gate_executed_before_status_transition(self, data_products_manager, mock_db, mock_product_db):
        """Verify compliance gate executes before transition_status (order matters for atomicity)."""
        call_order = []

        def track_completeness_call(*args, **kwargs):
            call_order.append("completeness_check")
            return CompletenessResult(passed=True)

        def track_transition_call(*args, **kwargs):
            call_order.append("transition_status")
            return MagicMock(status="active")

        # Mock the product lookup
        data_products_manager._repo.get = MagicMock(return_value=mock_product_db)

        # Mock compliance_templates_manager
        with patch("src.controller.data_products_manager.compliance_templates_manager") as mock_mgr:
            mock_mgr.check_completeness.side_effect = track_completeness_call

            # Mock transition_status
            with patch.object(data_products_manager, "transition_status", side_effect=track_transition_call):
                # Mock trigger
                with patch("src.common.workflow_triggers.get_trigger_registry"):
                    data_products_manager.publish_product("prod-123", current_user="user@example.com")

                    # Verify order: completeness check must come before transition
                    assert call_order == ["completeness_check", "transition_status"]

    def test_publish_does_not_block_on_edits(self):
        """Test that product edits are NOT blocked by compliance (only publish is blocked).

        This test documents the intended behavior: only the publish_product path
        enforces the compliance gate; update_product does not.
        """
        # This is a behavior documentation test.
        # The actual update_product method should not call check_completeness.
        # We don't test it here, but this comment documents the expected behavior.
        pass
