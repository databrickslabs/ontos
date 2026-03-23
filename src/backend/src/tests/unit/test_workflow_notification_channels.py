# Set test environment variables BEFORE any app imports
import os
os.environ['TESTING'] = 'true'
os.environ['SKIP_STARTUP_TASKS'] = 'true'

import json
import pytest
from unittest.mock import MagicMock, patch
from uuid import uuid4

from src.common.workflow_executor import (
    NotificationStepHandler,
    StepContext,
    StepResult,
)
from src.models.notifications import NotificationChannel, NotificationType
from src.models.settings import EmailConfig, NotificationChannelDefaults
from src.common.email_service import EmailService
from src.db_models.app_settings import AppSettingDb


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_context(**overrides) -> StepContext:
    """Build a minimal StepContext for testing."""
    defaults = dict(
        entity={'name': 'test_table', 'status': 'draft'},
        entity_type='table',
        entity_id='entity-123',
        entity_name='test_table',
        user_email='user@example.com',
        trigger_context=None,
        execution_id='exec-1',
        workflow_id='wf-1',
        workflow_name='Test Workflow',
        step_results={},
    )
    defaults.update(overrides)
    return StepContext(**defaults)


# =========================================================================
# 1. NotificationChannel enum
# =========================================================================

class TestNotificationChannelEnum:
    """AC: NotificationChannel enum exists with in_app, email, webhook values."""

    def test_has_in_app(self):
        assert NotificationChannel.IN_APP.value == "in_app"

    def test_has_email(self):
        assert NotificationChannel.EMAIL.value == "email"

    def test_has_webhook(self):
        assert NotificationChannel.WEBHOOK.value == "webhook"

    def test_exactly_three_members(self):
        assert len(NotificationChannel) == 3

    def test_is_string_enum(self):
        assert isinstance(NotificationChannel.IN_APP, str)


# =========================================================================
# 2. EmailService.from_settings
# =========================================================================

class TestEmailServiceFromSettings:
    """AC: EmailService.from_settings() reads config from Settings DB and returns None when disabled."""

    def test_returns_none_when_no_config_row(self, db_session):
        """No email_config row in DB -> returns None."""
        result = EmailService.from_settings(db_session)
        assert result is None

    def test_returns_none_when_disabled(self, db_session):
        """email_config row exists but enabled=False -> returns None."""
        db_session.add(AppSettingDb(
            key="email_config",
            value=json.dumps({"enabled": False, "provider": "smtp", "from_address": "a@b.com"})
        ))
        db_session.flush()

        result = EmailService.from_settings(db_session)
        assert result is None

    def test_returns_service_when_enabled(self, db_session):
        """email_config row with enabled=True -> returns EmailService instance."""
        db_session.add(AppSettingDb(
            key="email_config",
            value=json.dumps({
                "enabled": True,
                "provider": "smtp",
                "from_address": "noreply@test.com",
                "smtp_host": "smtp.test.com",
                "smtp_port": 587,
            })
        ))
        db_session.flush()

        svc = EmailService.from_settings(db_session)
        assert svc is not None
        assert isinstance(svc, EmailService)
        assert svc.provider == "smtp"
        assert svc.from_address == "noreply@test.com"
        assert svc.smtp_host == "smtp.test.com"

    def test_returns_none_when_value_is_invalid_json(self, db_session):
        """Malformed JSON in value -> returns None."""
        db_session.add(AppSettingDb(key="email_config", value="NOT-JSON"))
        db_session.flush()

        result = EmailService.from_settings(db_session)
        assert result is None


# =========================================================================
# 3. EmailService graceful degradation
# =========================================================================

