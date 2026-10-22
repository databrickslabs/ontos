import type { TFunction } from 'i18next';

/** The fields of a workflow execution that describe why it failed. */
export interface WorkflowExecutionErrorFields {
  error_message?: string | null;
  error_code?: string | null;
  error_params?: Record<string, unknown> | null;
}

/**
 * Why an execution failed, in the user's language when the backend sent the
 * failed step's code for it (``workflows:execution.stepErrors.<code>``);
 * otherwise ``defaultText`` (a shipped fail step's message in the user's
 * language, else as stored).
 */
export function workflowExecutionErrorText(
  t: TFunction,
  execution: WorkflowExecutionErrorFields,
  defaultText: (text: string | undefined | null) => string | undefined,
): string | undefined {
  if (!execution.error_message) return undefined;
  if (!execution.error_code) return defaultText(execution.error_message);
  return t(`workflows:execution.stepErrors.${execution.error_code}`, {
    ...(execution.error_params ?? {}),
    defaultValue: execution.error_message,
  }) as string;
}
