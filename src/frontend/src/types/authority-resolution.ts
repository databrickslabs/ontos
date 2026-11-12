export interface AssignedDomain {
  domain_id: string;
  domain_name: string;
  is_primary: boolean;
  assigned_by?: string | null;
  assigned_at?: string | null;
}

export interface AuthorityAffirmation {
  id: string;
  role: string;                     // Business Role name (cached label)
  business_role_id?: string | null; // Settings Business Role id
  role_category?: string | null;    // governance|technical|business|operational
  principal: string;
  principal_type: string;
  required: boolean;
  affirmed: boolean;
  affirmed_by?: string | null;
  affirmed_at?: string | null;
  sort_order: number;
  // A participant can be an approver (affirmation gate), a reviewer
  // (interviewee in the review process), or both.
  is_approver?: boolean;
  is_reviewer?: boolean;
  review_status?: string;           // na | pending | in_review | completed
  review_request_id?: string | null;
}

export interface ReviewQuestion {
  id: string;
  text: string;
}

export interface AuthorityReviewContext {
  participant_id: string;
  role: string;
  review_status: string;            // na | pending | in_review | completed
  questionnaire: ReviewQuestion[];
  existing_answers?: Record<string, string> | null;
  ar_name: string;
  // Present for technical/governance reviewers who inspect the rule + evidence.
  details?: {
    actor_identity?: string | null;
    action?: string | null;
    domain_context?: DomainContext | null;
    rule?: ArfRule | null;
    criteria?: { name?: string | null; rule?: string | null; direction?: string; weight?: number; enabled?: boolean }[];
    evidence_binding?: EvidenceBinding | null;
    evidence_sources?: EvidenceSource[] | null;
    justification_chain?: Record<string, any> | null;
  } | null;
}

export interface EvidenceBinding {
  source_table_fqn: string;
  column_map: Record<string, string>;
  row_filter?: string | null;
}

export type EvidenceSourceType = 'delta_table' | 'data_product' | 'asset';

export interface EvidenceSource {
  type: EvidenceSourceType;
  ref: string;
  label?: string | null;
  column_map?: Record<string, string>;
  row_filter?: string | null;
}

export interface AuthorityCriterion {
  id: string;
  policy_id?: string | null;
  name?: string | null;
  rule?: string | null;              // Compliance-DSL ASSERT rule (the condition)
  failure_message?: string | null;
  category?: string | null;
  direction: string;                 // actual-exceeds-documented | documented-exceeds-actual | neutral
  weight: number;
  dimension?: string;                // DNAco dimension (people|policy|…)
  order: number;
  enabled: boolean;
  policy_clause_ref?: string | null; // the Authority Policy clause this check enforces
}

export interface CriterionInput {
  policy_id?: string;                // link an existing Compliance Check
  name?: string;                     // inline-authored check name
  rule?: string;                     // inline-authored ASSERT rule
  failure_message?: string;
  direction: string;
  weight: number;
  dimension?: string;
  order: number;
  enabled: boolean;
  policy_clause_ref?: string;
}

export interface ReusableCheck {
  id: string;
  name: string;
  rule: string;
  category?: string | null;
  failure_message?: string | null;
  severity?: string | null;
}

export const ARF_DIRECTIONS: { value: string; label: string }[] = [
  { value: 'actual-exceeds-documented', label: 'Actual exceeds documented' },
  { value: 'documented-exceeds-actual', label: 'Documented exceeds actual' },
  { value: 'neutral', label: 'Neutral' },
];

// ODRL-shaped constraint (src/backend/src/common/authority_rule.py). The scope
// compares with values; rule constraints may also reference a variable
// (`ctx.<param>` / `req.<key>`).
export type OdrlOperator = 'eq' | 'neq' | 'lt' | 'lteq' | 'gt' | 'gteq' | 'isAnyOf' | 'isNoneOf';

export interface DivergenceFacets {
  name?: string;
  message?: string;
  direction?: string;
  weight?: number;
  dimension?: string;
  clause?: string;                   // the Authority Policy clause the item implements
}

export interface OdrlConstraint extends DivergenceFacets {
  leftOperand: string;
  operator: OdrlOperator;
  rightOperand?: string | number | boolean | (string | number | boolean)[];
  rightOperandReference?: string;
  unit?: string;
}

// A logical constraint: holds when any (or) / all (and) of its parts hold.
export interface OdrlLogicalConstraint extends DivergenceFacets {
  or?: OdrlConstraint[];
  and?: OdrlConstraint[];
}

