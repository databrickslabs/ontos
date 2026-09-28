/**
 * ODCS (Open Data Contract Standard) Lifecycle State Machine
 *
 * Implements the data contract lifecycle transitions.
 */

/**
 * Data Contract Status values
 */
export const DataContractStatus = {
  DRAFT: 'draft',
  PROPOSED: 'proposed',
  UNDER_REVIEW: 'under_review',
  APPROVED: 'approved',
  ACTIVE: 'active',
  DEPRECATED: 'deprecated',
  RETIRED: 'retired',
} as const;

export type DataContractStatusType = typeof DataContractStatus[keyof typeof DataContractStatus];

/**
 * Supported ODCS apiVersions (newest first). Fallback used when the
 * `/api/data-contracts/meta/odcs-versions` endpoint is unavailable.
 */
export const SUPPORTED_ODCS_VERSIONS = [
  'v3.2.0', 'v3.1.0', 'v3.0.2', 'v3.0.1', 'v3.0.0',
] as const;

export const LATEST_ODCS_VERSION = 'v3.2.0';

/** Parse "v3.2.0" -> [3,2,0] for numeric comparison. */
function parseOdcsVersion(v: string): number[] {
  const cleaned = (v || '').replace(/^v/i, '');
  return cleaned.split('.').map((n) => parseInt(n, 10) || 0);
}

/** True if apiVersion `a` is strictly newer than `b`. */
export function isNewerOdcsVersion(a: string, b: string): boolean {
  const pa = parseOdcsVersion(a);
  const pb = parseOdcsVersion(b);
  for (let i = 0; i < Math.max(pa.length, pb.length); i++) {
    const x = pa[i] || 0;
    const y = pb[i] || 0;
    if (x !== y) return x > y;
  }
  return false;
}

/** Supported versions strictly newer than `current` (candidate upgrade targets, newest first). */
export function odcsUpgradeTargets(
  current: string,
  supported: readonly string[] = SUPPORTED_ODCS_VERSIONS,
): string[] {
  return supported.filter((v) => isNewerOdcsVersion(v, current));
}

/** True if the contract's apiVersion is older than the latest supported version. */
export function canUpgradeOdcsVersion(current: string): boolean {
  return isNewerOdcsVersion(LATEST_ODCS_VERSION, current || '');
}

/**
 * Defines allowed status transitions for ODCS lifecycle.
 *
 * Lifecycle flow:
 * draft → proposed → under_review → approved → active → deprecated → retired
 *
 * Additional rules:
 * - Can go back from proposed/under_review to draft (refinement)
 * - Can jump from any status to deprecated (emergency deprecation)
 * - Retired is terminal (no transitions out)
 * - Rejected contracts go back to draft
 */
export const ALLOWED_TRANSITIONS: Record<string, string[]> = {
  [DataContractStatus.DRAFT]: [
    DataContractStatus.PROPOSED,
    DataContractStatus.DEPRECATED, // Emergency deprecation
  ],
  [DataContractStatus.PROPOSED]: [
    DataContractStatus.DRAFT, // Back to refinement
    DataContractStatus.UNDER_REVIEW,
    DataContractStatus.DEPRECATED, // Emergency deprecation
  ],
  [DataContractStatus.UNDER_REVIEW]: [
    DataContractStatus.DRAFT, // Rejected/needs work
    DataContractStatus.APPROVED,
    DataContractStatus.DEPRECATED, // Emergency deprecation
  ],
  [DataContractStatus.APPROVED]: [
    DataContractStatus.ACTIVE,
    DataContractStatus.DRAFT, // Send back for rework
    DataContractStatus.DEPRECATED, // Emergency deprecation
  ],
  [DataContractStatus.ACTIVE]: [
    DataContractStatus.DEPRECATED,
  ],
  [DataContractStatus.DEPRECATED]: [
    DataContractStatus.RETIRED,
    DataContractStatus.ACTIVE, // Reactivation (if deprecation was premature)
  ],
  [DataContractStatus.RETIRED]: [], // Terminal state
};

/**
 * Status display configuration for UI
 */
export interface StatusConfig {
  label: string;
  description: string;
  variant: 'default' | 'secondary' | 'destructive' | 'outline';
  icon?: string;
}

