import type { TFunction } from 'i18next';

/** A startup problem as `/api/health` and `/api/health/retry` send it. */
export interface HealthIssue {
  code: string;
  message: string;
  params?: Record<string, unknown>;
}

/**
 * The text of a startup problem in the user's language. The backend sends a
 * code and a generic English `message` (never the exception's text); an
 * unknown code shows that message.
 */
export function healthIssueText(issue: HealthIssue, t: TFunction): string {
  return t(`navigation:health.issues.${issue.code}`, {
    ...issue.params,
    defaultValue: issue.message,
  });
}

/** The text of a failed `/api/health/retry` response's `detail`, or null. */
export function retryDetailText(detail: unknown, t: TFunction): string | null {
  if (detail && typeof detail === 'object' && 'code' in detail) {
    return healthIssueText(detail as HealthIssue, t);
  }
  return null;
}
