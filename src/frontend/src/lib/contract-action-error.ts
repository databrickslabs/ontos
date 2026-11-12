import type { TFunction } from 'i18next';
import type { ApiResponse } from '@/hooks/use-api';
import { statusChangeErrorText } from '@/lib/status-change-error';

/**
 * The error of a contract action (Approve or Reject on the contract page, a
 * request from the request dialog), in the user's language.
 *
 * - `status_change_blocked`: a workflow gate blocked the change, translated
 *   by `statusChangeErrorText`.
 * - `invalid_status_transition`: the contract's status no longer allows the
 *   decision (approved or rejected elsewhere meanwhile); names that status.
 *   Without a status to name, the API's message is shown.
 * - `review_schema_required`: a draft without a schema can't be proposed for
 *   review.
 *
 * Any other error is shown as the API sent it, and `fallback` when it sent
 * none.
 */
export function contractActionErrorText(
  response: Pick<ApiResponse<unknown>, 'error' | 'errorCode' | 'errorParams'>,
  t: TFunction,
  fallback = '',
): string {
  const defaultValue = response.error || fallback;
  const fromStatus = String(response.errorParams?.fromStatus ?? '');
  if (response.errorCode === 'invalid_status_transition' && fromStatus) {
    const status = fromStatus;
    return t('data-contracts:detailsView.errors.invalidTransition', {
      fromStatus: t(`data-contracts:status.${status}`, { defaultValue: status }),
      defaultValue,
    });
  }
  if (response.errorCode === 'review_schema_required') {
    return t('data-contracts:requests.errors.reviewSchemaRequired', { defaultValue });
  }
  return statusChangeErrorText(response, t, 'data-contracts') || fallback;
}
