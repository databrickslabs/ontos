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
  /** Set when the description could not be written to Unity Catalog */
  description_sync?: AssetDescriptionSync | null;
}

/** A warning the UI translates by its code; `message` is the English fallback. */
export interface AssetCodedWarning {
  code: string;
  message: string;
  params?: Record<string, unknown>;
}

/** The asset's description is not in Unity Catalog: why, and since when. */
export interface AssetDescriptionSync extends AssetCodedWarning {
  status: 'out_of_sync';
  at?: string | null;
}

/** GET /api/assets/{id}/description/uc-comment: the Ontos description next to the UC comment. */
export interface AssetUcCommentPreview {
  asset_id: string;
  /** The Unity Catalog object: catalog.schema.table[.column] */
  target: string;
  object_type: string;
  description?: string | null;
  uc_comment?: string | null;
  in_sync: boolean;
  table_type?: string | null;
}

/** POST /api/assets/{id}/description/reset-to-uc */
export interface AssetDescriptionResetResult {
  asset_id: string;
  target: string;
  changed: boolean;
  previous_description?: string | null;
  description?: string | null;
  warnings: AssetCodedWarning[];
}

/** One change of the description of an asset (GET /api/assets/{id}/description/history). */
export interface AssetDescriptionHistoryEntry {
  id: string;
  timestamp: string;
  username?: string | null;
  /** manual, uc_import, bulk_import, uc_reset, restore (more may come) */
  source?: string | null;
  object_type?: string | null;
  before?: string | null;
  after?: string | null;
  restored_from?: string | null;
}

export interface AssetDescriptionHistory {
  asset_id: string;
  total: number;
  items: AssetDescriptionHistoryEntry[];
}

/** One description next to its Unity Catalog comment (GET .../description/drift). */
export interface AssetDriftField {
  asset_id: string;
  name: string;
  /** table, view or column */
  object_type: string;
  target: string;
  description?: string | null;
  uc_comment?: string | null;
  baseline_known: boolean;
  baseline_text?: string | null;
  differs: boolean;
  /** The comment is not what Ontos last saw (needs a recorded baseline) */
  changed_in_uc: boolean;
  missing_in_uc: boolean;
}

export interface AssetDescriptionDrift {
  asset_id: string;
  target: string;
  table_type?: string | null;
  /** The asset itself first, then the Column assets of a table or view */
  fields: AssetDriftField[];
  truncated: boolean;
}

/** One field of POST .../description/reset-selected. */
export interface AssetResetFieldResult {
  asset_id: string;
  target?: string | null;
  changed: boolean;
  warnings: AssetCodedWarning[];
  error?: { code: string; message: string; params?: Record<string, unknown> } | null;
}

export interface AssetResetSelectedResult {
  results: AssetResetFieldResult[];
  changed: number;
  failed: number;
}

/** PUT /api/assets/{id}: the saved asset, with what the save could not do. */
export interface AssetUpdateResult extends AssetRead {
  warnings?: AssetCodedWarning[];
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
