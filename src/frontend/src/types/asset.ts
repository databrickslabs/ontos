import { AssignedDomain } from '@/types/data-domain';

// --- Asset Types ---
export type AssetTypeCategory = 'data' | 'analytics' | 'integration' | 'system' | 'custom';
// Must match backend AssetTypeCategory enum: data, analytics, integration, system, custom
export type AssetTypeStatus = 'active' | 'deprecated';

export interface AssetTypeRead {
  id: string;
  name: string;
  description?: string | null;
  category?: AssetTypeCategory | null;
  icon?: string | null;
  required_fields?: Record<string, any> | null;
  optional_fields?: Record<string, any> | null;
  allowed_relationships?: string[] | null;
  is_system: boolean;
  status: AssetTypeStatus;
  asset_count: number;
  created_by?: string | null;
  created_at: string;
  updated_at: string;
}

export interface AssetTypeCreate {
  name: string;
  description?: string | null;
  category?: AssetTypeCategory | null;
  icon?: string | null;
  required_fields?: Record<string, any> | null;
  optional_fields?: Record<string, any> | null;
  allowed_relationships?: string[] | null;
  is_system?: boolean;
  status?: AssetTypeStatus;
}

export interface AssetTypeUpdate {
  name?: string | null;
  description?: string | null;
  category?: AssetTypeCategory | null;
  icon?: string | null;
  required_fields?: Record<string, any> | null;
  optional_fields?: Record<string, any> | null;
  allowed_relationships?: string[] | null;
  is_system?: boolean | null;
  status?: AssetTypeStatus | null;
}

// --- Assets ---
export type AssetStatus = 'draft' | 'active' | 'deprecated' | 'retired';

export interface AssetRelationship {
  id: string;
  source_asset_id: string;
  target_asset_id: string;
  relationship_type: string;
  properties?: Record<string, any> | null;
  created_by?: string | null;
  created_at: string;
}

export interface AssetRead {
  id: string;
  name: string;
  description?: string | null;
  asset_type_id: string;
  asset_type_name?: string | null;
  platform?: string | null;
  location?: string | null;
  domain_id?: string | null; // Legacy single-domain (primary); prefer domain_ids
  domain_ids?: string[]; // Multi-domain assignment (primary included)
  primary_domain_id?: string | null;
  domains?: AssignedDomain[]; // Assigned domains with names + primary flag
  properties?: Record<string, any> | null;
  tags?: string[] | null;
  status: AssetStatus;
  certification_level?: number | null;
  inherited_certification_level?: number | null;
  certified_at?: string | null;
  certified_by?: string | null;
  certification_expires_at?: string | null;
  certification_notes?: string | null;
  parent_id?: string | null;
  parent_name?: string | null;
  relationships: AssetRelationship[];
  created_by?: string | null;
  created_at: string;
  updated_at: string;
}

export interface AssetCreate {
  name: string;
  description?: string | null;
  asset_type_id: string;
  platform?: string | null;
  location?: string | null;
  domain_ids?: string[]; // Multi-domain assignment (primary included)
  primary_domain_id?: string | null;
  properties?: Record<string, any> | null;
  tags?: string[] | null;
  status?: AssetStatus;
}

export interface AssetUpdate {
  name?: string | null;
  description?: string | null;
  asset_type_id?: string | null;
  platform?: string | null;
  location?: string | null;
  domain_ids?: string[]; // Replace-all; omit to leave unchanged
  primary_domain_id?: string | null;
  properties?: Record<string, any> | null;
  tags?: string[] | null;
  status?: AssetStatus | null;
}
