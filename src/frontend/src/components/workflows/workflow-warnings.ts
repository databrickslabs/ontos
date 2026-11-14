import type { TFunction } from 'i18next';

import type { TriggerType, EntityType } from '@/types/process-workflow';
import { getEntityTypeLabel, getTriggerTypeLabel } from '@/lib/workflow-labels';
import type { WorkflowValidationIssue } from './step-config-checks';
import { TRIGGER_NODE_ID } from './workflow-entry-step';

// Warnings of POST /api/workflows/validate (`warning_issues`) and the stored trigger
// warnings of GET /api/workflows/{id} (`trigger_warnings`), coded per validate_workflow
// and stored_trigger_warnings in the backend. Warnings don't block a save.

/** The translated text of a warning (the backend's English text for a code it doesn't know). */
export function workflowWarningText(issue: WorkflowValidationIssue, t: TFunction): string {
  const params = issue.params || {};
  const fallback = issue.message || issue.code;
  switch (issue.code) {
    case 'terminal_step_has_next':
      return t('workflows:designer.validationWarnings.terminalStepHasNext', {
        step: params.step,
        target: params.target,
        defaultValue: fallback,
      });
    case 'conditional_branch_missing':
      return t('workflows:designer.validationWarnings.conditionalBranchMissing', {
        step: params.step,
        branch: t(`workflows:designer.edgeLabels.${String(params.branch)}`, {
          defaultValue: String(params.branch ?? ''),
        }),
        defaultValue: fallback,
      });
    case 'unreachable_steps':
      return t('workflows:designer.validationWarnings.unreachableSteps', {
        steps: Array.isArray(params.steps) ? params.steps.join(', ') : '',
        defaultValue: fallback,
      });
    case 'stored_entity_type_unknown':
      return t('workflows:designer.validationWarnings.storedEntityTypeUnknown', {
        entityType: params.entityType,
        defaultValue: fallback,
      });
    case 'stored_entity_type_unsupported':
      return t('workflows:designer.validationWarnings.storedEntityTypeUnsupported', {
        trigger: getTriggerTypeLabel(String(params.triggerType) as TriggerType, t),
        entity: getEntityTypeLabel(String(params.entityType) as EntityType, t),
        defaultValue: fallback,
      });
    default:
      return fallback;
  }
}

/** The canvas nodes an issue (warning or error) is about: its step, its unreachable steps, or the trigger. */
export function workflowIssueNodeIds(issue: WorkflowValidationIssue, stepIds: readonly string[]): string[] {
  const params = issue.params || {};
  if (issue.code.startsWith('stored_entity_type_') || issue.code.startsWith('trigger_entity_type_')) {
    return [TRIGGER_NODE_ID];
  }
  if (Array.isArray(params.steps)) {
    return params.steps.map(String).filter(id => stepIds.includes(id));
  }
  if (typeof params.step === 'string' && stepIds.includes(params.step)) {
    return [params.step];
  }
  return [];
}