class TestEmailServiceGracefulDegradation:
    """AC: Email delivery gracefully degrades when not configured (logs warning, doesn't fail)."""

    def test_send_smtp_returns_false_when_not_configured(self):
        """_send_smtp returns False when smtp_host or from_address is empty."""
        svc = EmailService(provider="smtp", from_address="", smtp_host="")
        result = svc._send_smtp(["x@y.com"], "subj", "body")
        assert result is False

    def test_send_smtp_returns_false_when_host_missing(self):
        svc = EmailService(provider="smtp", from_address="a@b.com", smtp_host="")
        assert svc._send_smtp(["x@y.com"], "subj", "body") is False

    def test_send_api_returns_false_when_not_configured(self):
        """_send_api returns False when api_key or api_endpoint is empty."""
        svc = EmailService(provider="sendgrid", api_key="", api_endpoint="")
        result = svc._send_api(["x@y.com"], "subj", "body")
        assert result is False

    def test_send_api_returns_false_when_endpoint_missing(self):
        svc = EmailService(provider="sendgrid", api_key="key123", api_endpoint="")
        assert svc._send_api(["x@y.com"], "subj", "body") is False

    def test_send_dispatches_to_smtp(self):
        svc = EmailService(provider="smtp", from_address="a@b.com", smtp_host="host")
        with patch.object(svc, '_send_smtp', return_value=True) as mock_smtp:
            assert svc.send(["x@y.com"], "subj", "body") is True
            mock_smtp.assert_called_once()

    def test_send_dispatches_to_api_for_sendgrid(self):
        svc = EmailService(provider="sendgrid", api_key="k", api_endpoint="http://e")
        with patch.object(svc, '_send_api', return_value=True) as mock_api:
            assert svc.send(["x@y.com"], "subj", "body") is True
            mock_api.assert_called_once()

    def test_send_returns_false_for_unknown_provider(self):
        svc = EmailService(provider="carrier_pigeon")
        assert svc.send(["x@y.com"], "subj", "body") is False


# =========================================================================
# 4. EmailConfig and NotificationChannelDefaults models
# =========================================================================

class TestSettingsModels:
    """AC: EmailConfig and NotificationChannelDefaults models exist with correct fields."""

    def test_email_config_defaults(self):
        cfg = EmailConfig()
        assert cfg.enabled is False
        assert cfg.provider.value == "smtp"
        assert cfg.from_address == ""
        assert cfg.smtp_port == 587
        assert cfg.smtp_use_tls is True

    def test_email_config_with_values(self):
        cfg = EmailConfig(
            enabled=True,
            provider="sendgrid",
            from_address="a@b.com",
            api_key="sg-key",
            api_endpoint="https://api.sendgrid.com/v3/mail/send",
        )
        assert cfg.enabled is True
        assert cfg.from_address == "a@b.com"

    def test_notification_channel_defaults_default(self):
        ncd = NotificationChannelDefaults()
        assert ncd.channels == ["in_app"]

    def test_notification_channel_defaults_custom(self):
        ncd = NotificationChannelDefaults(channels=["in_app", "email", "webhook"])
        assert "email" in ncd.channels
        assert len(ncd.channels) == 3


# =========================================================================
# 5. NotificationStepHandler channel dispatch
# =========================================================================