export type RuleConstraint = OdrlConstraint | OdrlLogicalConstraint;

export interface OdrlDuty extends DivergenceFacets {
  action: string;                    // e.g. arf:obtainCoApproval
  constraint: RuleConstraint[];      // the duty is fulfilled when these hold
}

export interface OdrlProhibition extends DivergenceFacets {
  constraint: RuleConstraint[];      // prohibited when all of these hold
}

export interface ArfRule {
  permission?: { constraint?: RuleConstraint[]; duty?: OdrlDuty[] };
  prohibition?: OdrlProhibition[];
}

export interface DomainContext {
  scope: OdrlConstraint[];           // must match the request context
  params: Record<string, any>;       // read by rules as ctx.<key>
}

export interface AuthorityRelation {
  id: string;
  slug?: string | null;
  family_slug?: string | null;   // slug for the whole version family (visible on every version)
  name: string;
  description?: string | null;
  status: string;                 // draft | active | needs_review | retired
  maturity_level_order?: number | null;   // cached achieved level (shared Maturity feature)
  maturity_evaluated_at?: string | null;
  version: string;                // semantic version string (e.g. 1.0.0)
  version_family_id?: string | null;
  parent_relation_id?: string | null;
  base_name?: string | null;
  change_summary?: string | null;
  draft_owner_id?: string | null;
  owner_team_id?: string | null;
  owner_team_name?: string | null;
  project_id?: string | null;
  project_name?: string | null;
  version_count?: number | null;  // family size (list view only); drives the count badge
  actor_role?: string | null;
  actor_identity?: string | null;
  actor_since?: string | null;
  action?: string | null;
  object_type?: string | null;
  object_id?: string | null;
  object_resolves_to?: string[] | null;
  domain_context?: DomainContext | null;
  rule?: ArfRule | null;
  justification_chain?: Record<string, any> | null;   // legacy free-form basis
  authority_policy_id?: string | null;
  policy_clause_refs?: string[];
  policy?: PolicyCitation | null;
  decision_logic?: Record<string, any> | null;
  evidence_binding?: EvidenceBinding | null;
  evidence_sources?: EvidenceSource[] | null;
  dna_magnitude?: number | null;
  dna_direction?: string | null;
  dna_dimensions?: Record<string, number> | null;   // {dimension: score} incl. structural
  dna_measured_at?: string | null;
  dna_max_threshold?: number | null;
  schedule_cron?: string | null;
  resolver_auth?: ResolverAuth;
  fully_affirmed?: boolean;
  usage_count?: number;
  approved_count?: number;
  denied_count?: number;
  domains?: AssignedDomain[];
  affirmations?: AuthorityAffirmation[];
  criteria?: AuthorityCriterion[];
  tags?: { fully_qualified_name?: string | null; assigned_value?: string | null }[];
  prerequisites?: AuthorityPrerequisite[];
  resource_refs?: AuthorityResourceRef[];
  created_at?: string;
  updated_at?: string;
  created_by?: string | null;
}

export interface AuthorityReviewTrackingReview {
  participant_id: string;
  principal: string;
  role: string;
  review_status: string;
  review_request_id?: string | null;   // real Asset Review id (linkable) or null
  request_status?: string | null;      // Asset Review request status
  request_title?: string | null;
}

export interface AuthorityReviewTrackingWorkflow {
  execution_id: string;
  workflow_id: string;
  workflow_name?: string | null;
  status: string;
  current_step?: string | null;
  entity_id?: string | null;
  started_at?: string | null;
}

export interface AuthorityReviewTracking {
  relation_id: string;
  reviews: AuthorityReviewTrackingReview[];
  workflows: AuthorityReviewTrackingWorkflow[];
}

export interface AuthorityDnaRun {
  id: string;
  status: string;                  // running | succeeded | failed
  started_at?: string | null;
  finished_at?: string | null;
  sampled_count?: number | null;
  divergent_count?: number | null;
  magnitude?: number | null;
  direction?: string | null;
  error_message?: string | null;
}

export interface AuthorityDecision {
  id: string;
  source: string;                  // mcp | evidence | ui
  verdict?: string | null;         // approved | conditional | denied | no_authority | conflict | null (evidence sample)
  reason?: string | null;
  actor_identity?: string | null;
  action?: string | null;
  object_id?: string | null;
  relation_version?: string | null;
  divergence_magnitude?: number | null;
  created_at?: string | null;
}

