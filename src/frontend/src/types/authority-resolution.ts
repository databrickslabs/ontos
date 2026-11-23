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
  // True when affirmed on an earlier draft; does not count as affirmed.
  stale?: boolean;
  definition_hash?: string | null;
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
    evidence_slice?: EvidenceSlice | null;
    adm_schema?: string | null;
    justification_chain?: Record<string, any> | null;
  } | null;
}

// The slice of the shared ADM schema's observations an AR reads (ARF 1.2.0, #1294 slice 4).
// There is no table reference: the schema is the app setting, or the AR's own override.
export interface EvidenceSlice {
  action_codes: string[];            // 1..20 lowercase ADM action codes, e.g. approve
  object_refs: string[];             // 0..200 exact object_ref values; empty = all objects of those actions
  domain_scope: boolean;             // applies the AR's domain-context scope to observed rows
  window_days: number;               // 1..3650
  sample_size: number;               // 1..5000
}

// One dimension of a DNA-Coefficient run (ARF 1.2.0 slice 4). `kind: 'definition'` marks the
// structural entry: its magnitude is the AR definition completeness and does not gate.
export interface DnaDimension {
  position: number;                  // -1..+1, signed direction of the divergence
  magnitude: number;                 // 0..1, share of sampled decisions that diverge
  weight: number;
  kind?: 'definition';
}

// NEW runs store a DnaDimension per dimension; LEGACY runs (before slice 4) store a bare
// magnitude (the old noisy-OR value) with no signed position.
export type DnaDimensionValue = DnaDimension | number;

export interface AdmConformanceFinding {
  code: 'missing_table' | 'missing_column' | 'type_mismatch';
  table: string;
  column?: string;
  expected?: string;
  actual?: string;
}

export interface AdmConformance {
  status: 'conformant' | 'nonconformant' | 'unavailable';
  schema: string;
  adm_version: string;
  findings: AdmConformanceFinding[];
  error_code?: string | null;
  checked_tables: string[];
}

// GET/PUT /api/authority/adm-schema. `schema` is the app-wide `catalog.schema` (or null).
export interface AdmSchemaState {
  schema: string | null;
  adm_version: string;
  conformance: AdmConformance | null;
}

export interface ComputeDnacoResponse {
  run_id: string;
  status: string;
  sampled_count: number;
  divergent_count: number;
  magnitude: number;
  position: number | null;
  direction: string | null;
}

// Provenance of a criterion copied from elsewhere. Stored as a label only:
// the check is owned by the AR version and has no live link.
export interface CriterionProvenance {
  kind: 'compliance' | 'template' | 'migrated';
  label: string;
  id?: string;
  key?: string;
}

export interface AuthorityCriterion {
  id: string;
  name?: string | null;
  rule?: string | null;              // Compliance-DSL ASSERT rule (the condition)
  failure_message?: string | null;
  direction: string;                 // actual-exceeds-documented | documented-exceeds-actual | neutral
  weight: number;
  dimension?: string;                // DNAco dimension (people|policy|…)
  order: number;
  enabled: boolean;
  policy_clause_ref?: string | null; // the Authority Policy clause this check enforces
  copied_from?: CriterionProvenance | null;
}

// One row of GET /api/authority/criteria/templates (ARF template registry).
export interface AuthorityCriterionTemplate {
  key: string;
  name: string;
  rule: string;
  failure_message: string;
  dimension: string;
  direction: string;
  description?: string | null;
}

