/**
 * Types for process workflows (visual workflow designer).
 * 
 * These workflows are different from Databricks job workflows - they are
 * internal process automation workflows for validation, approval, etc.
 */

// Enums
export type TriggerType = 
  | 'on_create'
  | 'on_update'
  | 'on_delete'
  | 'on_status_change'
  | 'scheduled'
  | 'manual'
  | 'before_create'   // Pre-creation validation (inline/blocking)
  | 'before_update'   // Pre-update validation (inline/blocking)
  | 'before_status_change'  // Pre-status-change validation (inline/blocking)
  // Request triggers
  | 'on_request_review'
  | 'on_request_access'
  | 'on_request_publish'
  | 'on_request_status_change'
  | 'on_request_certify'
  | 'on_certify'
  | 'on_decertify'
  // Job lifecycle triggers
  | 'on_job_success'
  | 'on_job_failure'
  // Subscription triggers
  | 'on_subscribe'
  | 'on_unsubscribe'
  // Publication triggers (separate from lifecycle status)
  | 'on_publish'
  | 'on_unpublish'
  // Access lifecycle triggers
  | 'on_expiring'
  | 'on_revoke'
  // User session triggers — fired by the frontend on app mount (e.g. terms-of-use disclaimers)
  | 'on_first_access'
  // App-known UI actions (approval workflows looked up by trigger type, 1:1 match with ON_*)
  | 'for_approval_response'
  | 'for_subscribe'
  | 'for_request_review'
  | 'for_request_access'
  | 'for_request_publish'
  | 'for_request_certify'
  | 'for_request_status_change';

/** Trigger literals for certification / publication lifecycle (use in configs and tests) */
export const ON_REQUEST_CERTIFY = 'on_request_certify' as const satisfies TriggerType;
export const FOR_REQUEST_CERTIFY = 'for_request_certify' as const satisfies TriggerType;
export const ON_CERTIFY = 'on_certify' as const satisfies TriggerType;
export const ON_DECERTIFY = 'on_decertify' as const satisfies TriggerType;

export type EntityType =
  | 'catalog'
  | 'schema'
  | 'table'
  | 'view'
  | 'data_contract'
  | 'data_product'
  | 'domain'
  | 'project'
  | 'access_grant'
  | 'role'
  | 'data_asset_review'
  | 'job'
  | 'subscription'
  | 'user';

export type ScopeType = 'all' | 'project' | 'catalog' | 'domain';

export type StepType =
  | 'validation'
  | 'approval'
  | 'notification'
  | 'assign_tag'
  | 'remove_tag'
  | 'conditional'
  | 'script'
  | 'pass'
  | 'fail'
  | 'policy_check'       // Evaluates existing compliance policy by UUID
  | 'delivery'           // Triggers DeliveryService to apply changes
  | 'create_asset_review' // Creates a DataAssetReview for formal review tracking
  | 'webhook'            // Calls external HTTP endpoints via UC Connections or direct URL
  | 'user_action'        // Approval workflow: collect user input (reason, acceptances, fields)
  | 'entity_action'      // Lifecycle action on trigger entity (certify, publish, etc.)
  | 'legal_document'             // Approval: display legal document for review
  | 'acknowledgement_checklist'  // Approval: checkbox list for explicit consents
  | 'co_signers'                 // Approval: collect co-signer principals
  | 'persist_agreement'          // Approval: materialize agreement record (non-visual)
  | 'generate_pdf'               // Approval: generate PDF artifact
  | 'deliver'                    // Approval: send agreement via channels (non-visual)
  | 'grant_permissions'          // Process: grant UC permissions via SP workspace client
  | 'on_behalf_of';              // Approval: capture self/group/SP principal in wizard ()

/** Canonical step type value for lifecycle actions on the trigger entity */
export const ENTITY_ACTION = 'entity_action' as const satisfies StepType;

export type ExecutionStatus =
  | 'pending'
  | 'running'
  | 'paused'
  | 'succeeded'
  | 'failed'
  | 'cancelled';

export type StepExecutionStatus =
  | 'pending'
  | 'running'
  | 'succeeded'
  | 'failed'
  | 'skipped';

// Trigger configuration
export interface WorkflowTrigger {
  type: TriggerType;
  entity_types: EntityType[];
  from_status?: string;
  to_status?: string;
  schedule?: string;
}