export interface AuthorityPrerequisite {
  prerequisite_family_slug: string;
  required: boolean;
  display_order: number;
  notes?: string | null;
  name?: string | null;          // resolved display name of the upstream AR
  status?: string | null;        // active | draft | needs_review | retired
  version?: string | null;
  resolved_id?: string | null;   // id of the currently-active version row
}

export type ResolverAuth = 'obo' | 'app_sp';

// UC MCP service from GET /api/authority/mcp-services.
export interface McpServiceInfo {
  name: string;          // mcp-services/<catalog>.<schema>.<name>
  short_name: string;
  schema: string;
  comment?: string | null;
}

// Tool from GET /api/authority/mcp-services/tools.
export interface McpToolInfo {
  name: string;
  description?: string | null;
  input_schema?: { properties?: Record<string, any>; required?: string[] } | null;
  output_schema?: Record<string, any> | null;
}

// A typed pointer backing one of the AR's canonical fields. Mirrors
// AuthorityResourceRefDb on the backend.
export interface AuthorityResourceRef {
  id?: string;
  field_path: string;
  ref_type: 'literal' | 'ontos_entity' | 'mcp_tool';
  literal_value?: string | null;
  entity_type?: string | null;    // business_concept | data_product | data_domain
  entity_id?: string | null;      // IRI (concept) or entity UUID
  mcp_service_name?: string | null;
  mcp_tool_name?: string | null;
  mcp_params?: Record<string, any> | null;
  mcp_result_pointer?: string | null;
  cached_label?: string | null;
  cached_at?: string | null;
}

export interface ResourceRefInput {
  field_path: string;
  ref_type: 'literal' | 'ontos_entity' | 'mcp_tool';
  literal_value?: string | null;
  entity_type?: string | null;
  entity_id?: string | null;
  mcp_service_name?: string | null;
  mcp_tool_name?: string | null;
  mcp_params?: Record<string, any> | null;
  mcp_result_pointer?: string | null;
}

// One row returned by GET /api/authority/entity-ref-candidates — the Ontos
// entity picker renders a flat list regardless of entity_type.
export interface EntityRefCandidate {
  entity_type: string;
  entity_id: string;
  label: string;
  iri?: string | null;
}

// A single ``resolved_refs`` entry on ResolveResponse: ``{field_path,
// ref_type, value, iri?, source, error?}``.
export interface ResolvedRefEntry {
  field_path: string;
  ref_type: 'literal' | 'ontos_entity' | 'mcp_tool';
  value: string | null;
  iri?: string | null;
  source: string;       // literal | ontos_entity | mcp_tool
  error?: string | null;
  error_kind?: string | null;  // timeout | permission | protocol | tool_error | config
}

export interface PrerequisiteInput {
  prerequisite_family_slug: string;
  required: boolean;
  display_order: number;
  notes?: string | null;
}

export interface AuthorityRelationSlug {
  family_slug: string;
  name: string;
  status: string;
  version: string;
}

export interface PrerequisiteChainEntry {
  slug: string;
  version?: string | null;
  verdict: string;
  reason?: string | null;
  required: boolean;
  pending_duties?: PendingDuty[];
}

export interface PendingDuty {
  duty: string;
  message?: string | null;
  clause?: string | null;
}

export interface ScopeCheckEntry {
  operand: string;
  operator: OdrlOperator;
  expected: any;
  actual: any;
  passed: boolean;
}

export interface AffirmationInput {
  role: string;
  business_role_id?: string | null;
  role_category?: string | null;
  principal: string;
  principal_type: string;
  required: boolean;
  is_approver?: boolean;
  is_reviewer?: boolean;
}

export interface AuthorityRelationCreate {
  name: string;
  slug?: string;
  description?: string;
  actor_role?: string;
  actor_identity?: string;
  action?: string;
  object_type?: string;
  object_id?: string;
  domain_context?: Record<string, any>;
  justification_chain?: Record<string, any>;
  decision_logic?: Record<string, any>;
  evidence_binding?: EvidenceBinding;
  dna_max_threshold?: number;
  domain_ids?: string[];
  primary_domain_id?: string | null;
  affirmations?: AffirmationInput[];
}

export interface ResolveResponse {
  verdict: string;                // approved | conditional | denied | no_authority | conflict
  reason: string;
  relation_id?: string | null;
  relation_slug?: string | null;
  relation_version?: string | null;
  dna_magnitude?: number | null;
  dna_direction?: string | null;
  prerequisite_chain?: PrerequisiteChainEntry[];
  resolved_refs?: ResolvedRefEntry[];
  scope_check?: ScopeCheckEntry[];
  pending_duties?: PendingDuty[];
  policy?: PolicyCitation | null;
}

