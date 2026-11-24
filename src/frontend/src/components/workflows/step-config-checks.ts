import type { TFunction } from 'i18next';

import type {
  EntityType, StepType, TriggerType, WorkflowStepCreate,
} from '@/types/process-workflow';
import { getEntityTypeLabel, getStepTypeLabel, getTriggerTypeLabel } from '@/lib/workflow-labels';
import { isScheduleIssue, scheduleIssueText } from './trigger-schedule-fields';

// Checks of Conditional and Script step configs the designer runs before it
// saves (#943, #942). The codes match src/backend/src/common/workflow_step_config.py.

/** An issue with a step's config: a code to translate, its params, and the English text. */
export interface StepConfigIssue {
  code: string;
  params?: Record<string, unknown>;
  message?: string | null;
}

/** Response of POST /api/workflows/check-condition. */
export interface ConditionCheckResult extends StepConfigIssue {
  valid: boolean;
}

const DEFAULT_SCRIPT_LANGUAGES = ['sql'];
/**
 * The language of a Script step stored without one. Python was the default
 * before Python steps were disabled (src/backend/src/common/workflow_step_config.py),
 * so such a step is shown as Python, not as SQL. New steps get `language: 'sql'`.
 */
export const LEGACY_SCRIPT_LANGUAGE = 'python';

// eslint-disable-next-line @typescript-eslint/no-explicit-any
type JsonSchema = Record<string, any>;

export function scriptSchema(schema: JsonSchema | undefined) {
  const properties = schema?.properties || {};
  const languages: string[] = properties.language?.enum || DEFAULT_SCRIPT_LANGUAGES;
  return {
    languages,
    defaultLanguage: String(properties.language?.default ?? languages[0]),
  };
}

/** A Script step's language as the backend runs it (`LEGACY_SCRIPT_LANGUAGE` when unset). */
export function scriptLanguageOf(config: Record<string, unknown>): string {
  return typeof config.language === 'string' && config.language
    ? config.language
    : LEGACY_SCRIPT_LANGUAGE;
}

// Script issues of the Python and SQL placeholder rules, with their texts in
// `designer.scriptStepSafety` (the backend codes of workflow_step_config.py and
// workflow_sql_params.py)
const SCRIPT_SAFETY_CODES = new Set([
  'script_python_disabled',
  'script_sql_placeholder_in_quotes',
  'script_sql_placeholder_in_identifier',
  'script_sql_placeholder_as_list',
]);

/** The translated text of a step config issue (English text from the backend as fallback). */
export function stepConfigIssueText(issue: StepConfigIssue, t: TFunction): string {
  if (issue.code.startsWith('maturity_bulk_')) {
    return t(`workflows:assetMaturityStep.errors.${issue.code}`, {
      ...(issue.params || {}),
      defaultValue: issue.message || issue.code,
    });
  }
  const namespace = SCRIPT_SAFETY_CODES.has(issue.code)
    ? 'scriptStepSafety'
    : issue.code.startsWith('script_') ? 'script' : 'conditional';
  return t(`workflows:designer.${namespace}.errors.${issue.code}`, {
    ...(issue.params || {}),
    defaultValue: issue.message || issue.code,
  });
}

/** An error of POST/PUT /api/workflows (`detail.params.issues`), see validate_workflow. */
export interface WorkflowValidationIssue {
  code: string;
  message?: string | null;
  params?: Record<string, unknown>;
}