// Scope configuration
export interface WorkflowScope {
  type: ScopeType;
  ids: string[];
}

// Step position for visual designer
export interface StepPosition {
  x: number;
  y: number;
}

// Step configurations for different step types
export interface ValidationStepConfig {
  rule: string;
}

export interface ApprovalStepConfig {
  approvers: string;
  timeout_days?: number;
  require_all?: boolean;
}

export type NotificationChannel = 'in_app' | 'email' | 'webhook';

export interface NotificationStepConfig {
  recipients: string;
  template: string;
  custom_message?: string;
  channels?: NotificationChannel[];
}

export interface AssignTagStepConfig {
  key: string;
  value?: string;
  value_source?: string;
}

export interface RemoveTagStepConfig {
  key: string;
}

export interface ConditionalStepConfig {
  condition: string;
}

export interface ScriptStepConfig {
  language: 'python' | 'sql';
  code: string;
  timeout_seconds?: number;
}

export interface FailStepConfig {
  message?: string;
}

export interface PolicyCheckStepConfig {
  policy_id: string;
  policy_name?: string;  // Cached for display
}

export interface WebhookStepConfig {
  connection_name?: string;    // UC HTTP Connection name (if using UC mode)
  url?: string;                // Target URL (if using inline mode)
  method?: 'GET' | 'POST' | 'PUT' | 'PATCH' | 'DELETE';
  path?: string;               // Path appended to connection base URL (for UC mode)
  headers?: Record<string, string>;  // Custom headers
  body_template?: string;      // JSON body with ${variable} substitution
  timeout_seconds?: number;    // Request timeout (default: 30)
  success_codes?: number[];    // HTTP codes considered success (default: 200-299)
  retry_count?: number;        // Number of retries on failure (default: 0)
}

export type EntityActionKind = 'certify' | 'decertify' | 'publish' | 'unpublish';

export type EntityActionLevelSource = 'from_request' | 'fixed' | 'from_approval';

export type EntityActionScopeSource = 'from_request' | 'fixed' | 'from_approval';

export type EntityActionFixedScope = 'domain' | 'organization' | 'external';

export interface EntityActionStepConfig {
  action: EntityActionKind;
  /** Certification level source (certify only) */
  level_source?: EntityActionLevelSource;
  fixed_level?: number;
  /** Publication scope source (publish only) */
  scope_source?: EntityActionScopeSource;
  fixed_scope?: EntityActionFixedScope;
}

export interface LegalDocumentStepConfig {
  title?: string;
  description?: string;
  body_markdown?: string;
  require_scroll_to_end?: boolean;
  require_acknowledgement_checkbox?: boolean;
  acknowledgement_label?: string;
}

export interface AcknowledgementChecklistStepConfig {
  title?: string;
  description?: string;
  items?: Array<{ id: string; label: string; required?: boolean }>;
}

export interface CoSignersStepConfig {
  title?: string;
  description?: string;
  min_count?: number;
  max_count?: number;
  principal_type?: 'user' | 'group' | 'either';
  label?: string;
}

export interface PersistAgreementStepConfig {
  // No user-configurable fields
}

export interface GeneratePdfStepConfig {
  storage?: 'volume' | 'none';
  volume_path?: string;
}

export interface DeliverStepConfig {
  channels?: Array<'in_app' | 'email' | 'webhook'>;
  recipients?: string[];
  subject_template?: string;
  body_template?: string;
}

export interface GrantPermissionsStepConfig {
  permission_type?: 'SELECT' | 'USE_SCHEMA' | 'USE_CATALOG' | 'ALL_PRIVILEGES';
  target_source?: 'from_entity' | 'from_variable';
  target_variable?: string;
  principal_source?: 'requester' | 'from_variable';
  principal_variable?: string;
}

// Reference to a UC HTTP Connection (for UI selection)
export interface HttpConnectionRef {
  name: string;
  connection_type: string;
  comment?: string;
  owner?: string;
}

// Reference to a compliance policy (for UI selection)
export interface CompliancePolicyRef {
  id: string;
  name: string;
  slug?: string;
  description?: string;
  category?: string;
  severity?: string;
}