// ------------------------------------------------------- Authority Policy

export type PolicyType = 'DOA' | 'BOARD_MANDATE' | 'REGULATION' | 'PROCUREMENT_POLICY' | 'SOP' | 'EXCEPTION';
export const POLICY_TYPES: PolicyType[] = ['DOA', 'BOARD_MANDATE', 'REGULATION', 'PROCUREMENT_POLICY', 'SOP', 'EXCEPTION'];
export type PolicyStatus = 'draft' | 'approved' | 'superseded' | 'withdrawn';

export interface PolicyClause {
  ref: string;                       // e.g. §7.1
  title?: string;
  text?: string;
  limits?: { amount?: number; currency?: string };
  conditions?: string[];
}

export interface PolicyDocument {
  id: string;
  title?: string;
  filename: string;
  content_type?: string | null;
  size_bytes?: number | null;
  sha256?: string | null;
}

export interface AuthorityPolicy {
  id: string;
  policy_key: string;
  version: string;
  version_family_id?: string | null;
  version_count?: number | null;
  parent_policy_id?: string | null;
  parent_version?: string | null;
  change_summary?: string | null;
  title: string;
  policy_type: PolicyType;
  summary?: string | null;
  owner_team_id?: string | null;
  owner_team_name?: string | null;
  jurisdiction?: Record<string, any> | null;
  effective_from?: string | null;
  effective_to?: string | null;
  status: PolicyStatus;
  root_problem?: string | null;      // why it can't ground an authority now (null = valid)
  approved_by?: string | null;
  approved_at?: string | null;
  approval_evidence_document_id?: string | null;
  withdrawn_reason?: string | null;
  clauses: PolicyClause[];
  documents: PolicyDocument[];
  dependent_count?: number;
  tags?: { fully_qualified_name?: string | null; assigned_value?: string | null }[];
  created_by?: string | null;
  created_at?: string;
  updated_at?: string;
}

/** What an AR cites (its read view and decision provenance). */
export interface PolicyCitation {
  authority_policy_id: string;
  clause_refs: string[];
  problem?: string | null;
  policy_key?: string;
  version?: string;
  title?: string;
  status?: PolicyStatus;
  policy_type?: PolicyType;
  effective_from?: string | null;
  effective_to?: string | null;
  parent_policy_id?: string | null;
  clauses?: PolicyClause[];
  documents?: { id: string; filename: string; sha256?: string | null }[];
}

export interface PolicyDependent {
  id: string;
  name: string;
  version: string;
  status: string;
  clause_refs: string[];
}

// Left operands the rule editor offers for the canonical request fields.
export const RULE_REQUEST_OPERANDS: { operand: string; field: string; kind: 'number' | 'string' | 'boolean' }[] = [
  { operand: 'payAmount', field: 'value', kind: 'number' },
  { operand: 'arf:actor', field: 'actor_identity', kind: 'string' },
  { operand: 'arf:action', field: 'action', kind: 'string' },
  { operand: 'arf:objectId', field: 'object_id', kind: 'string' },
  { operand: 'arf:cosignPresent', field: 'cosign_present', kind: 'boolean' },
  { operand: 'arf:escalated', field: 'escalated', kind: 'boolean' },
];

export const ODRL_OPERATORS: OdrlOperator[] = ['eq', 'neq', 'lt', 'lteq', 'gt', 'gteq', 'isAnyOf', 'isNoneOf'];

// ODRL core context operands a scope key keeps as is; others get the arf: prefix.
const ODRL_CONTEXT_OPERANDS = ['spatial', 'purpose', 'dateTime', 'industry', 'language', 'product'];

/** The request-context key an operand reads (`arf:market` -> `market`). */
export const operandKey = (operand: string): string => operand.split(':').pop() || operand;

/** The operand an authoring key is stored as (mirrors the backend). */
export const operandForKey = (key: string): string => {
  const k = key.trim();
  return k.includes(':') || ODRL_CONTEXT_OPERANDS.includes(k) ? k : `arf:${k}`;
};

export const ACTION_VOCAB = ['approve', 'escalate', 'override', 'delegate', 'veto'];
export const AFFIRMATION_ROLES = ['business', 'technical', 'governance'];
