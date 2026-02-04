// Simplified type for list view
export type DataContractListItem = {
  id: string
  name: string
  version: string
  status: string
  published?: boolean // Marketplace publication status
  owner_team_id?: string // UUID of the owning team
  owner_team_name?: string // Resolved owner team name
  project_id?: string // Project association
  project_name?: string // Resolved project name
  tags?: any[] // Tags assigned to the contract
  created?: string
  updated?: string
  // Semantic versioning fields
  parentContractId?: string
  baseName?: string
  // Personal draft visibility
  draftOwnerId?: string // If set, this is a personal draft
}

// ODCS compliant column property
export type ColumnProperty = {
  name: string
  logicalType: string
  physicalType?: string // Physical data type (VARCHAR(50), INT, etc.)
  physicalName?: string // Physical column name
  required?: boolean
  unique?: boolean
  primaryKey?: boolean // Primary key flag
  primaryKeyPosition?: number // PK position for composite keys (-1 if not part of PK)
  partitioned?: boolean // Partition column flag
  partitionKeyPosition?: number // Partition position (-1 if not partitioned)
  classification?: string // Data classification (confidential/restricted/public/PII/1-5)
  examples?: string // Sample values (comma-separated or JSON string)
  description?: string
  // ODCS-compatible logical type options and semantics
  logicalTypeOptions?: Record<string, any>
  authoritativeDefinitions?: { url: string; type: string }[]
  // Optional local helper used by wizard/editor to collect concepts
  semanticConcepts?: { iri: string; label?: string }[]
  // String constraints
  minLength?: number
  maxLength?: number
  pattern?: string
  // Number/Integer constraints
  minimum?: number
  maximum?: number
  multipleOf?: number
  precision?: number
  // Date constraints
  format?: string
  timezone?: string
  customFormat?: string
  // Array constraints
  itemType?: string
  minItems?: number
  maxItems?: number
  // ODCS v3.0.2 additional property fields
  businessName?: string
  encryptedName?: string
  criticalDataElement?: boolean
  transformLogic?: string
  transformSourceObjects?: string
  transformDescription?: string
  // ODCS quality checks, tags, and custom properties
  quality?: QualityRule[]  // Property-level quality checks
  tags?: string[]  // ODCS tags for categorization
  customProperties?: Record<string, any>  // ODCS custom properties
}

// ODCS compliant schema object
export type SchemaObject = {
  name: string
  physicalName?: string
  properties: ColumnProperty[]
  // Extended UC metadata
  description?: string
  tableType?: string
  owner?: string
  createdAt?: string
  updatedAt?: string
  tableProperties?: Record<string, any>
  // ODCS v3.0.2 fields
  businessName?: string
  physicalType?: string
  dataGranularityDescription?: string
  // Semantics
  authoritativeDefinitions?: { url: string; type: string }[]
  // Optional local helper used by wizard/editor to collect concepts
  semanticConcepts?: { iri: string; label?: string }[]
}

// ODCS compliant description
export type ContractDescription = {
  usage?: string
  purpose?: string
  limitations?: string
}

// ODCS v3.0.2 compliant team member
export type TeamMember = {
  username: string // Required by ODCS - maps to email/identifier
  role: string
  name?: string
  description?: string
  dateIn?: string // ISO date format
  dateOut?: string // ISO date format
  replacedByUsername?: string
  email?: string // Legacy/convenience field (aliased to username)
}

// ODCS compliant access control
export type AccessControl = {
  readGroups?: string[]
  writeGroups?: string[]
  adminGroups?: string[]
  classification?: string
  containsPii?: boolean
  requiresEncryption?: boolean
}

// ODCS compliant support channels
export type SupportChannels = {
  email?: string
  slack?: string
  documentation?: string
  [key: string]: string | undefined
}

// ODCS compliant SLA requirements
export type SLARequirements = {
  uptimeTarget?: number
  maxDowntimeMinutes?: number
  queryResponseTimeMs?: number
  dataFreshnessMinutes?: number
}

// ODCS v3.0.2 compliant quality rule (matches backend QualityRule model)
export type QualityRule = {
  name?: string
  description?: string
  level?: string // 'contract', 'object', 'property'
  dimension?: string // 'accuracy', 'completeness', 'conformity', 'consistency', 'coverage', 'timeliness', 'uniqueness'
  businessImpact?: string // 'operational', 'regulatory'
  severity?: string // 'info', 'warning', 'error'
  type?: string // 'text', 'library', 'sql', 'custom'
  method?: string
  schedule?: string
  scheduler?: string
  unit?: string
  tags?: string
  rule?: string
  query?: string
  engine?: string
  implementation?: string
  mustBe?: string
  mustNotBe?: string
  mustBeGt?: number
  mustBeGe?: number
  mustBeLt?: number
  mustBeLe?: number
  mustBeBetweenMin?: number
  mustBeBetweenMax?: number
}

