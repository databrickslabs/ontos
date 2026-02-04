import { AssignedTag } from '@/components/ui/tag-chip';

/**
 * ODPS v1.0.0 (Open Data Product Standard) TypeScript Types
 *
 * Based on: https://github.com/bitol-io/open-data-product-standard/blob/main/schema/odps-json-schema-v1.0.0.json
 */

// ============================================================================
// ODPS v1.0.0 Enums
// ============================================================================

export enum DataProductStatus {
  DRAFT = 'draft',
  SANDBOX = 'sandbox',
  PROPOSED = 'proposed',
  UNDER_REVIEW = 'under_review',
  APPROVED = 'approved',
  ACTIVE = 'active',
  CERTIFIED = 'certified',
  DEPRECATED = 'deprecated',
  RETIRED = 'retired'
}

// ============================================================================
// ODPS v1.0.0 Shared Models
// ============================================================================

export interface AuthoritativeDefinition {
  type: string; // businessDefinition, transformationImplementation, videoTutorial, tutorial, implementation
  url: string;
  description?: string;
}

export interface CustomProperty {
  property: string; // camelCase name
  value: any; // Can be any type
  description?: string;
}

export interface Description {
  purpose?: string;
  limitations?: string;
  usage?: string;
  authoritativeDefinitions?: AuthoritativeDefinition[];
  customProperties?: CustomProperty[];
}

// ============================================================================
// ODPS v1.0.0 Port Models
// ============================================================================

// Databricks extension - Connection details for output ports
export interface Server {
  project?: string;
  dataset?: string;
  account?: string;
  database?: string;
  schema?: string; // Use 'schema' to match API (not schema_name)
  host?: string;
  topic?: string;
  location?: string;
  delimiter?: string;
  format?: string;
  table?: string;
  view?: string;
  share?: string;
  additionalProperties?: string;
}

export interface InputPort {
  // UI fields
  id?: string; // For form tracking
  links?: Record<string, string>; // Port-level links
  custom?: Record<string, any>; // Port-level custom properties

  // ODPS required fields
  name: string;
  version: string;
  contractId: string; // REQUIRED in ODPS!

  // ODPS optional fields
  tags?: string[];
  customProperties?: CustomProperty[];
  authoritativeDefinitions?: AuthoritativeDefinition[];

  // Databricks extensions
  assetType?: string; // table, notebook, job
  assetIdentifier?: string; // catalog.schema.table, /path/to/notebook, job_id
  sourceSystemId?: string;
  type?: string;
  description?: string;
}

export interface SBOM {
  type: string; // Default: "external"
  url: string;
}

export interface InputContract {
  id: string; // Contract ID
  version: string; // Contract version
}

export interface OutputPort {
  // UI fields
  id?: string; // For form tracking
  links?: Record<string, string>; // Port-level links
  custom?: Record<string, any>; // Port-level custom properties

  // ODPS required fields
  name: string;
  version: string;

  // ODPS optional fields
  description?: string;
  type?: string; // Type of output port
  contractId?: string; // Optional link to contract
  contractName?: string; // Resolved contract name
  sbom?: SBOM[];
  inputContracts?: InputContract[];
  tags?: string[];
  customProperties?: CustomProperty[];
  authoritativeDefinitions?: AuthoritativeDefinition[];

  // Databricks extensions
  assetType?: string;
  assetIdentifier?: string;
  status?: string;
  server?: Server;
  containsPii?: boolean;
  autoApprove?: boolean;
}

// ============================================================================
// ODPS v1.0.0 Management Port (NEW)
// ============================================================================

export interface ManagementPort {
  // ODPS required fields
  name: string; // Endpoint identifier or unique name
  content: string; // discoverability, observability, control, dictionary

  // ODPS optional fields
  type?: string; // rest or topic (default: "rest")
  url?: string;
  channel?: string;
  description?: string;
  tags?: string[];
  customProperties?: CustomProperty[];
  authoritativeDefinitions?: AuthoritativeDefinition[];
}

// ============================================================================
// ODPS v1.0.0 Support Channel
// ============================================================================

export interface Support {
  // ODPS required fields
  channel: string;
  url: string;

  // ODPS optional fields
  description?: string;
  tool?: string; // email, slack, teams, discord, ticket, other
  scope?: string; // interactive, announcements, issues
  invitationUrl?: string;
  tags?: string[];
  customProperties?: CustomProperty[];
  authoritativeDefinitions?: AuthoritativeDefinition[];
}

// ============================================================================
// ODPS v1.0.0 Team
// ============================================================================

export interface TeamMember {
  // ODPS required fields
  username: string; // User's username or email

