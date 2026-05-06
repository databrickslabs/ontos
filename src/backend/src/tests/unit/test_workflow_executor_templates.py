# Set test environment variables BEFORE any app imports
import os
os.environ['TESTING'] = 'true'
os.environ['SKIP_STARTUP_TASKS'] = 'true'

import pytest
from unittest.mock import MagicMock, patch
from uuid import uuid4

from src.common.workflow_executor import (
    substitute_template,
    NotificationStepHandler,
    StepContext,
    StepResult,
)
from src.models.process_workflows import TriggerContext


def _make_context(**overrides) -> StepContext:
    """Build a StepContext with rich defaults for template testing."""
    defaults = dict(
        entity={'name': 'test_table', 'status': 'draft', 'owner': 'alice@co.com'},
        entity_type='table',
        entity_id='entity-123',
        entity_name='test_table',
        user_email='user@example.com',
        trigger_context=None,
        execution_id='exec-1',
        workflow_id='wf-1',
        workflow_name='Test Workflow',
        step_results={'validate': {'passed': True, 'score': 95}},
        on_behalf_of=None,
    )
    defaults.update(overrides)
    return StepContext(**defaults)


# =========================================================================
# substitute_template — basic scalar variables
# =========================================================================

class TestSubstituteTemplateBasicVars:
    """substitute_template resolves basic ${var} placeholders."""

    def test_entity_name(self):
        ctx = _make_context()
        assert substitute_template("Table: ${entity_name}", ctx) == "Table: test_table"

    def test_entity_type(self):
        ctx = _make_context()
        assert substitute_template("Type is ${entity_type}", ctx) == "Type is table"

    def test_user_email(self):
        ctx = _make_context()
        assert substitute_template("By ${user_email}", ctx) == "By user@example.com"

    def test_workflow_name(self):
        ctx = _make_context()
        assert substitute_template("WF: ${workflow_name}", ctx) == "WF: Test Workflow"

    def test_workflow_id(self):
        ctx = _make_context()
        assert substitute_template("id=${workflow_id}", ctx) == "id=wf-1"

    def test_execution_id(self):
        ctx = _make_context()
        assert substitute_template("run=${execution_id}", ctx) == "run=exec-1"

    def test_entity_id(self):
        ctx = _make_context()
        assert substitute_template("eid=${entity_id}", ctx) == "eid=entity-123"

    def test_multiple_vars_in_one_string(self):
        ctx = _make_context()
        tpl = "${entity_type} '${entity_name}' by ${user_email}"
        assert substitute_template(tpl, ctx) == "table 'test_table' by user@example.com"


# =========================================================================
# substitute_template — entity.field dot-notation
# =========================================================================

class TestSubstituteTemplateEntityFields:
    """substitute_template resolves ${entity.field} for entity dict fields."""

    def test_entity_field_string(self):
        ctx = _make_context()
        assert substitute_template("Owner: ${entity.owner}", ctx) == "Owner: alice@co.com"

    def test_entity_field_status(self):
        ctx = _make_context()
        assert substitute_template("Status: ${entity.status}", ctx) == "Status: draft"

    def test_entity_field_name(self):
        ctx = _make_context()
        assert substitute_template("Name: ${entity.name}", ctx) == "Name: test_table"

    def test_entity_field_numeric(self):
        ctx = _make_context(entity={'name': 'tbl', 'row_count': 42})
        assert substitute_template("Rows: ${entity.row_count}", ctx) == "Rows: 42"

    def test_entity_field_boolean(self):
        ctx = _make_context(entity={'name': 'tbl', 'active': True})
        assert substitute_template("Active: ${entity.active}", ctx) == "Active: True"


# =========================================================================
# substitute_template — step_results.step_id.field
# =========================================================================

