import type { TFunction } from 'i18next';
import type { ApiResponse } from '@/hooks/use-api';

/** Codes of the parent checks of a domain create / update, with their message keys. */
const PARENT_ERROR_KEYS: Record<string, string> = {
  domain_parent_not_found: 'data-domains:form.parentErrors.notFound',
  domain_parent_cycle: 'data-domains:form.parentErrors.cycle',
  domain_hierarchy_cycle: 'data-domains:form.parentErrors.existingCycle',
};

/**
 * The error of a domain create / update, in the user's language: a parent that no
 * longer exists (`domain_parent_not_found`), one that would close a loop
 * (`domain_parent_cycle`) or one whose ancestors already loop (`domain_hierarchy_cycle`).
 * Any other error is shown as the API sent it.
 */
export function domainParentErrorText(
  response: Pick<ApiResponse<unknown>, 'error' | 'errorCode'>,
  t: TFunction,
): string {
  const key = PARENT_ERROR_KEYS[response.errorCode ?? ''];
  const message = response.error ?? '';
  return key ? String(t(key, { defaultValue: message })) : message;
}
