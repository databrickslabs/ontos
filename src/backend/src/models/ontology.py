from typing import Dict, List, Optional, Any
from pydantic import BaseModel, Field
from datetime import datetime
from enum import Enum


# ============================================================================
# ENUMS FOR KNOWLEDGE COLLECTIONS
# ============================================================================

class CollectionType(str, Enum):
    GLOSSARY = "glossary"
    TAXONOMY = "taxonomy"
    ONTOLOGY = "ontology"


class ScopeLevel(str, Enum):
    ENTERPRISE = "enterprise"
    DOMAIN = "domain"
    DEPARTMENT = "department"
    TEAM = "team"
    PROJECT = "project"
    EXTERNAL = "external"


class SourceType(str, Enum):
    CUSTOM = "custom"
    IMPORTED = "imported"


class ConceptStatus(str, Enum):
    """Ontology concept status. Aligned with EntityStatus; CERTIFIED removed (separate dimension)."""
    DRAFT = "draft"
    UNDER_REVIEW = "under_review"
    APPROVED = "approved"
    ACTIVE = "active"
    DEPRECATED = "deprecated"
    RETIRED = "retired"


class PromotionType(str, Enum):
    PROMOTED = "promoted"
    DEMOTED = "demoted"
    MIGRATED = "migrated"


# ============================================================================
# KNOWLEDGE COLLECTION MODELS
# ============================================================================

class KnowledgeCollection(BaseModel):
    """A glossary, taxonomy, or ontology containing concepts"""
    iri: str
    label: str
    description: Optional[str] = None
    collection_type: CollectionType = CollectionType.GLOSSARY
    scope_level: ScopeLevel = ScopeLevel.ENTERPRISE
    source_type: SourceType = SourceType.CUSTOM
    source_url: Optional[str] = None
    parent_collection_iri: Optional[str] = None
    is_editable: bool = True
    status: str = "active"
    
    # Audit fields
    created_at: Optional[datetime] = None
    created_by: Optional[str] = None
    updated_at: Optional[datetime] = None
    updated_by: Optional[str] = None
    
    # Computed fields
    concept_count: int = 0
    child_collections: List["KnowledgeCollection"] = []


class KnowledgeCollectionCreate(BaseModel):
    """Create request for a knowledge collection"""
    label: str
    description: Optional[str] = None
    collection_type: CollectionType = CollectionType.GLOSSARY
    scope_level: ScopeLevel = ScopeLevel.ENTERPRISE
    parent_collection_iri: Optional[str] = None
    is_editable: bool = True


class KnowledgeCollectionUpdate(BaseModel):
    """Update request for a knowledge collection"""
    label: Optional[str] = None
    description: Optional[str] = None
    scope_level: Optional[ScopeLevel] = None
    parent_collection_iri: Optional[str] = None
    is_editable: Optional[bool] = None


# ============================================================================
# ONTOLOGY PROPERTY AND CONCEPT MODELS
# ============================================================================

class OntologyProperty(BaseModel):
    iri: str
    label: Optional[str] = None
    comment: Optional[str] = None
    domain: Optional[str] = None
    range: Optional[str] = None
    property_type: str  # 'datatype' | 'object' | 'annotation'


class OntologyConcept(BaseModel):
    iri: str
    label: Optional[str] = None  # Primary label (computed from labels dict)
    labels: Dict[str, str] = {}  # Multi-language labels: {"en": "Dataset", "ja": "データセット"}
    comment: Optional[str] = None  # Primary comment (computed from comments dict)
    comments: Dict[str, str] = {}  # Multi-language comments: {"en": "A curated...", "ja": "..."}
    concept_type: str  # 'class' | 'concept' | 'property' | 'individual' | 'term'
    property_type: Optional[str] = None  # For properties: 'datatype' | 'object' | 'annotation'
    source_context: Optional[str] = None  # The taxonomy/ontology source (collection IRI)
    parent_concepts: List[str] = []  # Parent class/concept IRIs
    child_concepts: List[str] = []   # Child class/concept IRIs
    related_concepts: List[str] = [] # skos:related IRIs
    domain: Optional[str] = None     # For properties: rdfs:domain
    range: Optional[str] = None      # For properties: rdfs:range
    properties: List[OntologyProperty] = []
    tagged_assets: List[Dict[str, Any]] = []  # Linked data assets
    synonyms: List[str] = []
    examples: List[str] = []
    
    # Governance fields (for custom concepts)
    status: Optional[ConceptStatus] = None
    version: Optional[str] = None
    
    # Lifecycle timestamps
    created_at: Optional[datetime] = None
    created_by: Optional[str] = None
    updated_at: Optional[datetime] = None
    updated_by: Optional[str] = None
    published_at: Optional[datetime] = None
    published_by: Optional[str] = None
    certified_at: Optional[datetime] = None
    certified_by: Optional[str] = None
    certification_expires_at: Optional[datetime] = None
    
    # Provenance (for promoted/migrated concepts)
    source_concept_iri: Optional[str] = None
    source_collection_iri: Optional[str] = None
    promotion_type: Optional[PromotionType] = None
    
    # Review integration
    review_request_id: Optional[str] = None


class ConceptCreate(BaseModel):
    """Create request for a concept"""
    collection_iri: str
    label: str
    definition: Optional[str] = None
    concept_type: str = "concept"  # 'class' | 'concept' | 'property' | 'individual' | 'term'
    # Property-specific fields (used when concept_type == 'property')
    property_type: Optional[str] = None  # 'datatype' | 'object' | 'annotation'
    domain: Optional[str] = None  # rdfs:domain (IRI)
    range: Optional[str] = None   # rdfs:range  (IRI or xsd datatype)
    synonyms: List[str] = []
    examples: List[str] = []
    broader_iris: List[str] = []  # skos:broader
    narrower_iris: List[str] = []  # skos:narrower
    related_iris: List[str] = []  # skos:related


class ConceptUpdate(BaseModel):
    """Update request for a concept"""
    label: Optional[str] = None
    definition: Optional[str] = None
    # Type-change fields. Mutating concept_type after creation is allowed only
    # while the concept is still draft and is handled by SemanticModelsManager.
    concept_type: Optional[str] = None
    property_type: Optional[str] = None
    domain: Optional[str] = None
    range: Optional[str] = None
    synonyms: Optional[List[str]] = None
    examples: Optional[List[str]] = None
    broader_iris: Optional[List[str]] = None
    narrower_iris: Optional[List[str]] = None
    related_iris: Optional[List[str]] = None
    
    
class SemanticModel(BaseModel):
    """Represents a loaded semantic model (taxonomy/ontology source)"""
    name: str
    display_name: Optional[str] = None
    description: Optional[str] = None
    source_type: str  # 'file' | 'database' | 'external' | 'schema'
    format: Optional[str] = None  # 'ttl' | 'rdf' | 'owl'
    concepts_count: int = 0
    properties_count: int = 0
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None


class ConceptHierarchy(BaseModel):
    """Represents hierarchical relationships for visualization"""
    concept: OntologyConcept
    ancestors: List[OntologyConcept] = []
    descendants: List[OntologyConcept] = []
    siblings: List[OntologyConcept] = []


class ConceptSearchResult(BaseModel):
    concept: OntologyConcept
    relevance_score: float = 0.0
    match_type: str = "label"  # 'label' | 'comment' | 'iri'


class TaxonomyStats(BaseModel):
    total_concepts: int
    total_properties: int
    taxonomies: List[SemanticModel]
    concepts_by_type: Dict[str, int] = {}
    top_level_concepts: int = 0