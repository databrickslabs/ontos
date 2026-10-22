export type CloudType = 'aws' | 'azure' | 'gcp';
export type SyncStatus = 'pending' | 'running' | 'success' | 'failed';
export type ConnectionType = 'delta_share' | 'database';
export type SharingResourceType =
  | 'data_product'
  | 'data_contract'
  | 'business_term'
  | 'data_domain'
  | 'concept';
export type SharingRuleOperator = 'equals' | 'contains' | 'starts_with' | 'regex';
export type SharingPolicyDirection = 'export' | 'import';

export const SHARING_RESOURCE_TYPES: [SharingResourceType, ...SharingResourceType[]] = [
  'data_product',
  'data_contract',
  'business_term',
  'data_domain',
  'concept',
];

export interface SharingRule {
  filter_type: string;
  operator: SharingRuleOperator;
  filter_value: string;
}

export interface SharingPolicy {
  id?: string;
  name: string;
  description?: string;
  resource_type: SharingResourceType;
  rules: SharingRule[];
  is_enabled: boolean;
  created_at: string; // ISO datetime string
  updated_at: string; // ISO datetime string
}

export interface Estate {
  id: string;
  name: string;
  description: string;
  workspace_url: string;
  cloud_type: CloudType;
  metastore_name: string;
  connection_type: ConnectionType;
  /** What this instance shares with the estate. */
  export_policies: SharingPolicy[];
  /** What this instance accepts from the estate. */
  import_policies: SharingPolicy[];
  is_enabled: boolean;
  sync_schedule: string;
  last_sync_time?: string;
  last_sync_status?: SyncStatus;
  last_sync_error?: string;
  created_at: string;
  updated_at: string;
}

/** The estate with ``policy`` appended to its export or import policies. */
export function withPolicy(
  estate: Estate,
  direction: SharingPolicyDirection,
  policy: SharingPolicy,
): Estate {
  return direction === 'export'
    ? { ...estate, export_policies: [...(estate.export_policies || []), policy] }
    : { ...estate, import_policies: [...(estate.import_policies || []), policy] };
}
