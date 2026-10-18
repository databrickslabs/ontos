export type EntityType = 'data_domain' | 'data_product' | 'data_contract' | 'authority_relation';

export interface EntitySemanticLink {
  id: string;
  entity_id: string;
  entity_type: EntityType;
  iri: string;
  label?: string;
}


