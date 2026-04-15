// ============================================================================
// ENUMS
// ============================================================================

export type CollectionType = 'glossary' | 'taxonomy' | 'ontology';

export type ScopeLevel = 'enterprise' | 'domain' | 'department' | 'team' | 'project' | 'external';

export type SourceType = 'custom' | 'imported';

export type ConceptStatus = 'draft' | 'under_review' | 'approved' | 'active' | 'deprecated' | 'retired';

export type PromotionType = 'promoted' | 'demoted' | 'migrated';

// ============================================================================
// KNOWLEDGE COLLECTION TYPES
// ============================================================================

export interface KnowledgeCollection {
  iri: string;
  label: string;
  description?: string;
  collection_type: CollectionType;
  scope_level: ScopeLevel;
  source_type: SourceType;
  source_url?: string;
  parent_collection_iri?: string;
  is_editable: boolean;
  status: string;
  
  // Audit fields
  created_at?: string;
  created_by?: string;
  updated_at?: string;
  updated_by?: string;
  
  // Computed fields
  concept_count: number;
  child_collections: KnowledgeCollection[];
}

export interface KnowledgeCollectionCreate {
  label: string;
  description?: string;
  collection_type?: CollectionType;
  scope_level?: ScopeLevel;
  parent_collection_iri?: string;
  is_editable?: boolean;
}

export interface KnowledgeCollectionUpdate {
  label?: string;
  description?: string;
  scope_level?: ScopeLevel;
  parent_collection_iri?: string;
  is_editable?: boolean;
}

// ============================================================================
// ONTOLOGY PROPERTY AND CONCEPT TYPES
// ============================================================================

export interface OntologyProperty {
  iri: string;
  label?: string;
  comment?: string;
  domain?: string;
  range?: string;
  property_type: 'datatype' | 'object' | 'annotation';
}

export interface OntologyConcept {
  iri: string;
  label?: string;  // Primary label (computed from labels dict)
  labels?: Record<string, string>;  // Multi-language labels: {"en": "Dataset", "ja": "データセット"}
  comment?: string;  // Primary comment (computed from comments dict)
  comments?: Record<string, string>;  // Multi-language comments: {"en": "A curated...", "ja": "..."}
  concept_type: 'class' | 'concept' | 'individual' | 'property' | 'term';
  source_context?: string;
  parent_concepts: string[];
  child_concepts: string[];
  related_concepts?: string[];
  properties: OntologyProperty[];
  tagged_assets: Array<{
    id: string;
    name: string;
    type?: string;
    path?: string;
  }>;
  synonyms: string[];
  examples: string[];
  
  // Property-specific fields (only set when concept_type === 'property')
  property_type?: 'datatype' | 'object' | 'annotation';
  domain?: string;
  range?: string;
  
  // Governance fields (for custom concepts)
  status?: ConceptStatus;
  version?: string;
  
  // Lifecycle timestamps
  created_at?: string;
  created_by?: string;
  updated_at?: string;
  updated_by?: string;
  published_at?: string;
  published_by?: string;
  certified_at?: string;
  certified_by?: string;
  certification_expires_at?: string;
  
  // Provenance (for promoted/migrated concepts)
  source_concept_iri?: string;
  source_collection_iri?: string;
  promotion_type?: PromotionType;
  
  // Review integration
  review_request_id?: string;
}

export interface ConceptCreate {
  collection_iri: string;
  label: string;
  definition?: string;
  concept_type?: 'class' | 'concept' | 'property' | 'individual' | 'term';
  // Property-specific fields
  property_type?: 'datatype' | 'object' | 'annotation';
  domain?: string;
  range?: string;
  synonyms?: string[];
  examples?: string[];
  broader_iris?: string[];
  narrower_iris?: string[];
  related_iris?: string[];
}

export interface ConceptUpdate {
  label?: string;
  definition?: string;
  concept_type?: 'class' | 'concept' | 'property' | 'individual' | 'term';
  // Property-specific fields
  property_type?: 'datatype' | 'object' | 'annotation';
  domain?: string;
  range?: string;
  synonyms?: string[];
  examples?: string[];
  broader_iris?: string[];
  narrower_iris?: string[];
  related_iris?: string[];
}

export interface SemanticModel {
  id: string;
  name: string;
  /** User-facing title; graph key remains `name` (filename / stable id). */
  display_name?: string | null;
  /** Legacy DB parse branch — not vocabulary. Prefer `serialization` for UI. */
  format?: 'rdfs' | 'skos' | string | null;
  /** RDF syntax label from API (Turtle, RDF/XML, …). */
  serialization?: string | null;
  original_filename?: string;
  content_type?: string;
  size_bytes?: number;
  enabled: boolean;
  created_by?: string;
  updated_by?: string;
  created_at?: string;
  updated_at?: string;
}

export interface ConceptHierarchy {
  concept: OntologyConcept;
  ancestors: OntologyConcept[];
  descendants: OntologyConcept[];
  siblings: OntologyConcept[];
}

export interface ConceptSearchResult {
  concept: OntologyConcept;
  relevance_score: number;
  match_type: 'label' | 'comment' | 'iri';
}

export interface TaxonomyStats {
  total_concepts: number;
  total_properties: number;
  taxonomies: SemanticModel[];
  concepts_by_type: Record<string, number>;
  top_level_concepts: number;
}

// Tree node structure for the UI
export interface ConceptTreeNode {
  concept: OntologyConcept;
  children: ConceptTreeNode[];
  isExpanded: boolean;
  level: number;
}

// Grouped concepts for tree view
export interface GroupedConcepts {
  [taxonomyName: string]: OntologyConcept[];
}