/** The translated text of a workflow validation error (English text from the backend as fallback). */
export function workflowValidationIssueText(issue: WorkflowValidationIssue, t: TFunction): string {
  const params = issue.params || {};
  const fallback = issue.message || issue.code;
  switch (issue.code) {
    case 'workflow_name_required':
      return t('workflows:designer.messages.nameRequired', { defaultValue: fallback });
    case 'workflow_steps_required':
      return t('workflows:designer.validationIssues.stepsRequired', { defaultValue: fallback });
    case 'duplicate_step_ids':
      return t('workflows:designer.validationIssues.duplicateStepIds', { defaultValue: fallback });
    case 'evaluate_asset_maturity_trigger_unsupported':
      return t('workflows:assetMaturityStep.triggerUnsupported', {
        step: params.step,
        trigger: getTriggerTypeLabel(String(params.triggerType) as TriggerType, t),
        defaultValue: fallback,
      });
    // Trigger entity types (#1151): one the app doesn't know, or one the trigger never fires for
    case 'trigger_entity_type_unknown':
      return t('workflows:triggerEntityChecks.unknownOnSave', {
        type: params.entityType,
        defaultValue: fallback,
      });
    case 'trigger_entity_type_required':
      return t('workflows:triggerEntityChecks.requiredOnSave', { defaultValue: fallback });
    case 'trigger_entity_type_unsupported':
      return t('workflows:triggerEntityChecks.unsupportedOnSave', {
        trigger: getTriggerTypeLabel(String(params.triggerType) as TriggerType, t),
        type: getEntityTypeLabel(String(params.entityType) as EntityType, t),
        defaultValue: fallback,
      });
    case 'step_unknown_reference':
      return t('workflows:designer.validationIssues.stepUnknownReference', {
        step: params.step,
        target: params.target,
        branch: t(`workflows:designer.validationIssues.branch.${String(params.field)}`, {
          defaultValue: String(params.field ?? ''),
        }),
        defaultValue: fallback,
      });
    case 'step_config_missing':
      return t('workflows:designer.validationIssues.stepConfigMissing', {
        step: params.step,
        fields: Array.isArray(params.fields) ? params.fields.join(', ') : '',
        defaultValue: fallback,
      });
    case 'assign_tag_value_source_unknown':
      return t('workflows:designer.validationIssues.assignTagValueSourceUnknown', {
        step: params.step,
        source: params.source,
        defaultValue: fallback,
      });
    // A step that commits or acts outside the app as the gate runs (#1403)
    case 'update_gate_step_not_allowed':
      return t('workflows:designer.validationIssues.updateGate.stepNotAllowed', {
        step: params.step,
        type: getStepTypeLabel(String(params.stepType) as StepType, t),
        defaultValue: fallback,
      });
    case 'policy_check_policy_missing':
      return t('workflows:designer.validationIssues.policyCheckPolicyMissing', {
        step: params.step,
        defaultValue: fallback,
      });
    case 'policy_check_policy_uses_llm_check':
      return t('workflows:designer.llmCheckIssues.policyCheckUsesLlmCheck', {
        step: params.step,
        defaultValue: fallback,
      });
    case 'validation_rule_uses_llm_check':
      return t('workflows:designer.llmCheckIssues.validationRuleUsesLlmCheck', {
        step: params.step,
        defaultValue: fallback,
      });
    default:
      if (isScheduleIssue(issue.code)) return scheduleIssueText(issue, t);
      if (!['condition_', 'script_', 'maturity_bulk_'].some(p => issue.code.startsWith(p))) {
        // An error the designer has no text for: the backend's English text.
        return fallback;
      }
      // Conditional, Script and asset maturity checks keep their codes (stepConfigIssueText).
      return t('workflows:designer.messages.stepConfigInvalid', {
        step: params.step,
        issue: stepConfigIssueText({ code: issue.code, params, message: null }, t),
        defaultValue: fallback,
      });
  }
}

/** Issues the designer can find without the backend: a missing condition or code, Python. */
export function localStepConfigIssue(step: WorkflowStepCreate): StepConfigIssue | null {
  const config = (step.config || {}) as Record<string, unknown>;
  if (step.step_type === 'conditional') {
    const condition = config.condition;
    if (typeof condition !== 'string' || !condition.trim()) {
      return { code: 'condition_required' };
    }
  }
  if (step.step_type === 'evaluate_asset_maturity') {
    // As normalize_scope (maturity_bulk_evaluator.py): a schema needs its catalog
    const catalog = typeof config.catalog === 'string' ? config.catalog.trim() : '';
    const schemaName = typeof config.schema_name === 'string' ? config.schema_name.trim() : '';
    if ((schemaName && !catalog) || /[.`]/.test(catalog + schemaName)) {
      return { code: 'maturity_bulk_scope_invalid' };
    }
  }
  if (step.step_type === 'script') {
    const code = config.code;
    if (typeof code !== 'string' || !code.trim()) {
      return { code: 'script_code_required' };
    }
    if (scriptLanguageOf(config) === LEGACY_SCRIPT_LANGUAGE) {
      return { code: 'script_python_disabled' };
    }
  }
  return null;
}
