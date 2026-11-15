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

/** The error fields of an API response (see `useApi`). */
interface CodedErrorResponse {
  error?: string | null;
  errorCode?: string | null;
  errorParams?: Record<string, unknown> | null;
}

/**
 * Why a rule test or a run of an LLM_CHECK rule was refused, in the user's
 * language when the backend sent a code for it (`compliance:llmCheck.errors.<code>`,
 * then `compliance:saveErrors.<code>`); otherwise the API's message, else `fallback`.
 */
export function llmCheckErrorText(
  t: TFunction,
  response: CodedErrorResponse,
  fallback = '',
): string {
  const defaultValue = response.error || fallback;
  if (!response.errorCode) return defaultValue;
  return t(
    [
      `compliance:llmCheck.errors.${response.errorCode}`,
      `compliance:saveErrors.${response.errorCode}`,
    ],
    { ...(response.errorParams ?? {}), defaultValue },
  ) as string;
}

/** The LLM_CHECK usage of a compliance run (null: not counted, a run from before). */
export interface LlmUsage {
  llm_calls?: number | null;
  llm_cache_hits?: number | null;
}

/**
 * How many model calls a run's LLM_CHECKs made and how many verdicts came from
 * the cache, or null when the run counted none (no LLM_CHECK, or an older run).
 */
export function llmUsageText(t: TFunction, run: LlmUsage): string | null {
  const calls = run.llm_calls ?? 0;
  const cached = run.llm_cache_hits ?? 0;
  if (!calls && !cached) return null;
  return t('compliance:llmCheck.usage', { calls, cached }) as string;
}