  // ODPS optional fields
  name?: string;
  description?: string;
  role?: string; // owner, data steward, contributor, etc.
  dateIn?: string; // ISO date string
  dateOut?: string; // ISO date string
  replacedByUsername?: string;
  tags?: string[];
  customProperties?: CustomProperty[];
  authoritativeDefinitions?: AuthoritativeDefinition[];
}

export interface Team {
  name?: string;
  description?: string;
  members?: TeamMember[];
  tags?: string[];
  customProperties?: CustomProperty[];
  authoritativeDefinitions?: AuthoritativeDefinition[];
}

// ============================================================================
// ODPS v1.0.0 Link Type
// ============================================================================

export interface Link {
  url: string;
  description?: string;
}

// ============================================================================
// ODPS v1.0.0 Info Type
// ============================================================================

export interface Info {
  title?: string;
  owner?: string;
  domain?: string;
  archetype?: string;
  description?: string;
  status?: string;
}

// ============================================================================
// ODPS v1.0.0 Data Product (Main Model)
// ============================================================================

export interface DataProduct {
  // ODPS v1.0.0 required fields
  apiVersion: string; // "v1.0.0"
  
  // Extensions
  owner_team_id?: string // UUID of the owning team
  owner_team_name?: string // Display name of the owning team
  kind: string; // "DataProduct"
  id: string;
  status: string; // proposed, draft, active, deprecated, retired

  // ODPS v1.0.0 optional fields
  name?: string;
  version?: string;
  domain?: string;
  tenant?: string;
  authoritativeDefinitions?: AuthoritativeDefinition[];
  description?: Description;
  customProperties?: CustomProperty[];
  tags?: (string | AssignedTag)[]; // Support both formats for flexibility
  inputPorts?: InputPort[];
  outputPorts?: OutputPort[];
  managementPorts?: ManagementPort[];
  support?: Support[];
  team?: Team;
  productCreatedTs?: string; // ISO timestamp

  // Audit fields (not in ODPS, but useful)
  created_at?: string;
  updated_at?: string;

  // Databricks extension
  project_id?: string;
  project_name?: string; // Resolved project name

  // Versioning fields
  draftOwnerId?: string; // Personal draft owner - if set, visible only to owner
  parentProductId?: string; // Parent version ID for version lineage
  baseName?: string; // Base name without version for grouping versions
  changeSummary?: string; // Summary of changes in this version
  published?: boolean; // Whether published to marketplace

  // UI form fields (for form handling)
  dataProductSpecification?: string; // Spec version
  productType?: string; // Product type
  info?: Info; // Basic info object
  links?: Record<string, Link>; // Named links
  custom?: Record<string, any>; // Custom key-value pairs
}

// ============================================================================
// Request/Response Models
// ============================================================================

export interface CommitDraftRequest {
  new_version: string;
  change_summary: string;
}

export interface CommitDraftResponse {
  id: string;
  name?: string;
  version?: string;
  status: string;
  draftOwnerId?: string;
}

export interface DiffFromParentResponse {
  parent_version: string;
  suggested_bump: string;
  suggested_version: string;
  analysis: Record<string, any>;
}

export interface ChangeStatusPayload {
  new_status: string;
}

export interface RequestStatusChangePayload {
  target_status: string;
  justification: string;
  current_status?: string;
}

export interface HandleStatusChangePayload {
  decision: string;
  target_status: string;
  requester_email: string;
  message?: string;
}

export interface GenieSpaceRequest {
  product_ids: string[];
}

export interface NewVersionRequest {
  new_version: string;
}

// ============================================================================
// Legacy type aliases for backward compatibility (can be removed later)
// ============================================================================

export type DataProductArchetype = string;
export type DataProductOwner = string;
export type DataProductType = string;

// ============================================================================
// Helper Types
// ============================================================================

// Type for metastore table info from the backend
export interface MetastoreTableInfo {
  catalog_name: string;
  schema_name: string;
  table_name: string;
  full_name: string;
}

// Form data types for creating/updating products
export interface DataProductFormData extends Partial<DataProduct> {
  // Additional form-specific fields if needed
}

// ============================================================================
// Subscription Types
// ============================================================================

export interface Subscription {
  id: string;
  product_id: string;
  subscriber_email: string;
  subscribed_at: string;  // ISO date string
  subscription_reason?: string;
}

export interface SubscriptionCreate {
  reason?: string;
}

export interface SubscriptionResponse {
  subscribed: boolean;
  subscription?: Subscription;
}

export interface SubscriberInfo {
  email: string;
  subscribed_at: string;  // ISO date string
  reason?: string;
}

export interface SubscribersListResponse {
  product_id: string;
  subscriber_count: number;
  subscribers: SubscriberInfo[];
}

export interface SubscriberCountResponse {
  product_id: string;
  subscriber_count: number;
}