class TestNotificationStepHandlerChannels:
    """AC: NotificationStepHandler dispatches to configured channels.
       AC: Per-step channels config overrides global defaults.
       AC: Email channel failure does not fail the notification step."""

    @patch('src.repositories.notification_repository.notification_repo')
    def test_uses_step_level_channels(self, mock_repo, db_session):
        """When step config includes 'channels', those are used instead of global defaults."""
        mock_repo.create.return_value = MagicMock()

        handler = NotificationStepHandler(
            db=db_session,
            config={
                'recipients': 'requester',
                'template': 'validation_passed',
                'channels': ['in_app'],
            },
        )
        result = handler.execute(_make_context())

        assert result.passed is True
        assert result.data['channels'] == ['in_app']
        # in_app channel should have created a notification
        assert result.data['created_count'] >= 1
        # email_count should be 0 because email channel not in channels list
        assert result.data.get('email_count', 0) == 0

    @patch('src.repositories.notification_repository.notification_repo')
    def test_falls_back_to_global_defaults(self, mock_repo, db_session):
        """When step config has no 'channels', falls back to _get_default_channels()."""
        mock_repo.create.return_value = MagicMock()

        # Set up global default in DB
        db_session.add(AppSettingDb(
            key="notification_channel_defaults",
            value=json.dumps({"channels": ["in_app"]})
        ))
        db_session.flush()

        handler = NotificationStepHandler(
            db=db_session,
            config={
                'recipients': 'requester',
                'template': 'validation_passed',
                # no 'channels' key
            },
        )
        result = handler.execute(_make_context())

        assert result.passed is True
        assert result.data['channels'] == ['in_app']

    @patch('src.repositories.notification_repository.notification_repo')
    def test_falls_back_to_in_app_when_no_global_setting(self, mock_repo, db_session):
        """When no global setting exists and no step channels, defaults to ['in_app']."""
        mock_repo.create.return_value = MagicMock()

        handler = NotificationStepHandler(
            db=db_session,
            config={
                'recipients': 'requester',
                'template': 'validation_passed',
            },
        )
        result = handler.execute(_make_context())

        assert result.passed is True
        assert 'in_app' in result.data['channels']

    @patch('src.common.email_service.EmailService.from_settings', return_value=None)
    @patch('src.repositories.notification_repository.notification_repo')
    def test_email_channel_graceful_when_not_configured(self, mock_repo, mock_from_settings, db_session):
        """Email channel requested but not configured -> step still passes via in_app."""
        mock_repo.create.return_value = MagicMock()

        handler = NotificationStepHandler(
            db=db_session,
            config={
                'recipients': 'requester',
                'template': 'validation_passed',
                'channels': ['in_app', 'email'],
            },
        )
        result = handler.execute(_make_context())

        assert result.passed is True
        # in_app created, email skipped gracefully
        assert result.data['created_count'] >= 1
        assert result.data['email_count'] == 0

    @patch('src.common.email_service.EmailService.send', side_effect=Exception("SMTP boom"))
    @patch('src.common.email_service.EmailService.from_settings')
    @patch('src.repositories.notification_repository.notification_repo')
    def test_email_send_exception_does_not_fail_step(self, mock_repo, mock_from_settings, mock_send, db_session):
        """If EmailService.send() raises, the step still passes via in_app."""
        mock_repo.create.return_value = MagicMock()
        mock_svc = MagicMock()
        mock_svc.send.side_effect = Exception("SMTP boom")
        mock_from_settings.return_value = mock_svc

        handler = NotificationStepHandler(
            db=db_session,
            config={
                'recipients': 'requester',
                'template': 'validation_passed',
                'channels': ['in_app', 'email'],
            },
        )
        result = handler.execute(_make_context())

        # Should still pass because in_app succeeded
        assert result.passed is True
        assert result.data['created_count'] >= 1

    @patch('src.repositories.notification_repository.notification_repo')
    def test_email_channel_sends_when_configured(self, mock_repo, db_session):
        """Email channel with a configured service should attempt send."""
        mock_repo.create.return_value = MagicMock()

        # Set up email config in DB
        db_session.add(AppSettingDb(
            key="email_config",
            value=json.dumps({
                "enabled": True,
                "provider": "smtp",
                "from_address": "noreply@test.com",
                "smtp_host": "smtp.test.com",
                "smtp_port": 587,
            })
        ))
        db_session.flush()

        handler = NotificationStepHandler(
            db=db_session,
            config={
                'recipients': 'requester',
                'template': 'validation_passed',
                'channels': ['in_app', 'email'],
            },
        )

        with patch.object(EmailService, 'send', return_value=True) as mock_send:
            result = handler.execute(_make_context())

        assert result.passed is True
        assert result.data['created_count'] >= 1
        # Email should have been attempted for user@example.com
        assert result.data['email_count'] == 1
        mock_send.assert_called_once()


# =========================================================================
# 6. Frontend types (static check)
# =========================================================================

class TestFrontendTypes:
    """AC: Frontend types include NotificationChannel."""

    def test_notification_channel_type_exists_in_frontend(self):
        """Verify the NotificationChannel type is defined in the frontend types file."""
        types_file = os.path.join(
            os.path.dirname(__file__),
            '..', '..', '..', '..', 'frontend', 'src', 'types', 'process-workflow.ts',
        )
        types_file = os.path.normpath(types_file)
        assert os.path.exists(types_file), f"Frontend types file not found: {types_file}"

        with open(types_file, 'r') as f:
            content = f.read()

        assert "NotificationChannel" in content
        assert "'in_app'" in content
        assert "'email'" in content
        assert "'webhook'" in content

    def test_notification_step_config_has_channels_field(self):
        """Verify NotificationStepConfig includes optional channels field."""
        types_file = os.path.join(
            os.path.dirname(__file__),
            '..', '..', '..', '..', 'frontend', 'src', 'types', 'process-workflow.ts',
        )
        types_file = os.path.normpath(types_file)

        with open(types_file, 'r') as f:
            content = f.read()

        assert "channels?: NotificationChannel[]" in content
