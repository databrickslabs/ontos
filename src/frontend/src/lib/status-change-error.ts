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
 * an admin wrote (a Fail step's message) is shown as written. An update that
 * tries to change the status (`status_change_requires_transition`) and a status
 * that isn't a lifecycle one (`certified_is_not_a_status`, `invalid_status`)
 * are translated too, and so is a `fail_closed` gate that couldn't be evaluated
 * (`status_change_gate_error`). Any other error is the English `error` the API sent.
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
  const statusLabel = (status: unknown) =>
    t(`${statusNamespace}:status.${String(status ?? '')}`, { defaultValue: String(status ?? '') });
  // The lifecycle status checks of src.common.lifecycle_status
  if (response.errorCode === 'status_change_requires_transition' && params) {
    return t('workflow-gates:requiresTransition', {
      fromStatus: statusLabel(params.fromStatus),
      toStatus: statusLabel(params.toStatus),
      defaultValue: error,
    });
  }
  if (response.errorCode === 'certified_is_not_a_status') {
    return t('workflow-gates:certifiedIsNotAStatus', { defaultValue: error });
  }
  if (response.errorCode === 'invalid_status' && params) {
    const allowed = Array.isArray(params.allowed) ? params.allowed : [];
    return t('workflow-gates:invalidStatus', {
      status: String(params.status ?? ''),
      allowed: allowed.map(statusLabel).join(', '),
      defaultValue: error,
    });
  }
  // A fail_closed gate that couldn't be evaluated (#1103)
  if (response.errorCode === 'status_change_gate_error' && params) {
    const workflows = Array.isArray(params.workflows) ? params.workflows.map(String) : [];
    return t(workflows.length ? 'workflow-gates:gateError' : 'workflow-gates:gateErrorUnnamed', {
      fromStatus: statusLabel(params.fromStatus),
      toStatus: statusLabel(params.toStatus),
      workflows: workflows.join(', '),
      defaultValue: error,
    });
  }
  if (response.errorCode !== 'status_change_blocked' || !params) return error;
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

/** The `error` / `errorCode` / `errorParams` of a failed response's JSON body, as useApi gives them. */
export function apiErrorOf(
  body: unknown,
  fallback: string,
): Pick<ApiResponse<unknown>, 'error' | 'errorCode' | 'errorParams'> {
  const detail = (body as { detail?: unknown } | null)?.detail;
  if (typeof detail === 'string') return { error: detail, errorCode: null, errorParams: null };
  if (detail && typeof detail === 'object' && !Array.isArray(detail)) {
    const coded = detail as { code?: string; message?: string; params?: Record<string, unknown> };
    return {
      error: coded.message || fallback,
      errorCode: coded.code ?? null,
      errorParams: coded.params && typeof coded.params === 'object' ? coded.params : null,
    };
  }
  return { error: fallback, errorCode: null, errorParams: null };
}