// A criteria write. With template_key set, the server fills name, rule,
// failure_message, dimension and direction from the template registry.
export interface CriterionInput {
  template_key?: string;
  name?: string;
  rule?: string;
  failure_message?: string;
  direction?: string;
  weight?: number;
  dimension?: string;
  order?: number;
  enabled?: boolean;
  copied_from?: CriterionProvenance;
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
  // Only drafts are editable, and only the newest version of a family.
  editable?: boolean;
  definition_hash?: string | null;
  definition_edited_by?: string | null;
  enabled_check_count?: number;
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
  evidence_slice?: EvidenceSlice | null;
  // Per-AR override of the shared ADM schema (`catalog.schema`). Admin-only to change.
  adm_schema_override?: string | null;
  // The EFFECTIVE schema: the override, else the shared one. Null when neither is set.
  adm_schema?: string | null;
  dna_magnitude?: number | null;     // 0..1, share of sampled decisions that diverge; the ceiling gates on it
  dna_position?: number | null;      // -1..+1 combined signed position
  dna_direction?: string | null;
  dna_dimensions?: Record<string, DnaDimensionValue> | null;   // {dimension: entry} incl. structural
  dna_measured_at?: string | null;
  // False with dna_magnitude set: measured on an earlier draft.
  dna_current?: boolean;
  dna_max_threshold?: number | null; // the ceiling (magnitude must stay at or below it)
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
  evidence_slice?: EvidenceSlice;
  adm_schema_override?: string | null;
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

// ------------------------------------------------------- Policy reference (ARF 1.2.0)
// A reference is metadata: nothing about it is enforced. Its validity reaches the
// Compliance checks as justification.* (see the justification check template).

/** A clause label, offered as a suggestion when an AR cites a clause. Free text otherwise. */
export interface PolicyClause {
  ref: string;                       // e.g. §7.1
  title?: string;
  text?: string;
}

export interface AuthorityPolicy {
  id: string;
  policy_key: string;                // external id, shared by every version
  version: string;
  version_family_id?: string | null;
  version_count?: number | null;
  parent_policy_id?: string | null;
  parent_version?: string | null;
  change_summary?: string | null;
  title: string;                     // name
  summary?: string | null;           // description
  owner_team_id?: string | null;
  owner_team_name?: string | null;
  url?: string | null;               // link out to the source document
  valid_from?: string | null;
  valid_to?: string | null;
  expired: boolean;                  // computed at read time; informational
  clauses: PolicyClause[];           // suggestions only
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
  policy_key?: string;
  version?: string;
  title?: string;
  url?: string | null;
  valid_from?: string | null;
  valid_to?: string | null;
  expired?: boolean;
  parent_policy_id?: string | null;
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

/**
 * The request field a scope operand reads (mirrors the backend's scope_key): a typed field
 * reads its canonical field (arf:actor -> actor_identity), not a key the caller picks (#1491-2).
 */
export const scopeKey = (operand: string): string =>
  RULE_REQUEST_OPERANDS.find((o) => o.operand === operand)?.field ?? operandKey(operand);

/** The request fields a scope reads, from stored scope operands. */
export const scopeRequestKeys = (scope: { leftOperand: string }[]): string[] =>
  scope.map((c) => scopeKey(c.leftOperand));

export const ACTION_VOCAB = ['approve', 'escalate', 'override', 'delegate', 'veto'];
export const AFFIRMATION_ROLES = ['business', 'technical', 'governance'];

// ------------------------------------------------ Evidence slice + ADM schema (ARF 1.2.0, #1294 slice 4)

export const EVIDENCE_BOUNDS = {
  actionCodesMax: 20,
  objectRefsMax: 200,
  windowDaysMin: 1,
  windowDaysMax: 3650,
  windowDaysDefault: 90,
  sampleSizeMin: 1,
  sampleSizeMax: 5000,
  sampleSizeDefault: 500,
} as const;

// Lowercase ADM action codes (approve, escalate, ...). The server bounds the count only;
// this shape check is the editor's own guard against typos.
export const ACTION_CODE_PATTERN = /^[a-z][a-z0-9_-]{0,63}$/;

// `catalog.schema`: two dot-separated identifiers, no whitespace.
export const ADM_SCHEMA_PATTERN = /^[^.\s]+\.[^.\s]+$/;

/** The editor's text state for a slice; numbers stay text until validated. */
export interface EvidenceSliceDraft {
  action_codes: string[];
  object_refs: string[];
  domain_scope: boolean;
  window_days: string;
  sample_size: string;
}

export type EvidenceSliceError =
  | 'actionCodesRequired'
  | 'actionCodesTooMany'
  | 'actionCodeInvalid'
  | 'objectRefsTooMany'
  | 'windowDaysRange'
  | 'sampleSizeRange';

export const newEvidenceSliceDraft = (actionCode = 'approve'): EvidenceSliceDraft => ({
  action_codes: [actionCode],
  object_refs: [],
  domain_scope: true,
  window_days: String(EVIDENCE_BOUNDS.windowDaysDefault),
  sample_size: String(EVIDENCE_BOUNDS.sampleSizeDefault),
});

const isIntIn = (text: string, lo: number, hi: number): boolean => {
  const n = Number(text.trim());
  return text.trim() !== '' && Number.isInteger(n) && n >= lo && n <= hi;
};

/** Validates a draft against the server bounds; an empty list means the slice is valid. */
export function evidenceSliceErrors(draft: EvidenceSliceDraft): EvidenceSliceError[] {
  const errors: EvidenceSliceError[] = [];
  if (draft.action_codes.length === 0) errors.push('actionCodesRequired');
  if (draft.action_codes.length > EVIDENCE_BOUNDS.actionCodesMax) errors.push('actionCodesTooMany');
  if (draft.action_codes.some((c) => !ACTION_CODE_PATTERN.test(c))) errors.push('actionCodeInvalid');
  if (draft.object_refs.length > EVIDENCE_BOUNDS.objectRefsMax) errors.push('objectRefsTooMany');
  if (!isIntIn(draft.window_days, EVIDENCE_BOUNDS.windowDaysMin, EVIDENCE_BOUNDS.windowDaysMax)) errors.push('windowDaysRange');
  if (!isIntIn(draft.sample_size, EVIDENCE_BOUNDS.sampleSizeMin, EVIDENCE_BOUNDS.sampleSizeMax)) errors.push('sampleSizeRange');
  return errors;
}

/** The wire shape of a valid draft (call evidenceSliceErrors first). */
export function evidenceSliceFromDraft(draft: EvidenceSliceDraft): EvidenceSlice {
  return {
    action_codes: draft.action_codes,
    object_refs: draft.object_refs,
    domain_scope: draft.domain_scope,
    window_days: Number(draft.window_days.trim()),
    sample_size: Number(draft.sample_size.trim()),
  };
}

export const draftFromEvidenceSlice = (slice: EvidenceSlice): EvidenceSliceDraft => ({
  action_codes: [...slice.action_codes],
  object_refs: [...(slice.object_refs || [])],
  domain_scope: slice.domain_scope ?? true,
  window_days: String(slice.window_days ?? EVIDENCE_BOUNDS.windowDaysDefault),
  sample_size: String(slice.sample_size ?? EVIDENCE_BOUNDS.sampleSizeDefault),
});

const clampRange = (x: number, lo: number, hi: number): number => Math.min(hi, Math.max(lo, x));

export interface DnaDimensionRow {
  name: string;
  /** Signed position -1..+1; null for a legacy (magnitude-only) dimension. */
  position: number | null;
  magnitude: number;
  weight: number | null;
  /** The structural entry: its magnitude is definition completeness and does not gate. */
  definition: boolean;
  legacy: boolean;
}

/** Normalises both dimension shapes (new entries and legacy bare numbers) into rows, sorted by name. */
export function dnaDimensionRows(dims: Record<string, DnaDimensionValue> | null | undefined): DnaDimensionRow[] {
  if (!dims) return [];
  return Object.entries(dims)
    .sort(([a], [b]) => a.localeCompare(b))
    .map(([name, v]): DnaDimensionRow => {
      if (typeof v === 'number') {
        return { name, position: null, magnitude: clampRange(v, 0, 1), weight: null, definition: false, legacy: true };
      }
      return {
        name,
        position: typeof v.position === 'number' ? clampRange(v.position, -1, 1) : null,
        magnitude: clampRange(Number(v.magnitude) || 0, 0, 1),
        weight: typeof v.weight === 'number' ? v.weight : null,
        definition: v.kind === 'definition',
        legacy: typeof v.position !== 'number',
      };
    });
}

/** True when any dimension is a pre-slice-4 bare number (no signed position). */
export const isLegacyDnaDimensions = (dims: Record<string, DnaDimensionValue> | null | undefined): boolean =>
  dnaDimensionRows(dims).some((r) => r.legacy);
