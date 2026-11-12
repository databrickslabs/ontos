import type { TFunction } from 'i18next';

/** The outcome of one LLM_CHECK: a model verdict (`code` null) or why there is none. */
export interface LlmCheck {
  criterion: string;
  passed: boolean;
  reason?: string;
  code?: string | null;
  cached?: boolean;
}

/** The LLM_CHECKs stored in a compliance result's `details_json` (none if it has none). */
export function parseLlmChecks(detailsJson?: string | null): LlmCheck[] {
  if (!detailsJson) return [];
  try {
    const checks = JSON.parse(detailsJson)?.llm_checks;
    return Array.isArray(checks) ? checks : [];
  } catch {
    return [];
  }
}

/**
 * What an LLM_CHECK found, in the user's language: the model's reason (its
 * own words, not translated) or the translated code
 * (`compliance:llmCheck.codes.<code>`). An unknown code is shown as the code.
 */
export function llmCheckText(t: TFunction, check: LlmCheck): string {
  if (!check.code) return check.reason ?? '';
  return t(`compliance:llmCheck.codes.${check.code}`, { defaultValue: check.code }) as string;
}
