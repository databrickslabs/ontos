/**
 * Dataset Types
 *
 * Datasets are logical groupings of related data assets.
 * Physical implementations are represented by DatasetInstance objects.
 */

import type { AssignedTag } from '@/components/ui/tag-chip';

// =============================================================================
// Enums / Type Unions
// =============================================================================

export type DatasetStatus = 'draft' | 'in_review' | 'active' | 'deprecated' | 'retired';

// Environment is used at the instance level only
export type DatasetInstanceEnvironment = 'dev' | 'staging' | 'prod' | 'test' | 'qa' | 'uat';

export type DatasetInstanceRole = 'undefined' | 'main' | 'dimension' | 'lookup' | 'reference' | 'staging';

// =============================================================================
// Custom Property Types
// =============================================================================

export interface DatasetCustomProperty {
  id?: string;
  property: string;
  value?: string;
}

// =============================================================================
// Subscription Types
// =============================================================================

export interface DatasetSubscription {
  id: string;
  dataset_id: string;
  subscriber_email: string;
  subscribed_at: string;
  subscription_reason?: string;
}

export interface DatasetSubscriptionCreate {
  reason?: string;
}

export interface DatasetSubscriptionResponse {
  subscribed: boolean;
  subscription?: DatasetSubscription;
}

export interface DatasetSubscriberInfo {
  email: string;
  subscribed_at: string;
  reason?: string;
}

export interface DatasetSubscribersListResponse {
  dataset_id: string;
  subscriber_count: number;
  subscribers: DatasetSubscriberInfo[];
}

// =============================================================================
// Instance Types (Physical Implementations)
// =============================================================================

export type DatasetInstanceStatus = 'active' | 'deprecated' | 'retired';

export interface DatasetInstance {
  id: string;
  dataset_id: string;

  // Contract linkage
  contract_id?: string;
  contract_name?: string;
  contract_version?: string;

  // Server linkage (from contract)
  contract_server_id?: string;
  server_type?: string;
  server_environment?: string;
  server_name?: string;

  // Physical location
  physical_path: string;
  
  // Asset type (unified across platforms)
  asset_type?: string; // UnifiedAssetType value or null

  // Role and identity within the dataset
  role: DatasetInstanceRole;
  display_name?: string;
  environment?: DatasetInstanceEnvironment;

  // Instance status
  status: DatasetInstanceStatus;
  notes?: string;

  // Tags (from unified tagging system)
  tags?: AssignedTag[];

  // Audit
  created_at?: string;
  updated_at?: string;
  created_by?: string;
  updated_by?: string;
}

export interface DatasetInstanceCreate {
  contract_id?: string;
  contract_server_id?: string;
  physical_path: string;
  asset_type?: string; // UnifiedAssetType value (e.g., 'uc_table', 'snowflake_view')
  role?: DatasetInstanceRole;
  display_name?: string;
  environment?: DatasetInstanceEnvironment;
  status?: DatasetInstanceStatus;
  notes?: string;
  tags?: { tag_fqn?: string; tag_id?: string; assigned_value?: string }[];
}

export interface DatasetInstanceUpdate {
  contract_id?: string;
  contract_server_id?: string;
  physical_path?: string;
  asset_type?: string; // UnifiedAssetType value (e.g., 'uc_table', 'snowflake_view')
  role?: DatasetInstanceRole;
  display_name?: string;
  environment?: DatasetInstanceEnvironment;
  status?: DatasetInstanceStatus;
  notes?: string;
  tags?: { tag_fqn?: string; tag_id?: string; assigned_value?: string }[];
}

export interface DatasetInstanceListResponse {
  dataset_id: string;
  instance_count: number;
  instances: DatasetInstance[];
}

export const DATASET_INSTANCE_STATUS_LABELS: Record<DatasetInstanceStatus, string> = {
  active: 'Active',
  deprecated: 'Deprecated',
  retired: 'Retired',
};

export const DATASET_INSTANCE_STATUS_COLORS: Record<DatasetInstanceStatus, string> = {
  active: 'bg-green-100 text-green-800 dark:bg-green-900 dark:text-green-300',
  deprecated: 'bg-yellow-100 text-yellow-800 dark:bg-yellow-900 dark:text-yellow-300',
  retired: 'bg-red-100 text-red-800 dark:bg-red-900 dark:text-red-300',
};

export const DATASET_INSTANCE_ROLE_LABELS: Record<DatasetInstanceRole, string> = {
  undefined: 'Undefined',
  main: 'Main Table',
  dimension: 'Dimension',
  lookup: 'Lookup',
  reference: 'Reference',
  staging: 'Staging',
};

export const DATASET_INSTANCE_ROLE_COLORS: Record<DatasetInstanceRole, string> = {
  undefined: 'bg-slate-100 text-slate-600 dark:bg-slate-800 dark:text-slate-400',
  main: 'bg-blue-100 text-blue-800 dark:bg-blue-900 dark:text-blue-300',
  dimension: 'bg-purple-100 text-purple-800 dark:bg-purple-900 dark:text-purple-300',
  lookup: 'bg-teal-100 text-teal-800 dark:bg-teal-900 dark:text-teal-300',
  reference: 'bg-gray-100 text-gray-800 dark:bg-gray-700 dark:text-gray-300',
  staging: 'bg-orange-100 text-orange-800 dark:bg-orange-900 dark:text-orange-300',
};

