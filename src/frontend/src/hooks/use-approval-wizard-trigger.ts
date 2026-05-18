/**
 * Portable approval-wizard launch helper.
 *
 * Looks up the currently-configured approval workflow for a given app-action
 * trigger (e.g., 'for_subscribe', 'for_request_access') so any call site can
 * decide whether to open the ApprovalWizardDialog or fall through to the
 * legacy direct-submit path.
 *
 * Replaces three hardcoded `for_subscribe` lookups (data-product-details,
 * marketplace-view, discovery-section) and unblocks the same wizard for the
 * other five `for_request_*` triggers without code changes per workflow.
 *
 * Returns ``null`` when no workflow is configured (404), or on any other
 * error — callers should treat both cases as "no wizard, go direct".
 */
import { useCallback } from 'react';
import { useApi } from '@/hooks/use-api';
import type { TriggerType } from '@/types/process-workflow';

/** Trigger types this hook supports — must match backend APP_ACTION_TRIGGER_TYPES. */
export type AppActionTriggerType = Extract<
  TriggerType,
  | 'for_approval_response'
  | 'for_subscribe'
  | 'for_request_review'
  | 'for_request_access'
  | 'for_request_publish'
  | 'for_request_certify'
  | 'for_request_status_change'
>;

export interface UseApprovalWizardTriggerResult {
  /**
   * Look up the configured approval workflow id for the given trigger type.
   * Returns the workflow id when one is configured, or ``null`` when none is
   * configured (or the lookup fails). Never throws.
   */
  lookupWorkflowId: (triggerType: AppActionTriggerType) => Promise<string | null>;
}

export function useApprovalWizardTrigger(): UseApprovalWizardTriggerResult {
  const { get } = useApi();

  const lookupWorkflowId = useCallback(
    async (triggerType: AppActionTriggerType): Promise<string | null> => {
      try {
        const res = await get<{ id: string }>(`/api/workflows/for-trigger/${triggerType}`);
        return res.data?.id ?? null;
      } catch {
        // 404 (no workflow configured) and other errors both mean "go direct"
        return null;
      }
    },
    [get],
  );

  return { lookupWorkflowId };
}
