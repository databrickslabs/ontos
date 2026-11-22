// Mirrors EntityType in src/backend/src/models/semantic_links.py
export type EntityType =
  | 'data_domain' | 'data_product' | 'data_contract'
  | 'data_contract_schema' | 'data_contract_property'
  | 'dataset' | 'asset' | 'uc_catalog' | 'uc_schema' | 'uc_table' | 'uc_column'
  | 'authority_relation';

export interface EntitySemanticLink {
  id: string;
  entity_id: string;
  entity_type: EntityType;
  iri: string;
  label?: string;
}