class TestSubstituteTemplateStepResults:
    """substitute_template resolves ${step_results.step_id.field} for previous step data."""

    def test_step_result_bool(self):
        ctx = _make_context()
        assert substitute_template("Passed: ${step_results.validate.passed}", ctx) == "Passed: True"

    def test_step_result_int(self):
        ctx = _make_context()
        assert substitute_template("Score: ${step_results.validate.score}", ctx) == "Score: 95"

    def test_step_result_nested_dict(self):
        """Nested dict inside step_results is also resolved."""
        ctx = _make_context(
            step_results={'check': {'details': {'severity': 'high', 'count': 3}}}
        )
        result = substitute_template("Severity: ${step_results.check.details.severity}", ctx)
        assert result == "Severity: high"

    def test_step_result_multiple_steps(self):
        ctx = _make_context(
            step_results={
                'step_a': {'val': 'AAA'},
                'step_b': {'val': 'BBB'},
            }
        )
        tpl = "${step_results.step_a.val} / ${step_results.step_b.val}"
        assert substitute_template(tpl, ctx) == "AAA / BBB"


# =========================================================================
# substitute_template — {{var}} (double-brace) syntax
# =========================================================================

class TestSubstituteTemplateDoubleBrace:
    """substitute_template handles {{var}} syntax identically to ${var}."""

    def test_double_brace_entity_name(self):
        ctx = _make_context()
        assert substitute_template("Table: {{entity_name}}", ctx) == "Table: test_table"

    def test_double_brace_entity_field(self):
        ctx = _make_context()
        assert substitute_template("Owner: {{entity.owner}}", ctx) == "Owner: alice@co.com"

    def test_double_brace_step_results(self):
        ctx = _make_context()
        assert substitute_template("Score: {{step_results.validate.score}}", ctx) == "Score: 95"

    def test_mixed_syntax(self):
        """Both ${} and {{}} in the same string."""
        ctx = _make_context()
        tpl = "${entity_name} score={{step_results.validate.score}}"
        assert substitute_template(tpl, ctx) == "test_table score=95"


# =========================================================================
# substitute_template — missing / unknown variables
# =========================================================================

class TestSubstituteTemplateMissing:
    """substitute_template handles missing/unknown variables gracefully."""

    def test_unknown_var_left_as_is(self):
        ctx = _make_context()
        tpl = "Hello ${nonexistent_var}"
        assert substitute_template(tpl, ctx) == "Hello ${nonexistent_var}"

    def test_unknown_double_brace_left_as_is(self):
        ctx = _make_context()
        tpl = "Hello {{nonexistent_var}}"
        assert substitute_template(tpl, ctx) == "Hello {{nonexistent_var}}"

    def test_unknown_entity_field_left_as_is(self):
        ctx = _make_context()
        tpl = "Val: ${entity.missing_field}"
        assert substitute_template(tpl, ctx) == "Val: ${entity.missing_field}"

    def test_unknown_step_result_left_as_is(self):
        ctx = _make_context()
        tpl = "${step_results.missing_step.field}"
        assert substitute_template(tpl, ctx) == "${step_results.missing_step.field}"

    def test_empty_template(self):
        ctx = _make_context()
        assert substitute_template("", ctx) == ""

    def test_no_variables(self):
        ctx = _make_context()
        assert substitute_template("plain text", ctx) == "plain text"

    def test_none_entity_name_resolves_empty(self):
        """entity_name=None should resolve to empty string, not 'None'."""
        ctx = _make_context(entity_name=None)
        assert substitute_template("N=${entity_name}", ctx) == "N="


# =========================================================================
# list/dict serialization + nested context paths
# =========================================================================

