import type { TFunction } from 'i18next';
import type { ApiResponse } from '@/hooks/use-api';

/** A workflow's reason, as `failed_execution_reasons` sends it. */
interface BlockedReason {
  workflow?: string | null;
  text: string;
  code?: string;
  params?: Record<string, unknown>;
}

const REASON_KEYS: Record<string, string> = {
  waiting_for_approval: 'workflow-gates:reasons.waitingForApproval',
  rule_entity_load_failed: 'workflow-gates:reasons.entityLoadFailed',
};

function reasonText(reason: BlockedReason, t: TFunction): string {
  let text = reason.text;
  if (reason.code === 'execution_status') {
    const status = String(reason.params?.status ?? '');
    text = t(`workflow-gates:reasons.status.${status}`, { defaultValue: reason.text });
  } else if (reason.code && REASON_KEYS[reason.code]) {
    text = t(REASON_KEYS[reason.code], { ...reason.params, defaultValue: reason.text });
  }
  return reason.workflow ? `${reason.workflow}: ${text}` : text;
}

/**
 * The error of a failed status change, in the user's language.
 *
 * When a before_status_change workflow blocks the change, the backend answers
 * `detail = {code: 'status_change_blocked', message, params}`: `params` has
 * the statuses and one reason per workflow, `{workflow, text}`, plus a `code`
 * and `params` for the reasons the app writes. Those are translated; a reason
 * an admin wrote (a Fail step's message) is shown as written. Any other error
 * is the English `error` the API sent.
 *
 * `statusNamespace` is the namespace whose `status.<status>` keys label the
 * entity's statuses (`data-products`, `data-contracts`).
 */
export function statusChangeErrorText(
  response: Pick<ApiResponse<unknown>, 'error' | 'errorCode' | 'errorParams'>,
  t: TFunction,
  statusNamespace: string,
): string {
  const error = response.error || '';
  const params = response.errorParams;
  if (response.errorCode !== 'status_change_blocked' || !params) return error;
  const statusLabel = (status: unknown) =>
    t(`${statusNamespace}:status.${String(status ?? '')}`, { defaultValue: String(status ?? '') });
  const reasons = Array.isArray(params.reasons) ? (params.reasons as BlockedReason[]) : [];
  return t('workflow-gates:blocked', {
    fromStatus: statusLabel(params.fromStatus),
    toStatus: statusLabel(params.toStatus),
    reasons: reasons.length
      ? reasons.map(reason => reasonText(reason, t)).join('; ')
      : t('workflow-gates:reasons.validationFailed'),
    defaultValue: error,
  });
}
