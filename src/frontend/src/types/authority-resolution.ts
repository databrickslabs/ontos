export interface AssignedDomain {
  domain_id: string;
  domain_name: string;
  is_primary: boolean;
  assigned_by?: string | null;
  assigned_at?: string | null;
}

export interface AuthorityAffirmation {
  id: string;
  role: string;
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
    domain_context?: Record<string, any> | null;
    decision_logic?: Record<string, any> | null;
    evidence_binding?: EvidenceBinding | null;
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

export interface AuthorityRelation {
  id: string;
  slug?: string | null;
  name: string;
  description?: string | null;
  status: string;                 // draft | active | needs_review | retired
  maturity_level: string;         // L1..L4
  version: number;
  version_family_id?: string | null;
  actor_role?: string | null;
  actor_identity?: string | null;
  actor_since?: string | null;
  action?: string | null;
  object_type?: string | null;
  object_id?: string | null;
  object_resolves_to?: string[] | null;
  domain_context?: Record<string, any> | null;
  justification_chain?: Record<string, any> | null;
  decision_logic?: Record<string, any> | null;
  evidence_binding?: EvidenceBinding | null;
  evidence_sources?: EvidenceSource[] | null;
  dna_magnitude?: number | null;
  dna_direction?: string | null;
  dna_measured_at?: string | null;
  dna_max_threshold?: number | null;
  schedule_cron?: string | null;
  fully_affirmed?: boolean;
  usage_count?: number;
  approved_count?: number;
  denied_count?: number;
  domains?: AssignedDomain[];
  affirmations?: AuthorityAffirmation[];
  tags?: { fully_qualified_name?: string | null; assigned_value?: string | null }[];
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
  verdict?: string | null;         // approved | denied | null (evidence sample)
  reason?: string | null;
  actor_identity?: string | null;
  action?: string | null;
  object_id?: string | null;
  relation_version?: number | null;
  divergence_magnitude?: number | null;
  created_at?: string | null;
}

export interface AffirmationInput {
  role: string;
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
  verdict: string;                // approved | denied | no_authority | conflict
  reason: string;
  relation_id?: string | null;
  relation_slug?: string | null;
  relation_version?: number | null;
  dna_magnitude?: number | null;
  dna_direction?: string | null;
}

export const ACTION_VOCAB = ['approve', 'escalate', 'override', 'delegate', 'veto'];
export const AFFIRMATION_ROLES = ['business', 'technical', 'governance'];
