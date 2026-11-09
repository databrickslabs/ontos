import type { TFunction } from 'i18next';

import type { WorkflowStepCreate } from '@/types/process-workflow';

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

const DEFAULT_SCRIPT_LANGUAGES = ['python', 'sql'];
const DEFAULT_SCRIPT_TIMEOUT = 60;

// eslint-disable-next-line @typescript-eslint/no-explicit-any
type JsonSchema = Record<string, any>;

export function scriptSchema(schema: JsonSchema | undefined) {
  const properties = schema?.properties || {};
  const languages: string[] = properties.language?.enum || DEFAULT_SCRIPT_LANGUAGES;
  return {
    languages,
    defaultLanguage: String(properties.language?.default ?? languages[0]),
    defaultTimeout: Number(properties.timeout_seconds?.default ?? DEFAULT_SCRIPT_TIMEOUT),
    minimumTimeout: Number(properties.timeout_seconds?.minimum ?? 1),
  };
}

/** The translated text of a step config issue (English text from the backend as fallback). */
export function stepConfigIssueText(issue: StepConfigIssue, t: TFunction): string {
  const namespace = issue.code.startsWith('script_') ? 'script' : 'conditional';
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
    default:
      if (!(issue.code.startsWith('condition_') || issue.code.startsWith('script_'))) {
        // An error the designer has no text for: the backend's English text.
        return fallback;
      }
      // Conditional and Script checks keep their own codes (stepConfigIssueText).
      return t('workflows:designer.messages.stepConfigInvalid', {
        step: params.step,
        issue: stepConfigIssueText({ code: issue.code, params, message: null }, t),
        defaultValue: fallback,
      });
  }
}

/** Issues the designer can find without the backend: a missing condition or code, a bad timeout. */
export function localStepConfigIssue(
  step: WorkflowStepCreate,
  schema?: JsonSchema,
): StepConfigIssue | null {
  const config = (step.config || {}) as Record<string, unknown>;
  if (step.step_type === 'conditional') {
    const condition = config.condition;
    if (typeof condition !== 'string' || !condition.trim()) {
      return { code: 'condition_required' };
    }
  }
  if (step.step_type === 'script') {
    const code = config.code;
    if (typeof code !== 'string' || !code.trim()) {
      return { code: 'script_code_required' };
    }
    // Only Python scripts use the timeout; the form hides the field for SQL.
    const timeout = config.timeout_seconds;
    const { minimumTimeout, defaultLanguage } = scriptSchema(schema);
    const language = typeof config.language === 'string' ? config.language : defaultLanguage;
    if (
      language !== 'sql'
      && timeout !== undefined
      && (!Number.isInteger(timeout) || (timeout as number) < minimumTimeout)
    ) {
      return { code: 'script_timeout_invalid', params: { minimum: minimumTimeout } };
    }
  }
  return null;
}
