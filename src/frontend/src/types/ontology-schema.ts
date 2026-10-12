/**
 * Types for the Ontology Schema API (/api/ontology/entity-types).
 * These drive dynamic UI rendering — forms, relationship panels, hierarchy views.
 */

export interface EntityTypeDefinition {
  iri: string;
  local_name: string;
  label: string;
  comment?: string | null;
  model_tier: 'dedicated' | 'asset';
  ui_icon?: string | null;
  ui_category?: string | null;
  ui_display_order?: number | null;
  persona_visibility?: string[] | null;
  parent_class?: string | null;
  parent_class_label?: string | null;
}

export interface EntityFieldDefinition {
  iri: string;
  name: string;
  label: string;
  comment?: string | null;
  range_type: string;
  field_type: string;
  field_order: number;
  is_required: boolean;
  field_group: string;
  select_options?: string[] | null;
}

export interface EntityTypeSchema {
  type_iri: string;
  type_label: string;
  model_tier: string;
  fields: EntityFieldDefinition[];
  json_schema?: Record<string, any> | null;
}

export interface RelationshipDefinition {
  property_iri: string;
  property_name: string;
  label: string;
  inverse_label?: string | null;
  source_type_iri: string;
  source_type_label?: string | null;
  target_type_iri: string;
  target_type_label?: string | null;
  cardinality: string;
  display_context: string;
  direction: 'outgoing' | 'incoming';
}

export interface EntityRelationships {
  type_iri: string;
  outgoing: RelationshipDefinition[];
  incoming: RelationshipDefinition[];
}

export interface EntityRelationshipRecord {
  id: string;
  source_type: string;
  source_id: string;
  target_type: string;
  target_id: string;
  relationship_type: string;
  relationship_label?: string | null;
  properties?: Record<string, any> | null;
  created_by?: string | null;
  created_at: string;
}

export interface EntitySubscription {
  id: string;
  entity_type: string;
  entity_id: string;
  subscriber_email: string;
  subscription_reason?: string | null;
  created_at: string;
}

export interface InstanceHierarchyNode {
  entity_type: string;
  entity_id: string;
  name: string;
  status?: string | null;
  icon?: string | null;
  description?: string | null;
  properties?: Record<string, any> | null;
  child_count: number;
  children: InstanceHierarchyNode[];
  relationship_type?: string | null;
  relationship_label?: string | null;
}

export interface HierarchyRootGroup {
  entity_type: string;
  label: string;
  icon?: string | null;
  roots: InstanceHierarchyNode[];
}

export interface ProductDatasetSummary {
  relationship_id: string;
  dataset_id: string;
  name: string;
  description?: string | null;
  status: string;
  properties?: Record<string, any>;
  tags?: string[];
  created_at?: string | null;
}

export interface HierarchyColumn {
  id: string;
  name: string;
  properties?: Record<string, any>;
}

export interface HierarchyTableOrView {
  id: string;
  name: string;
  location?: string | null;
  status: string;
  properties?: Record<string, any>;
  columns: HierarchyColumn[];
}

export interface HierarchyDataset {
  dataset_id: string;
  name: string;
  description?: string | null;
  status: string;
  properties?: Record<string, any>;
  tables: HierarchyTableOrView[];
  views: HierarchyTableOrView[];
  contract?: { id: string; type: string } | null;
}

export interface ProductHierarchy {
  product_id: string;
  product_name: string;
  datasets: HierarchyDataset[];
}


export interface LineageGraphNode {
  id: string;
  entity_type: string;
  entity_id: string;
  name: string;
  icon?: string | null;
  status?: string | null;
  description?: string | null;
  domain?: string | null;
  is_center: boolean;
  /** Model layer: business | delivery | logical | physical | other */
  layer?: string | null;
  /** Owning entity id (contract for schema objects/properties, product for output ports) */
  context_id?: string | null;
}

export interface LineageGraphEdge {
  source: string;
  target: string;
  relationship_type: string;
  label?: string | null;
  /** Computed at query time rather than stored */
  derived?: boolean;
  /** Stored direction points against the flow (target is upstream), e.g. dependsOn */
  reversed?: boolean;
}

export interface LineageGraph {
  center_entity_type: string;
  center_entity_id: string;
  nodes: LineageGraphNode[];
  edges: LineageGraphEdge[];
  /** Walk stopped at the backend node budget; the graph is incomplete */
  truncated?: boolean;
}

export interface ReadinessCheck {
  name: string;
  status: 'pass' | 'fail' | 'warn';
  detail: string;
}

export interface ReadinessReport {
  product_id: string;
  product_name: string;
  checks: ReadinessCheck[];
  overall: 'ready' | 'not_ready' | 'partial';
}
