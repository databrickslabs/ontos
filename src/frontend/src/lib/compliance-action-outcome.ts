import type { TFunction } from 'i18next';

/** What a policy action did for one result, as the backend stores it in `details_json.actions`. */
export interface ComplianceActionOutcome {
  type: string;
  success: boolean;
  target?: string;
  code?: string;
  params?: Record<string, unknown>;
}

/** The action outcomes of a result; an empty list when it has none or the JSON is not readable. */
export function complianceActionOutcomes(detailsJson?: string | null): ComplianceActionOutcome[] {
  if (!detailsJson) return [];
  try {
    const actions = JSON.parse(detailsJson)?.actions;
    return Array.isArray(actions) ? actions.filter((a) => a && typeof a.type === 'string') : [];
  } catch {
    return [];
  }
}

/** The action, e.g. "Assign tag governance/classification", in the user's language. */
export function complianceActionLabel(t: TFunction, outcome: ComplianceActionOutcome): string {
  return t(`compliance:actionOutcomes.types.${outcome.type}`, {
    target: outcome.target ?? '',
    defaultValue: outcome.target ? `${outcome.type} ${outcome.target}` : outcome.type,
  }) as string;
}

/** Why the action failed, in the user's language; an unknown code is shown as the code. */
export function complianceActionError(t: TFunction, outcome: ComplianceActionOutcome): string {
  if (outcome.success) return '';
  const code = outcome.code || 'action_failed';
  return t(`compliance:actionOutcomes.errors.${code}`, {
    ...(outcome.params ?? {}),
    defaultValue: code,
  }) as string;
}
