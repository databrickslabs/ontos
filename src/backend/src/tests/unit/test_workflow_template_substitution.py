"""Tests for workflow template substitution with compliance template values."""

import pytest
from src.common.workflow_executor import substitute_template, StepContext
from src.models.process_workflows import TriggerContext


@pytest.fixture
def step_context_with_template_values():
    """Fixture: StepContext with pre-resolved template values."""
    return StepContext(
        entity={"name": "test-product", "owner": "alice@example.com"},
        entity_type="data_product",
        entity_id="prod-123",
        entity_name="test-product",
        user_email="bob@example.com",
        trigger_context=None,
        execution_id="exec-456",
        workflow_id="wf-789",
        workflow_name="test-workflow",
        step_results={},
        on_behalf_of=None,
        template_values={
            "purpose": "Analytics",
            "retention": "90 days",
            "classification": "Internal",
        },
    )


@pytest.fixture
def step_context_without_template_values():
    """Fixture: StepContext without template values."""
    return StepContext(
        entity={"name": "test-product", "owner": "alice@example.com"},
        entity_type="data_product",
        entity_id="prod-123",
        entity_name="test-product",
        user_email="bob@example.com",
        trigger_context=None,
        execution_id="exec-456",
        workflow_id="wf-789",
        workflow_name="test-workflow",
        step_results={},
        on_behalf_of=None,
        template_values=None,
    )


class TestTemplateSubstitution:
    """Test substitute_template function."""

    def test_resolve_template_field_from_values(self, step_context_with_template_values):
        """Test ${template.<ref>} resolves from template_values."""
        template = "Purpose: ${template.purpose}"
        result = substitute_template(template, step_context_with_template_values)
        assert result == "Purpose: Analytics"

    def test_resolve_multiple_template_fields(self, step_context_with_template_values):
        """Test multiple ${template.<ref>} placeholders resolve."""
        template = (
            "Purpose: ${template.purpose}, "
            "Retention: ${template.retention}, "
            "Classification: ${template.classification}"
        )
        result = substitute_template(template, step_context_with_template_values)
        assert result == "Purpose: Analytics, Retention: 90 days, Classification: Internal"

    def test_unknown_template_field_left_intact(self, step_context_with_template_values):
        """Test ${template.<unknown>} is left intact when not in template_values."""
        template = "Purpose: ${template.purpose}, Owner: ${template.unknown_field}"
        result = substitute_template(template, step_context_with_template_values)
        assert result == "Purpose: Analytics, Owner: ${template.unknown_field}"

    def test_template_field_without_context_values_left_intact(
        self, step_context_without_template_values
    ):
        """Test ${template.<ref>} is left intact when context.template_values is None."""
        template = "Purpose: ${template.purpose}"
        result = substitute_template(template, step_context_without_template_values)
        assert result == "Purpose: ${template.purpose}"

    def test_entity_field_resolution_still_works(self, step_context_with_template_values):
        """Test ${entity.<field>} resolution still works (regression)."""
        template = "Product: ${entity.name}, Owner: ${entity.owner}"
        result = substitute_template(template, step_context_with_template_values)
        assert result == "Product: test-product, Owner: alice@example.com"

    def test_context_field_resolution_still_works(self, step_context_with_template_values):
        """Test ${context.<field>} resolution still works (regression)."""
        template = "User: ${context.user_email}, Entity ID: ${context.entity_id}"
        result = substitute_template(template, step_context_with_template_values)
        assert result == "User: bob@example.com, Entity ID: prod-123"

    def test_flat_scalar_resolution_still_works(self, step_context_with_template_values):
        """Test flat scalars like ${user_email} still resolve (regression)."""
        template = "Requester: ${user_email}, Type: ${entity_type}"
        result = substitute_template(template, step_context_with_template_values)
        assert result == "Requester: bob@example.com, Type: data_product"

    def test_mixed_template_and_entity_fields(self, step_context_with_template_values):
        """Test mixing ${template.<ref>} and ${entity.<field>} in same template."""
        template = (
            "Product: ${entity.name} "
            "(Purpose: ${template.purpose}, "
            "Owner: ${entity.owner})"
        )
        result = substitute_template(template, step_context_with_template_values)
        assert result == (
            "Product: test-product "
            "(Purpose: Analytics, "
            "Owner: alice@example.com)"
        )

    def test_curly_brace_syntax_also_works(self, step_context_with_template_values):
        """Test {{template.<ref>}} syntax (alternate) also works."""
        template = "Purpose: {{template.purpose}}, Owner: {{entity.owner}}"
        result = substitute_template(template, step_context_with_template_values)
        assert result == "Purpose: Analytics, Owner: alice@example.com"

    def test_step_results_resolution_still_works(self, step_context_with_template_values):
        """Test ${step_results.<step>.<field>} resolution still works (regression)."""
        step_context_with_template_values.step_results = {
            "approval_step": {
                "passed": True,
                "reason": "looks good",
            }
        }
        template = "Approval: ${step_results.approval_step.reason}"
        result = substitute_template(template, step_context_with_template_values)
        assert result == "Approval: looks good"

    def test_template_values_with_special_chars(self, step_context_with_template_values):
        """Test template values containing special characters resolve."""
        step_context_with_template_values.template_values = {
            "notes": "Data: PII, Special Chars: <tag> & symbols",
            "owner": "team+data@example.com",
        }
        template = "Notes: ${template.notes}"
        result = substitute_template(template, step_context_with_template_values)
        assert result == "Notes: Data: PII, Special Chars: <tag> & symbols"

    def test_empty_template_values_dict_leaves_placeholder_intact(self):
        """Test that empty template_values dict leaves ${template.<ref>} intact."""
        context = StepContext(
            entity={},
            entity_type="data_product",
            entity_id="prod-123",
            entity_name=None,
            user_email=None,
            trigger_context=None,
            execution_id="exec-456",
            workflow_id="wf-789",
            workflow_name="test-workflow",
            step_results={},
            on_behalf_of=None,
            template_values={},  # Empty but not None
        )
        template = "Purpose: ${template.purpose}"
        result = substitute_template(template, context)
        assert result == "Purpose: ${template.purpose}"