// Server configuration (ODCS compliant)
export type ServerConfig = {
  server?: string
  type?: string
  description?: string
  environment?: string
  host?: string
  port?: number
  database?: string
  schema?: string
  catalog?: string
  project?: string
  account?: string
  region?: string
  location?: string
  properties?: Record<string, string>
}

// Full ODCS v3.0.2 compliant data contract
export interface DataContract {
  id: string
  kind: string
  apiVersion: string
  version: string
  status: string
  published?: boolean // Marketplace publication status
  name: string
  tenant?: string
  domain?: string // Legacy field (domain name)
  domainId?: string // Domain ID for backend API
  dataProduct?: string
  owner_team_id?: string // UUID of the owning team
  owner_team_name?: string // Display name of the owning team
  project_id?: string // Project association
  project_name?: string // Resolved project name
  description?: ContractDescription
  tags?: any[] // Tags assigned to the contract
  schema?: SchemaObject[]
  qualityRules?: QualityRule[]
  team?: TeamMember[]
  accessControl?: AccessControl
  support?: SupportChannels
  sla?: SLARequirements
  servers?: ServerConfig | ServerConfig[]
  customProperties?: Record<string, any>
  created?: string
  updated?: string
  // Semantic versioning fields
  parentContractId?: string // Parent version reference
  baseName?: string // Base name without version suffix
  changeSummary?: string // Summary of changes in this version
  // Personal draft visibility (three-tier model)
  // Tier 1: draftOwnerId set = personal draft, only owner can see
  // Tier 2: draftOwnerId null, published=false = team/project visible
  // Tier 3: published=true = marketplace visible to all
  draftOwnerId?: string
}

// Response from diff-from-parent endpoint
export interface DiffFromParentResponse {
  parent_version: string
  parent_status: string
  suggested_bump: 'major' | 'minor' | 'patch'
  suggested_version: string
  analysis: {
    change_type: string
    version_bump: string
    summary: string
    breaking_changes: string[]
    new_features: string[]
    fixes: string[]
    schema_changes?: Array<{
      change_type: string
      schema_name: string
      field_name?: string
      old_value?: string
      new_value?: string
      severity: string
    }>
  }
}

// Request to commit a personal draft
export interface CommitDraftRequest {
  new_version: string
  change_summary: string
}

// DQX Profiling types
export type DataProfilingRun = {
  id: string
  contract_id: string
  source: 'dqx' | 'llm' | 'manual'
  schema_names: string[]
  status: 'pending' | 'running' | 'completed' | 'failed'
  summary_stats?: string
  run_id?: string
  started_at: string
  completed_at?: string
  error_message?: string
  triggered_by?: string
  suggestion_counts?: {
    pending: number
    accepted: number
    rejected: number
  }
}

export type SuggestedQualityCheck = {
  id: string
  profile_run_id: string
  contract_id: string
  source: 'dqx' | 'llm' | 'manual'
  schema_name: string
  property_name?: string
  status: 'pending' | 'accepted' | 'rejected'
  confidence_score?: number
  rationale?: string
  // Quality rule fields
  name?: string
  description?: string
  level?: string
  dimension?: string
  business_impact?: string
  severity?: string
  type: string
  method?: string
  schedule?: string
  scheduler?: string
  unit?: string
  tags?: string
  rule?: string
  query?: string
  engine?: string
  implementation?: string
  must_be?: string
  must_not_be?: string
  must_be_gt?: string
  must_be_ge?: string
  must_be_lt?: string
  must_be_le?: string
  must_be_between_min?: string
  must_be_between_max?: string
  created_at?: string
}

// For local draft storage (UI state)
export type DataContractDraft = {
  name: string
  version: string
  status: string
  owner: string
  kind: string
  apiVersion: string
  contract_text: string
  format: 'json' | 'yaml' | 'text'
}

// For creating new contracts
export type DataContractCreate = {
  name: string
  version?: string
  status?: string
  owner_team_id?: string // UUID of the owning team
  project_id?: string // Project association
  kind?: string
  apiVersion?: string
  domain?: string
  domainId?: string
  tenant?: string
  dataProduct?: string
  description?: ContractDescription
  tags?: any[] // Tags to assign to the contract
  schema?: SchemaObject[]
  qualityRules?: QualityRule[]
  team?: TeamMember[]
  accessControl?: AccessControl
  support?: SupportChannels
  sla?: SLARequirements
  servers?: ServerConfig | ServerConfig[]
  customProperties?: Record<string, any>
}

// Team member for import (from app teams to ODCS team array)
export type TeamMemberForImport = {
  member_identifier: string
  member_name: string
  member_type: 'user' | 'group'
  suggested_role: string
} 