class TestSubscribeOnBehalfTemplates:
    """Resolver fixes required for subscribe-on-behalf-of-group + the
    consumer_principals data product metadata. The external runbook webhook
    body needs `${context.on_behalf_of.value}` (nested dict) AND
    `${entity.consumer_principals}` (list, JSON-serialized)."""

    def test_entity_list_serialized_as_json(self):
        """${entity.<list_field>} renders as a JSON array string."""
        ctx = _make_context(entity={
            'name': 'sales_kpis',
            'consumer_principals': [
                {'type': 'group', 'value': 'sales_consumers'},
                {'type': 'group', 'value': 'finance_readers'},
            ],
        })
        out = substitute_template("principals=${entity.consumer_principals}", ctx)
        assert out == (
            'principals=[{"type": "group", "value": "sales_consumers"}, '
            '{"type": "group", "value": "finance_readers"}]'
        )

    def test_entity_empty_list_serializes(self):
        ctx = _make_context(entity={'consumer_principals': []})
        assert substitute_template("${entity.consumer_principals}", ctx) == "[]"

    def test_entity_dict_serialized_as_json(self):
        """${entity.<dict_field>} renders as a JSON object string."""
        ctx = _make_context(entity={'metadata': {'k': 'v', 'n': 1}})
        out = substitute_template("${entity.metadata}", ctx)
        assert out in ('{"k": "v", "n": 1}', '{"n": 1, "k": "v"}')

    def test_entity_nested_dict_path(self):
        """${entity.a.b} walks nested dict structure."""
        ctx = _make_context(entity={'metadata': {'owner': 'alice'}})
        assert substitute_template("o=${entity.metadata.owner}", ctx) == "o=alice"

    def test_context_on_behalf_of_value(self):
        """${context.on_behalf_of.value} resolves the nested dict path."""
        ctx = _make_context(on_behalf_of={
            'type': 'group', 'value': 'sales_consumers', 'display': 'Group: sales_consumers',
        })
        out = substitute_template("principal=${context.on_behalf_of.value}", ctx)
        assert out == "principal=sales_consumers"

    def test_context_on_behalf_of_type_and_display(self):
        ctx = _make_context(on_behalf_of={
            'type': 'group', 'value': 'sales_consumers', 'display': 'Group: sales_consumers',
        })
        assert substitute_template("${context.on_behalf_of.type}", ctx) == "group"
        assert substitute_template("${context.on_behalf_of.display}", ctx) == "Group: sales_consumers"

    def test_context_on_behalf_of_none_unresolved(self):
        """When on_behalf_of is None, the placeholder is left intact (don't render 'None')."""
        ctx = _make_context(on_behalf_of=None)
        out = substitute_template("p=${context.on_behalf_of.value}", ctx)
        assert out == "p=${context.on_behalf_of.value}"

    def test_context_top_level_attr(self):
        """${context.entity_type} resolves the top-level scalar attribute."""
        ctx = _make_context(entity_type='data_product')
        assert substitute_template("t=${context.entity_type}", ctx) == "t=data_product"

    def test_webhook_body_template_full__payload(self):
        """Realistic External-runbook payload combining both fixes."""
        ctx = _make_context(
            entity={
                'name': 'sales_kpis',
                'consumer_principals': [
                    {'type': 'group', 'value': 'sales_consumers'},
                    {'type': 'group', 'value': 'finance_readers'},
                ],
            },
            on_behalf_of={'type': 'group', 'value': 'sales_consumers', 'display': 'Group: sales_consumers'},
        )
        body_template = (
            '{"product": "${entity_name}", '
            '"on_behalf_of": "${context.on_behalf_of.value}", '
            '"principals": ${entity.consumer_principals}}'
        )
        rendered = substitute_template(body_template, ctx)
        import json as _json
        payload = _json.loads(rendered)
        assert payload['product'] == 'test_table'
        assert payload['on_behalf_of'] == 'sales_consumers'
        assert payload['principals'] == [
            {'type': 'group', 'value': 'sales_consumers'},
            {'type': 'group', 'value': 'finance_readers'},
        ]


# =========================================================================
# NotificationStepHandler — applies substitution to custom_message
# =========================================================================

