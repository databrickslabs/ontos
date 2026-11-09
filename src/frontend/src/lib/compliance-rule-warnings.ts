import type { TFunction } from 'i18next';

/** A warning returned when a policy rule is saved but cannot work as written. */
export interface RuleWarning {
  code: string;
  params?: Record<string, string>;
  message: string;
}

/** Translated text of a rule warning; falls back to the API's English message. */
export function formatRuleWarning(t: TFunction, warning: RuleWarning): string {
  return t(`compliance:ruleWarnings.${warning.code}`, {
    ...(warning.params ?? {}),
    defaultValue: warning.message,
  });
}
