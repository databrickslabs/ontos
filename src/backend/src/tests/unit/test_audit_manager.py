"""
Unit tests for AuditManager
"""
import uuid

import pytest
from datetime import datetime
from unittest.mock import Mock, MagicMock, patch
from pathlib import Path
from src.controller.audit_manager import AuditManager
from src.models.audit_log import AuditLogCreate, AuditLogRead
from src.db_models.audit_log import AuditLogDb


class TestAuditManager:
    """Test suite for AuditManager."""

    @pytest.fixture
    def mock_settings(self):
        """Create mock settings."""
        settings = Mock()
        settings.APP_AUDIT_LOG_DIR = "/tmp/audit_logs"
        return settings

    @pytest.fixture
    def mock_db_session(self):
        """Create mock database session."""
        return Mock()

    @pytest.fixture
    def mock_repository(self):
        """Create mock audit log repository."""
        return Mock()

    @pytest.fixture
    @patch('src.controller.audit_manager.audit_log_repository')
    def manager(self, mock_repo, mock_settings, mock_db_session):
        """Create AuditManager instance for testing."""
        with patch.object(AuditManager, '_configure_file_logger'):
            return AuditManager(settings=mock_settings, db_session=mock_db_session)

    @pytest.fixture
    def sample_audit_log_db(self):
        """Sample audit log database object."""
        log = Mock(spec=AuditLogDb)
        log.id = uuid.uuid4()
        log.username = "user@example.com"
        log.ip_address = "192.168.1.1"
        log.feature = "data-products"
        log.action = "CREATE"
        log.success = True
        log.details = {"product_id": "prod-123"}
        log.timestamp = datetime(2024, 1, 1, 0, 0, 0)
        return log

    # Initialization Tests

    @patch('src.controller.audit_manager.audit_log_repository')
    def test_manager_initialization(self, mock_repo, mock_settings, mock_db_session):
        """Test manager initializes with settings and db."""
        with patch.object(AuditManager, '_configure_file_logger'):
            manager = AuditManager(settings=mock_settings, db_session=mock_db_session)
            assert manager.settings == mock_settings
            assert manager.db == mock_db_session

    @patch('src.controller.audit_manager.Path.mkdir')
    @patch('src.controller.audit_manager.TimedRotatingFileHandler')
    @patch('src.controller.audit_manager.file_audit_logger')
    def test_configure_file_logger_success(
        self, mock_logger, mock_handler_class, mock_mkdir, mock_settings, mock_db_session
    ):
        """Test successful file logger configuration."""
        mock_handler = Mock()
        mock_handler_class.return_value = mock_handler
        mock_logger.hasHandlers.return_value = False

        manager = AuditManager(settings=mock_settings, db_session=mock_db_session)

        # Verify directory creation
        mock_mkdir.assert_called_once_with(parents=True, exist_ok=True)
        # Verify handler was added
        mock_logger.addHandler.assert_called_once_with(mock_handler)

    @patch('src.controller.audit_manager.Path.mkdir')
    @patch('src.controller.audit_manager.file_audit_logger')
    def test_configure_file_logger_failure(
        self, mock_logger, mock_mkdir, mock_settings, mock_db_session
    ):
        """Test handling of file logger configuration failure."""
        mock_mkdir.side_effect = PermissionError("Cannot create directory")
        mock_logger.hasHandlers.return_value = False

        manager = AuditManager(settings=mock_settings, db_session=mock_db_session)

        # Logger should be disabled on failure
        assert mock_logger.disabled is True

    # Log Action Internal Tests

    @patch('src.controller.audit_manager.file_audit_logger')
    def test_log_action_internal_success(self, mock_file_logger, manager):
        """Test internal logging to both file and database."""
        mock_file_logger.disabled = False
        mock_db = Mock()
        
        log_data = {
            "username": "user@example.com",
            "ip_address": "192.168.1.1",
            "feature": "data-products",
            "action": "CREATE",
            "success": True,
            "details": {"product_id": "prod-123"},
        }

        manager._log_action_internal(mock_db, log_data)

        # Verify file logging
        mock_file_logger.info.assert_called_once()
        # Verify database logging
        manager.repository.create.assert_called_once()
        mock_db.commit.assert_called_once()

    @patch('src.controller.audit_manager.file_audit_logger')
    def test_log_action_internal_file_disabled(self, mock_file_logger, manager):
        """Test internal logging when file logger is disabled."""
        mock_file_logger.disabled = True
        mock_db = Mock()
        
        log_data = {
            "username": "user@example.com",
            "ip_address": "192.168.1.1",
            "feature": "data-products",
            "action": "CREATE",
            "success": True,
            "details": {},
        }

        manager._log_action_internal(mock_db, log_data)

        # File logging should be skipped
        mock_file_logger.info.assert_not_called()
        # But database logging should still work
        manager.repository.create.assert_called_once()

    @patch('src.controller.audit_manager.file_audit_logger')
    def test_log_action_internal_db_error(self, mock_file_logger, manager):
        """Test handling of database errors during logging."""
        mock_file_logger.disabled = False
        mock_db = Mock()
        manager.repository.create.side_effect = Exception("Database error")
        
        log_data = {
            "username": "user@example.com",
            "ip_address": "192.168.1.1",
            "feature": "data-products",
            "action": "CREATE",
            "success": True,
            "details": {},
        }

        # Should not raise exception
        manager._log_action_internal(mock_db, log_data)

        # Verify rollback was called
        mock_db.rollback.assert_called_once()

    # Log Action Tests

    @patch('src.controller.audit_manager.get_session_factory')
    def test_log_action_success(self, mock_factory, manager):
        """Test synchronous log action."""
        mock_session = Mock()
        mock_factory.return_value = lambda: mock_session
        mock_session.__enter__ = Mock(return_value=mock_session)
        mock_session.__exit__ = Mock(return_value=False)

        manager.log_action(
            Mock(),  # db parameter (ignored)
            username="user@example.com",
            ip_address="192.168.1.1",
            feature="data-products",
            action="CREATE",
            success=True,
            details={"product_id": "prod-123"},
        )

        # Verify internal logging was called
        manager.repository.create.assert_called_once()

    @patch('src.controller.audit_manager.get_session_factory')
    def test_log_action_no_session_factory(self, mock_factory, manager):
        """Test log action when session factory is unavailable."""
        mock_factory.return_value = None

        # Should not raise exception
        manager.log_action(
            Mock(),
            username="user@example.com",
            ip_address="192.168.1.1",
            feature="data-products",
            action="CREATE",
            success=True,
        )

        # No repository call should be made
        manager.repository.create.assert_not_called()

    @patch('src.controller.audit_manager.get_session_factory')
    def test_log_action_with_none_details(self, mock_factory, manager):
        """Test log action with None details defaults to empty dict."""
        mock_session = Mock()
        mock_factory.return_value = lambda: mock_session
        mock_session.__enter__ = Mock(return_value=mock_session)
        mock_session.__exit__ = Mock(return_value=False)

        manager.log_action(
            Mock(),
            username="user@example.com",
            ip_address=None,
            feature="data-products",
            action="VIEW",
            success=True,
            details=None,
        )

        # Should use empty dict for details
        manager.repository.create.assert_called_once()

    # Get Audit Logs Tests

    @pytest.mark.asyncio
    async def test_get_audit_logs_empty(self, manager):
        """Test getting audit logs when none exist."""
        mock_db = Mock()
        manager.repository.get_multi_count.return_value = 0
        manager.repository.get_multi.return_value = []

        total, logs = await manager.get_audit_logs(mock_db)

        assert total == 0
        assert logs == []

    @pytest.mark.asyncio
    async def test_get_audit_logs_with_results(self, manager, sample_audit_log_db):
        """Test getting audit logs with results."""
        mock_db = Mock()
        manager.repository.get_multi_count.return_value = 1
        manager.repository.get_multi.return_value = [sample_audit_log_db]

        total, logs = await manager.get_audit_logs(mock_db)

        assert total == 1
        assert len(logs) == 1
        assert logs[0].username == "user@example.com"

    @pytest.mark.asyncio
    async def test_get_audit_logs_with_filters(self, manager):
        """Test getting audit logs with filters."""
        mock_db = Mock()
        manager.repository.get_multi_count.return_value = 0
        manager.repository.get_multi.return_value = []

        start_time = datetime(2024, 1, 1, 0, 0, 0)
        end_time = datetime(2024, 12, 31, 23, 59, 59)

        await manager.get_audit_logs(
            mock_db,
            skip=10,
            limit=50,
            start_time=start_time,
            end_time=end_time,
            username="user@example.com",
            feature="data-products",
            action="CREATE",
            success=True,
        )

        # Verify filters were passed to repository
        manager.repository.get_multi.assert_called_once()
        call_kwargs = manager.repository.get_multi.call_args[1]
        assert call_kwargs["skip"] == 10
        assert call_kwargs["limit"] == 50
        assert call_kwargs["start_time"] == start_time
        assert call_kwargs["end_time"] == end_time
        assert call_kwargs["username"] == "user@example.com"
        assert call_kwargs["feature"] == "data-products"
        assert call_kwargs["action"] == "CREATE"
        assert call_kwargs["success"] is True

    @pytest.mark.asyncio
    async def test_get_audit_logs_with_pagination(self, manager):
        """Test getting audit logs with pagination."""
        mock_db = Mock()
        manager.repository.get_multi_count.return_value = 100
        manager.repository.get_multi.return_value = []

        await manager.get_audit_logs(mock_db, skip=20, limit=25)

        call_kwargs = manager.repository.get_multi.call_args[1]
        assert call_kwargs["skip"] == 20
        assert call_kwargs["limit"] == 25

    @pytest.mark.asyncio
    async def test_get_audit_logs_handles_error(self, manager):
        """Test error handling when retrieving audit logs."""
        mock_db = Mock()
        manager.repository.get_multi_count.side_effect = Exception("Database error")

        total, logs = await manager.get_audit_logs(mock_db)

        # Should return empty on error
        assert total == 0
        assert logs == []

    # Background Logging Tests

    @pytest.mark.asyncio
    @patch('src.controller.audit_manager.get_session_factory')
    async def test_log_action_background_success(self, mock_factory, manager):
        """Test background async log action."""
        mock_session = Mock()
        mock_factory.return_value = lambda: mock_session
        mock_session.__enter__ = Mock(return_value=mock_session)
        mock_session.__exit__ = Mock(return_value=False)

        await manager.log_action_background(
            username="user@example.com",
            ip_address="192.168.1.1",
            feature="data-products",
            action="UPDATE",
            success=True,
            details={"field": "status"},
        )

        # Verify internal logging was called
        manager.repository.create.assert_called_once()

    @pytest.mark.asyncio
    @patch('src.controller.audit_manager.get_session_factory')
    async def test_log_action_background_no_factory(self, mock_factory, manager):
        """Test background logging when session factory unavailable."""
        mock_factory.return_value = None

        await manager.log_action_background(
            username="user@example.com",
            ip_address="192.168.1.1",
            feature="data-products",
            action="DELETE",
            success=False,
        )

        # No repository call should be made
        manager.repository.create.assert_not_called()
