export type EntityType =
  | 'data_domain'
  | 'data_product'
  | 'data_contract'
  | 'access_policy'
  | 'access_audience'
  | 'access_asset_collection';

export interface EntitySemanticLink {
  id: string;
  entity_id: string;
  entity_type: EntityType;
  iri: string;
  label?: string;
}