class TestNotificationStepHandlerSubstitution:
    """NotificationStepHandler applies variable substitution to custom_message."""

    @patch('src.repositories.notification_repository.notification_repo')
    def test_custom_message_substituted(self, mock_repo, db_session):
        """custom_message with ${var} is resolved before creating notification."""
        mock_repo.create = MagicMock()

        handler = NotificationStepHandler(
            db=db_session,
            config={
                'recipients': 'user@example.com',
                'template': 'info',
                'custom_message': 'Entity ${entity_name} was processed by ${user_email}',
                'channels': ['in_app'],
            },
        )
        ctx = _make_context()
        result = handler.execute(ctx)

        assert result.passed is True
        # Verify notification was created with substituted message
        assert mock_repo.create.called
        created_notification = mock_repo.create.call_args[1].get('obj_in') or mock_repo.create.call_args[0][1] if len(mock_repo.create.call_args[0]) > 1 else mock_repo.create.call_args[1].get('obj_in')
        # The notification description should contain the substituted message
        if created_notification:
            assert 'test_table' in created_notification.description
            assert 'user@example.com' in created_notification.description

    @patch('src.repositories.notification_repository.notification_repo')
    def test_template_message_substituted(self, mock_repo, db_session):
        """When custom_message is absent, the template message is still substituted."""
        mock_repo.create = MagicMock()

        handler = NotificationStepHandler(
            db=db_session,
            config={
                'recipients': 'user@example.com',
                'template': 'status_changed',
                'channels': ['in_app'],
            },
        )
        ctx = _make_context()
        result = handler.execute(ctx)

        assert result.passed is True
        assert mock_repo.create.called

    @patch('src.repositories.notification_repository.notification_repo')
    def test_no_recipients_fails(self, mock_repo, db_session):
        """Missing recipients returns passed=False."""
        handler = NotificationStepHandler(
            db=db_session,
            config={'recipients': '', 'template': 'info'},
        )
        result = handler.execute(_make_context())
        assert result.passed is False
        assert 'recipient' in (result.error or '').lower()


# =========================================================================
# NotificationTemplateDb — correct columns
# =========================================================================

class TestNotificationTemplateDbSchema:
    """Verify NotificationTemplateDb model has the required columns."""

    def test_columns_exist(self):
        from src.db_models.notifications import NotificationTemplateDb

        mapper = NotificationTemplateDb.__table__
        col_names = {c.name for c in mapper.columns}
        expected = {'id', 'name', 'title_template', 'body_template',
                    'notification_type', 'is_default'}
        assert expected.issubset(col_names), f"Missing columns: {expected - col_names}"

    def test_table_name(self):
        from src.db_models.notifications import NotificationTemplateDb
        assert NotificationTemplateDb.__tablename__ == 'notification_templates'

    def test_name_is_unique(self):
        from src.db_models.notifications import NotificationTemplateDb
        name_col = NotificationTemplateDb.__table__.c.name
        assert name_col.unique is True


# =========================================================================
# Pydantic models — existence and fields
# =========================================================================

class TestNotificationTemplatePydanticModels:
    """Verify Pydantic models for notification templates exist and have key fields."""

    def test_notification_template_read_model(self):
        from src.models.notifications import NotificationTemplate
        fields = set(NotificationTemplate.model_fields.keys())
        assert {'id', 'name', 'title_template', 'body_template',
                'notification_type', 'is_default'}.issubset(fields)

    def test_notification_template_create_model(self):
        from src.models.notifications import NotificationTemplateCreate
        fields = set(NotificationTemplateCreate.model_fields.keys())
        assert {'name', 'title_template', 'body_template'}.issubset(fields)

    def test_notification_template_update_model(self):
        from src.models.notifications import NotificationTemplateUpdate
        fields = set(NotificationTemplateUpdate.model_fields.keys())
        assert {'name', 'title_template', 'body_template'}.issubset(fields)

    def test_create_model_defaults(self):
        from src.models.notifications import NotificationTemplateCreate, NotificationType
        obj = NotificationTemplateCreate(
            name='test', title_template='T', body_template='B'
        )
        assert obj.notification_type == NotificationType.INFO
        assert obj.is_default is False

    def test_update_model_all_optional(self):
        from src.models.notifications import NotificationTemplateUpdate
        obj = NotificationTemplateUpdate()  # All fields optional
        assert obj.name is None
        assert obj.title_template is None
