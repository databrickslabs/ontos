import { create } from 'zustand';

/**
 * Install state of the background jobs that gate user-facing features.
 *
 * The regular job endpoints require the 'jobs' feature permission, which non-admin
 * roles do not have, so features read their gating job's state from
 * /api/jobs/capabilities instead. It returns booleans only, for an allowlist of
 * workflow IDs.
 */
export type FeatureGatingWorkflowId = 'dqx_profile_datasets' | 'mdm_match_detect';

interface JobCapabilitiesState {
  installed: Partial<Record<FeatureGatingWorkflowId, boolean>>;
  enablementRequestsAllowed: boolean;
  isLoading: boolean;
  isLoaded: boolean;
  fetchCapabilities: () => Promise<void>;
  isWorkflowInstalled: (workflowId: FeatureGatingWorkflowId) => boolean;
  requestEnablement: (workflowId: FeatureGatingWorkflowId) => Promise<'requested' | 'already_requested' | 'already_installed'>;
}

export const useJobCapabilitiesStore = create<JobCapabilitiesState>()((set, get) => ({
  installed: {},
  enablementRequestsAllowed: false,
  isLoading: false,
  isLoaded: false,

  fetchCapabilities: async () => {
    if (get().isLoaded || get().isLoading) return;

    set({ isLoading: true });
    try {
      const response = await fetch('/api/jobs/capabilities');
      if (response.ok) {
        const data = await response.json();
        const installed: Partial<Record<FeatureGatingWorkflowId, boolean>> = {};
        for (const [workflowId, state] of Object.entries(data.workflows ?? {})) {
          installed[workflowId as FeatureGatingWorkflowId] = Boolean(
            (state as { installed?: boolean }).installed
          );
        }
        set({
          installed,
          enablementRequestsAllowed: Boolean(data.enablement_requests_allowed),
        });
      }
    } catch (err) {
      console.error('Error fetching job capabilities:', err);
    } finally {
      set({ isLoading: false, isLoaded: true });
    }
  },

  isWorkflowInstalled: (workflowId: FeatureGatingWorkflowId) => {
    // Assume available until proven otherwise, so a failed capabilities fetch
    // does not disable working features.
    const { installed, isLoaded } = get();
    if (!isLoaded) return true;
    return installed[workflowId] !== false;
  },

  requestEnablement: async (workflowId: FeatureGatingWorkflowId) => {
    const response = await fetch(`/api/jobs/workflows/${workflowId}/request-enablement`, {
      method: 'POST',
    });
    if (!response.ok) {
      const detail = await response.json().catch(() => null);
      throw new Error(detail?.detail || 'Failed to submit enablement request');
    }
    const data = await response.json();
    if (data.requested) return 'requested';
    return data.reason === 'already_installed' ? 'already_installed' : 'already_requested';
  },
}));
