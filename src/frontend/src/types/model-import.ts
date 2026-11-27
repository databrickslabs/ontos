// Staged erwin model imports (PRD #1718). Mirrors src/backend/src/models/model_import.py
// and the preview/result payloads of controller/model_import_manager.py.

export type ContractGrouping = 'subject_area' | 'schema' | 'table' | 'model';
export type UdpTarget = 'custom_property' | 'tag' | 'classification' | 'critical_data_element' | 'ignore';
export type ModelImportStatus = 'previewed' | 'running' | 'completed' | 'failed' | 'cancelled' | 'expired';
export type ContractAction = 'create' | 'unchanged' | 'update' | 'new_version';

export interface CatalogMapping {
  source: string;
  target: string;
}

export interface UdpMapping {
  udp: string;
  target: UdpTarget;
}

export interface ModelImportOptions {
  import_logical: boolean;
  import_physical: boolean;
  subject_area_ids: string[];
  collection_iri: string | null;
  contract_grouping: ContractGrouping;
  catalog_mappings: CatalogMapping[];
  table_overrides: Record<string, string>;
  dbms: string | null;
  migration_mode: boolean;
  udp_mappings: UdpMapping[];
  domain_by_group: Record<string, string>;
}

export interface ConceptRef {
  iri: string;
  label: string;
}

export interface TableDrift {
  missing_in_uc: string[];
  extra_in_uc: string[];
  type_mismatches: { column: string; modeled: string; modeled_databricks: string; actual: string }[];
  nullability_mismatches: { column: string; modeled_required: boolean; uc_nullable: boolean }[];
}

export interface TableResolution {
  entity_id: string;
  table: string;
  owner: string | null;
  fqn: string | null;
  asset_id: string | null;
  drift: TableDrift | null;
}

export interface SchemaDiff {
  tables_added: string[];
  tables_removed: string[];
  tables_changed: {
    table: string;
    columns_added: string[];
    columns_removed: string[];
    columns_changed: { column: string; fields: string[] }[];
    fields: string[];
  }[];
}

export interface ContractPreview {
  group_key: string;
  group_label: string;
  name: string;
  action: ContractAction;
  tables: string[];
  table_count: number;
  existing_contract_id: string | null;
  existing_status: string | null;
  existing_version: string | null;
  diff: SchemaDiff | null;
  warnings: string[];
}

export interface ModelImportPreview {
  model: {
    id: string;
    name: string;
    model_type: 'logical' | 'physical' | 'logical_physical';
    target_dbms: string | null;
    dbms: string;
    version: string | null;
    entities: number;
    views: number;
    attributes: number;
    relationships: number;
    domains: number;
    udps: string[];
    owners: string[];
    subject_areas: { id: string; name: string; entities: number }[];
  };
  scope: { entities: number; subject_area_ids: string[] };
  previous_run_id: string | null;
  warnings: string[];
  logical: null | {
    collection_iri: string;
    collection_label: string;
    collection_exists: boolean;
    counts: Record<string, number>;
    summary: { unchanged: number; modified: number; new: number; removed: number };
    new: ConceptRef[];
    modified: ConceptRef[];
    removed: ConceptRef[];
  };
  physical: null | {
    counts: Record<ContractAction | 'removed' | 'tables', number>;
    contracts: ContractPreview[];
    removed: { contract_id: string; name: string; status: string; group_key: string }[];
    uc: { resolved: number; unresolved: number; tables: TableResolution[] };
  };
}

export interface ModelImportResult {
  warnings: string[];
  logical: null | {
    collection_iri: string;
    summary: { unchanged: number; modified: number; new: number; removed: number };
    counts: Record<string, number>;
  };
  physical: null | {
    contracts: {
      group_key: string;
      name: string;
      action: ContractAction;
      contract_id?: string;
      previous_contract_id?: string;
      status: 'ok' | 'failed';
      error?: string;
    }[];
    removed: { contract_id: string; name: string }[];
    uc: { resolved: number; unresolved: number; drift: TableResolution[] };
    failed: number;
  };
}

export interface ModelImportRunSummary {
  id: string;
  status: ModelImportStatus;
  source_kind: string;
  source_filename: string | null;
  source_model_name: string | null;
  source_model_version: string | null;
  progress_message: string | null;
  error: string | null;
  user_id: string;
  created_at: string | null;
  completed_at: string | null;
  expires_at: string | null;
}

export interface ModelImportRunDetail extends ModelImportRunSummary {
  source_sha256: string | null;
  source_size_bytes: number | null;
  options: ModelImportOptions | null;
  preview: ModelImportPreview | null;
  confirm_token: string | null;
  result: ModelImportResult | null;
}