export const DATASET_INSTANCE_ROLE_ICONS: Record<DatasetInstanceRole, string> = {
  undefined: '?',
  main: '⬤',
  dimension: '◆',
  lookup: '◇',
  reference: '○',
  staging: '▲',
};

export const DATASET_INSTANCE_ENVIRONMENT_LABELS: Record<DatasetInstanceEnvironment, string> = {
  dev: 'Development',
  staging: 'Staging',
  prod: 'Production',
  test: 'Test',
  qa: 'QA',
  uat: 'UAT',
};

export const DATASET_INSTANCE_ENVIRONMENT_COLORS: Record<DatasetInstanceEnvironment, string> = {
  dev: 'bg-blue-100 text-blue-800 dark:bg-blue-900 dark:text-blue-300',
  staging: 'bg-purple-100 text-purple-800 dark:bg-purple-900 dark:text-purple-300',
  prod: 'bg-green-100 text-green-800 dark:bg-green-900 dark:text-green-300',
  test: 'bg-gray-100 text-gray-800 dark:bg-gray-700 dark:text-gray-300',
  qa: 'bg-orange-100 text-orange-800 dark:bg-orange-900 dark:text-orange-300',
  uat: 'bg-cyan-100 text-cyan-800 dark:bg-cyan-900 dark:text-cyan-300',
};

// =============================================================================
// Dataset List Item (Lightweight for list views)
// =============================================================================

export interface DatasetListItem {
  id: string;
  name: string;
  description?: string;
  full_path?: string;
  
  // Lifecycle
  status: DatasetStatus;
  version?: string;
  published: boolean;
  
  // Contract reference
  contract_id?: string;
  contract_name?: string;
  
  // Ownership
  owner_team_id?: string;
  owner_team_name?: string;
  project_id?: string;
  project_name?: string;
  
  // Counts
  subscriber_count?: number;
  instance_count?: number;
  
  // Audit
  created_at?: string;
  updated_at?: string;
}

// =============================================================================
// Full Dataset Model
// =============================================================================

export interface Dataset {
  id: string;
  name: string;
  description?: string;

  // Contract reference (optional default contract)
  contract_id?: string;
  contract_name?: string;

  // Ownership and project
  owner_team_id?: string;
  owner_team_name?: string;
  project_id?: string;
  project_name?: string;

  // Lifecycle
  status: DatasetStatus;
  version?: string;
  published: boolean;
  
  // Metadata inheritance
  max_level_inheritance?: number;

  // Related data
  tags?: AssignedTag[];
  custom_properties?: DatasetCustomProperty[];
  instances?: DatasetInstance[];
  subscriber_count?: number;
  instance_count?: number;

  // Audit
  created_at?: string;
  updated_at?: string;
  created_by?: string;
  updated_by?: string;
}

// =============================================================================
// Create/Update Models
// =============================================================================

export interface DatasetCreate {
  name: string;
  description?: string;

  // Contract reference (optional)
  contract_id?: string;

  // Ownership and project
  owner_team_id?: string;
  project_id?: string;

  // Lifecycle
  status?: DatasetStatus;
  version?: string;
  published?: boolean;
  
  // Metadata inheritance
  max_level_inheritance?: number;

  // Optional related data (uses unified tagging system)
  tags?: { tag_fqn?: string; tag_id?: string; assigned_value?: string }[];
  custom_properties?: { property: string; value?: string }[];
}

export interface DatasetUpdate {
  name?: string;
  description?: string;

  // Contract reference
  contract_id?: string;

  // Ownership and project
  owner_team_id?: string;
  project_id?: string;

  // Lifecycle
  status?: DatasetStatus;
  version?: string;
  published?: boolean;
  
  // Metadata inheritance
  max_level_inheritance?: number;

  // Optional related data (uses unified tagging system)
  tags?: { tag_fqn?: string; tag_id?: string; assigned_value?: string }[];
  custom_properties?: { property: string; value?: string }[];
}

// =============================================================================
// Filter/Query Types
// =============================================================================

export interface DatasetFilter {
  status?: DatasetStatus;
  contract_id?: string;
  owner_team_id?: string;
  project_id?: string;
  published?: boolean;
  search?: string;
}

// =============================================================================
// Status Display Helpers
// =============================================================================

export const DATASET_STATUS_LABELS: Record<DatasetStatus, string> = {
  draft: 'Draft',
  in_review: 'In Review',
  active: 'Active',
  deprecated: 'Deprecated',
  retired: 'Retired',
};

export const DATASET_STATUS_COLORS: Record<DatasetStatus, string> = {
  draft: 'bg-gray-100 text-gray-800 dark:bg-gray-700 dark:text-gray-300',
  in_review: 'bg-amber-100 text-amber-800 dark:bg-amber-900 dark:text-amber-300',
  active: 'bg-green-100 text-green-800 dark:bg-green-900 dark:text-green-300',
  deprecated: 'bg-yellow-100 text-yellow-800 dark:bg-yellow-900 dark:text-yellow-300',
  retired: 'bg-red-100 text-red-800 dark:bg-red-900 dark:text-red-300',
};