export const STATUS_CONFIG: Record<string, StatusConfig> = {
  [DataContractStatus.DRAFT]: {
    label: 'Draft',
    description: 'Under development, not yet submitted for review',
    variant: 'secondary',
    icon: '✏️',
  },
  [DataContractStatus.PROPOSED]: {
    label: 'Proposed',
    description: 'Submitted for review consideration',
    variant: 'secondary',
    icon: '📝',
  },
  [DataContractStatus.UNDER_REVIEW]: {
    label: 'Under Review',
    description: 'Being reviewed by data steward',
    variant: 'secondary',
    icon: '👀',
  },
  [DataContractStatus.APPROVED]: {
    label: 'Approved',
    description: 'Approved by steward, ready to activate',
    variant: 'default',
    icon: '✓',
  },
  [DataContractStatus.ACTIVE]: {
    label: 'Active',
    description: 'In production use, governing data assets',
    variant: 'default',
    icon: '✅',
  },
  [DataContractStatus.DEPRECATED]: {
    label: 'Deprecated',
    description: 'Still available but marked for retirement',
    variant: 'outline',
    icon: '⚠️',
  },
  [DataContractStatus.RETIRED]: {
    label: 'Retired',
    description: 'No longer in use, archived',
    variant: 'destructive',
    icon: '🔒',
  },
};

/**
 * Checks if a status transition is allowed
 */
export function canTransitionTo(currentStatus: string, targetStatus: string): boolean {
  const normalizedCurrent = currentStatus.toLowerCase();
  const normalizedTarget = targetStatus.toLowerCase();

  if (normalizedCurrent === normalizedTarget) {
    return false; // No transition to same status
  }

  const allowedTargets = ALLOWED_TRANSITIONS[normalizedCurrent] || [];
  return allowedTargets.includes(normalizedTarget);
}

/**
 * Gets all allowed target statuses from current status
 */
export function getAllowedTransitions(currentStatus: string): string[] {
  const normalizedCurrent = currentStatus.toLowerCase();
  return ALLOWED_TRANSITIONS[normalizedCurrent] || [];
}

/**
 * Gets status configuration for UI display
 */
export function getStatusConfig(status: string): StatusConfig {
  const normalizedStatus = status.toLowerCase();
  return STATUS_CONFIG[normalizedStatus] || {
    label: status,
    description: 'Unknown status',
    variant: 'secondary',
  };
}

/**
 * Validates a status transition and returns error message if invalid
 */
export function validateTransition(
  currentStatus: string,
  targetStatus: string
): { valid: boolean; error?: string } {
  const normalizedCurrent = currentStatus.toLowerCase();
  const normalizedTarget = targetStatus.toLowerCase();

  // Check if target status exists
  const validStatuses = Object.values(DataContractStatus);
  if (!validStatuses.includes(normalizedTarget as any)) {
    return {
      valid: false,
      error: `Invalid target status: ${targetStatus}`,
    };
  }

  // Check if same status
  if (normalizedCurrent === normalizedTarget) {
    return {
      valid: false,
      error: 'Contract is already in this status',
    };
  }

  // Check if transition is allowed
  if (!canTransitionTo(normalizedCurrent, normalizedTarget)) {
    const currentConfig = getStatusConfig(normalizedCurrent);
    const targetConfig = getStatusConfig(normalizedTarget);
    const allowedTransitions = getAllowedTransitions(normalizedCurrent);
    return {
      valid: false,
      error: `Cannot transition from ${currentConfig.label} to ${targetConfig.label}. Allowed transitions: ${
        allowedTransitions.length > 0
          ? allowedTransitions.map((s) => getStatusConfig(s).label).join(', ')
          : 'none'
      }`,
    };
  }

  return { valid: true };
}

/**
 * Gets recommended next action for current status
 */
export function getRecommendedAction(currentStatus: string): string | null {
  const normalizedCurrent = currentStatus.toLowerCase();

  switch (normalizedCurrent) {
    case DataContractStatus.DRAFT:
      return 'Submit for review (Proposed) when ready';
    case DataContractStatus.PROPOSED:
      return 'Wait for steward to move to Under Review';
    case DataContractStatus.UNDER_REVIEW:
      return 'Steward will approve or request changes';
    case DataContractStatus.APPROVED:
      return 'Activate when ready to govern production data';
    case DataContractStatus.ACTIVE:
      return 'Deprecate when planning retirement; use the certification panel for certification';
    case DataContractStatus.DEPRECATED:
      return 'Retire when no longer in use';
    case DataContractStatus.RETIRED:
      return null; // Terminal state
    default:
      return null;
  }
}

