/**
 * Audit Log Types
 *
 * Type definitions for the audit logging system.
 */

export interface AuditLog {
  id: string;
  timestamp: string;
  username: string;
  ip_address?: string;
  feature: string;
  action: string;
  success: boolean;
  details?: Record<string, any>;
}

export interface PaginatedAuditLogResponse {
  total: number;
  items: AuditLog[];
}

export interface AuditLogFilters {
  start_time?: string;
  end_time?: string;
  username?: string;
  feature?: string;
  action?: string;
  success?: boolean;
  skip?: number;
  limit?: number;
}

// Common actions
export const AUDIT_ACTIONS = {
  CREATE: 'CREATE',
  UPDATE: 'UPDATE',
  DELETE: 'DELETE',
  READ: 'READ',
  APPROVE: 'APPROVE',
  REJECT: 'REJECT',
  PUBLISH: 'PUBLISH',
} as const;

export type AuditAction = typeof AUDIT_ACTIONS[keyof typeof AUDIT_ACTIONS];

// Feature IDs (should match backend features.py)
export const AUDIT_FEATURES = {
  SETTINGS: 'settings',
  DATA_PRODUCTS: 'data-products',
  DATA_CONTRACTS: 'data-contracts',
  DATA_DOMAINS: 'data-domains',
  TEAMS: 'teams',
  PROJECTS: 'projects',
  SEMANTIC_MODELS: 'semantic-models',
  COMPLIANCE: 'compliance',
  DATA_ASSET_REVIEWS: 'data-asset-reviews',
  ACCESS_POLICIES: 'access-policies',
  AUDIT: 'audit',
} as const;

export type AuditFeature = typeof AUDIT_FEATURES[keyof typeof AUDIT_FEATURES];
