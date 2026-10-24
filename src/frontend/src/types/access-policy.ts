/**
 * Access Policies (W3C ODRL 2.2) — policies, audiences (odrl:PartyCollection)
 * and asset collections (odrl:AssetCollection).
 */
import type { AssignedTag } from '@/components/ui/tag-chip';

export type AccessKind = 'policy' | 'audience' | 'asset_collection';
export type AccessEntityType = 'access_policy' | 'access_audience' | 'access_asset_collection';
export type AccessStatus =
  | 'draft'
  | 'under_review'
  | 'approved'
  | 'active'
  | 'needs_review'
  | 'deprecated'
  | 'retired';
export type OdrlPolicyType = 'Set' | 'Offer' | 'Agreement';
export type OdrlConflict = 'perm' | 'prohibit' | 'invalid';
export type RuleKind = 'permission' | 'prohibition' | 'obligation';

/** A Constraint (leftOperand op rightOperand) or a LogicalConstraint. */
export interface OdrlConstraint {
  leftOperand?: string;
  operator?: string;
  rightOperand?: unknown;
  rightOperandReference?: string;
  logical?: 'and' | 'or' | 'xone' | 'andSequence';
  constraints?: OdrlConstraint[];
  [key: string]: unknown;
}

/** An inline (refined) collection or a plain IRI reference. */
export type OdrlRef = string | { '@type'?: string; source?: string; uid?: string; refinement?: OdrlConstraint[]; members?: string[] } | null;

/** An atomic ODRL rule as stored by the backend. */
export interface OdrlRule {
  action: string | null;
  target?: OdrlRef;
  assignee?: OdrlRef;
  assigner?: OdrlRef;
  constraint?: OdrlConstraint[];
  action_refinement?: OdrlConstraint[];
  duty?: OdrlRule[];
  remedy?: OdrlRule[];
  consequence?: OdrlRule[];
  uid?: string;
}

export interface OdrlRules {
  permission?: OdrlRule[];
  prohibition?: OdrlRule[];
  obligation?: OdrlRule[];
}

export interface AssignedDomainRef {
  domain_id: string;
  domain_name?: string | null;
  is_primary?: boolean;
}

export interface AccessEntityBase {
  id: string;
  kind: AccessKind;
  entity_type: AccessEntityType;
  uid: string;
  name: string;
  description?: string | null;
  status: AccessStatus;
  allowed_transitions: AccessStatus[];
  editable: boolean;
  version: string;
  version_family_id: string;
  parent_id?: string | null;
  change_summary?: string | null;
  draft_owner_id?: string | null;
  version_count?: number | null;
  owner_team_id?: string | null;
  project_id?: string | null;
  maturity_level_order?: number | null;
  domains: AssignedDomainRef[];
  tags: AssignedTag[];
  created_by?: string | null;
  updated_by?: string | null;
  created_at?: string;
  updated_at?: string;
}

export interface AccessPolicy extends AccessEntityBase {
  kind: 'policy';
  policy_type: OdrlPolicyType;
  conflict: OdrlConflict;
  inherit_from: string[];
  rules: OdrlRules;
  rule_counts: Record<RuleKind, number>;
}

export interface UsedByRef {
  id: string;
  name: string;
  version: string;
  status: AccessStatus;
}

export interface AccessCollection extends AccessEntityBase {
  kind: 'audience' | 'asset_collection';
  members: string[];
  refinement: OdrlConstraint[];
  used_by: UsedByRef[];
}

export type AccessEntity = AccessPolicy | AccessCollection;

export interface VersionRow {
  id: string;
  name: string;
  version: string;
  status: AccessStatus;
  parent_id?: string | null;
  change_summary?: string | null;
  created_at?: string;
  created_by?: string | null;
}

export interface ValidationIssue {
  severity: 'error' | 'warning';
  path: string;
  message: string;
}

export interface PolicyValidation {
  valid: boolean;
  issues: ValidationIssue[];
  activation_problems?: string[];
}

export interface ProfileAction {
  key: string;
  label: string;
  included_in: string | null;
  implies: string[];
  description: string;
}

export interface ProfileLeftOperand {
  key: string;
  label: string;
  enforcement: 'platform' | 'workflow' | 'advisory';
  subject: 'context' | 'party' | 'asset';
  datatype: string;
  description: string;
}

export interface OdrlProfile {
  profile: string;
  policy_types: OdrlPolicyType[];
  conflict_terms: OdrlConflict[];
  default_conflict: OdrlConflict;
  actions: ProfileAction[];
  left_operands: ProfileLeftOperand[];
  operators: { key: string; label: string }[];
  logical_operands: string[];
}

export interface RuleMatch {
  policy_uid: string;
  policy_name: string;
  kind: RuleKind;
  index: number;
  action: string;
  target: OdrlRef;
  assignee: OdrlRef;
  effect: 'permit' | 'prohibit' | 'pending_duties' | 'constraint_unmet';
  reasons: string[];
  pending_duties: string[];
  unenforceable: string[];
}

export interface AccessDecision {
  verdict: 'allow' | 'deny' | 'conditional' | 'not_applicable';
  allowed: boolean;
  explanation: string[];
  matches: RuleMatch[];
  void_policies: string[];
  pending_duties: string[];
  evaluated_policies: { id: string; uid: string; name: string; version: string; status: AccessStatus }[];
  resolved_principal_attributes: Record<string, string[]>;
  warnings: string[];
  mode: 'active' | 'what_if';
}

/** URL segment used by the API and the routes for each kind. */
export const KIND_SEGMENT: Record<AccessKind, string> = {
  policy: 'policies',
  audience: 'audiences',
  asset_collection: 'asset-collections',
};

export const SEGMENT_KIND: Record<string, AccessKind> = {
  policies: 'policy',
  audiences: 'audience',
  'asset-collections': 'asset_collection',
};

export const KIND_ENTITY_TYPE: Record<AccessKind, AccessEntityType> = {
  policy: 'access_policy',
  audience: 'access_audience',
  asset_collection: 'access_asset_collection',
};

export const AUDIENCE_IRI_PREFIX = 'urn:ontos:audience:';
export const ASSET_COLLECTION_IRI_PREFIX = 'urn:ontos:asset-collection:';