export type StepConfig = 
  | ValidationStepConfig
  | ApprovalStepConfig
  | NotificationStepConfig
  | AssignTagStepConfig
  | RemoveTagStepConfig
  | ConditionalStepConfig
  | ScriptStepConfig
  | FailStepConfig
  | PolicyCheckStepConfig
  | WebhookStepConfig
  | EntityActionStepConfig
  | LegalDocumentStepConfig
  | AcknowledgementChecklistStepConfig
  | CoSignersStepConfig
  | PersistAgreementStepConfig
  | GeneratePdfStepConfig
  | DeliverStepConfig
  | GrantPermissionsStepConfig
  | Record<string, unknown>;

// Workflow step
export interface WorkflowStep {
  id: string;
  workflow_id: string;
  step_id: string;
  name?: string;
  step_type: StepType;
  config: StepConfig;
  on_pass?: string;
  on_fail?: string;
  order: number;
  position?: StepPosition;
  created_at?: string;
  updated_at?: string;
}

export interface WorkflowStepCreate {
  step_id: string;
  name?: string;
  step_type: StepType;
  config: StepConfig;
  on_pass?: string;
  on_fail?: string;
  order: number;
  position?: StepPosition;
}

// Process workflow
export type WorkflowTypeValue = 'process' | 'approval';

export interface ProcessWorkflow {
  id: string;
  name: string;
  description?: string;
  trigger: WorkflowTrigger;
  scope?: WorkflowScope;
  workflow_type?: WorkflowTypeValue;
  is_active: boolean;
  is_default: boolean;
  version: number;
  steps: WorkflowStep[];
  created_at?: string;
  updated_at?: string;
  created_by?: string;
  updated_by?: string;
}

export interface ProcessWorkflowCreate {
  name: string;
  description?: string;
  trigger: WorkflowTrigger;
  scope?: WorkflowScope;
  workflow_type?: WorkflowTypeValue;
  is_active?: boolean;
  steps: WorkflowStepCreate[];
}

export interface ProcessWorkflowUpdate {
  name?: string;
  description?: string;
  trigger?: WorkflowTrigger;
  scope?: WorkflowScope;
  workflow_type?: WorkflowTypeValue;
  is_active?: boolean;
  steps?: WorkflowStepCreate[];
}

// Trigger context
export interface TriggerContext {
  entity_type: string;
  entity_id: string;
  entity_name?: string;
  trigger_type: TriggerType;
  user_email?: string;
  entity_data?: Record<string, unknown>;
  from_status?: string;
  to_status?: string;
}

// Step execution result
export interface WorkflowStepExecutionResult {
  id: string;
  step_id: string;
  status: StepExecutionStatus;
  passed?: boolean;
  result_data?: Record<string, unknown>;
  error_message?: string;
  duration_ms?: number;
  started_at?: string;
  finished_at?: string;
}

// Workflow execution
export interface WorkflowExecution {
  id: string;
  workflow_id: string;
  trigger_context?: TriggerContext;
  status: ExecutionStatus;
  current_step_id?: string;
  current_step_name?: string;
  success_count: number;
  failure_count: number;
  error_message?: string;
  started_at?: string;
  finished_at?: string;
  triggered_by?: string;
  step_executions: WorkflowStepExecutionResult[];
  workflow_name?: string;
  entity_type?: string;
  entity_id?: string;
  entity_name?: string;
}

// Step type schema (for dynamic form generation)
export interface StepTypeSchema {
  type: StepType;
  name: string;
  description: string;
  icon: string;
  config_schema: Record<string, unknown>;
  has_pass_branch: boolean;
  has_fail_branch: boolean;
}

// Validation result
export interface WorkflowValidationResult {
  valid: boolean;
  errors: string[];
  warnings: string[];
}

// API responses
export interface WorkflowListResponse {
  workflows: ProcessWorkflow[];
  total: number;
}

export interface WorkflowExecutionListResponse {
  executions: WorkflowExecution[];
  total: number;
}

// React Flow node data types
export interface WorkflowNodeData {
  step: WorkflowStep;
  isSelected?: boolean;
  onSelect?: (stepId: string) => void;
  onDelete?: (stepId: string) => void;
}

export interface TriggerNodeData {
  trigger: WorkflowTrigger;
  isSelected?: boolean;
  onSelect?: () => void;
}

