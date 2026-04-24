/**
 * Workflow label utilities.
 * 
 * Provides consistent, localized labels for workflow trigger types,
 * entity types, and step types throughout the application.
 */

import { TFunction } from 'i18next';
import {
  Shield,
  UserCheck,
  Bell,
  Tag,
  Code,
  CheckCircle,
  XCircle,
  ClipboardCheck,
  Truck,
  GitBranch,
  FileSearch,
  Globe,
  MessageSquare,
  Zap,
  FileText,
  ListChecks,
  Users,
  Database,
  Send,
  type LucideIcon,
} from 'lucide-react';
import { TriggerType, EntityType, StepType } from '@/types/process-workflow';

/**
 * Icons for each step type.
 */
export const STEP_ICONS: Record<StepType, LucideIcon> = {
  validation: Shield,
  approval: UserCheck,
  notification: Bell,
  assign_tag: Tag,
  remove_tag: Tag,
  conditional: GitBranch,
  script: Code,
  pass: CheckCircle,
  fail: XCircle,
  policy_check: ClipboardCheck,
  delivery: Truck,
  create_asset_review: FileSearch,
  webhook: Globe,
  user_action: MessageSquare,
  entity_action: Zap,
  legal_document: FileText,
  acknowledgement_checklist: ListChecks,
  co_signers: Users,
  persist_agreement: Database,
  generate_pdf: FileText,
  deliver: Send,
};

/**
 * Colors for each step type (Tailwind color names without prefix).
 */
export const STEP_COLORS: Record<StepType, string> = {
  validation: 'blue',
  approval: 'amber',
  notification: 'green',
  assign_tag: 'violet',
  remove_tag: 'rose',
  conditional: 'slate',
  script: 'cyan',
  pass: 'emerald',
  fail: 'red',
  policy_check: 'orange',
  delivery: 'indigo',
  create_asset_review: 'teal',
  webhook: 'orange',
  user_action: 'sky',
  entity_action: 'lime',
  legal_document: 'indigo',
  acknowledgement_checklist: 'teal',
  co_signers: 'violet',
  persist_agreement: 'slate',
  generate_pdf: 'orange',
  deliver: 'cyan',
};

/**
 * Get the icon for a step type with fallback.
 */
export function getStepIcon(type: StepType | string): LucideIcon {
  return STEP_ICONS[type as StepType] || Code;
}

/**
 * Get the color for a step type with fallback.
 */
export function getStepColor(type: StepType | string): string {
  return STEP_COLORS[type as StepType] || 'slate';
}

/**
 * Get a human-readable label for a trigger type.
 */
export function getTriggerTypeLabel(type: TriggerType, t: TFunction): string {
  return t(`common:workflows.triggerTypes.${type}`, { defaultValue: formatFallback(type) });
}

/**
 * Get a human-readable label for an entity type.
 */
export function getEntityTypeLabel(type: EntityType, t: TFunction): string {
  return t(`common:workflows.entityTypes.${type}`, { defaultValue: formatFallback(type) });
}

/**
 * Get a human-readable label for a step type.
 */
export function getStepTypeLabel(type: StepType, t: TFunction): string {
  return t(`common:workflows.stepTypes.${type}`, { defaultValue: formatFallback(type) });
}

/**
 * Get a formatted trigger display string including entity types.
 * Example: "On Create (Table, View)"
 */
export function getTriggerDisplay(
  trigger: { type: TriggerType; entity_types: EntityType[] },
  t: TFunction
): string {
  const typeLabel = getTriggerTypeLabel(trigger.type, t);
  
  if (!trigger.entity_types || trigger.entity_types.length === 0) {
    return typeLabel;
  }
  
  const entityLabels = trigger.entity_types
    .map(et => getEntityTypeLabel(et, t))
    .join(', ');
  
  return `${typeLabel} (${entityLabels})`;
}

/**
 * Format a snake_case or kebab-case string as a fallback label.
 * Example: "on_request_review" -> "On Request Review"
 */
function formatFallback(value: string): string {
  return value
    .replace(/[_-]/g, ' ')
    .replace(/\b\w/g, char => char.toUpperCase());
}

/**
 * All trigger types for use in selectors/dropdowns.
 */
export const ALL_TRIGGER_TYPES: TriggerType[] = [
  'on_create',
  'on_update',
  'on_delete',
  'on_status_change',
  'scheduled',
  'manual',
  'before_create',
  'before_update',
  'before_status_change',
  'on_request_review',
  'on_request_access',
  'on_request_publish',
  'on_request_status_change',
  'on_request_certify',
  'on_certify',
  'on_decertify',
  'on_job_success',
  'on_job_failure',
  'on_subscribe',
  'on_unsubscribe',
  'on_publish',
  'on_unpublish',
  'on_expiring',
  'on_revoke',
  // App-known UI actions (approval workflows, 1:1 match with ON_*)
  'for_approval_response',
  'for_subscribe',
  'for_request_review',
  'for_request_access',
  'for_request_publish',
  'for_request_certify',
  'for_request_status_change',
];

/**
 * All entity types for use in selectors/dropdowns.
 */
export const ALL_ENTITY_TYPES: EntityType[] = [
  'catalog',
  'schema',
  'table',
  'view',
  'data_contract',
  'data_product',
  'domain',
  'project',
  'access_grant',
  'role',
  'data_asset_review',
  'job',
  'subscription',
];

/**
 * All step types for use in selectors/dropdowns.
 */
export const ALL_STEP_TYPES: StepType[] = [
  'validation',
  'approval',
  'notification',
  'assign_tag',
  'remove_tag',
  'conditional',
  'script',
  'pass',
  'fail',
  'policy_check',
  'delivery',
  'create_asset_review',
  'webhook',
  'user_action',
  'entity_action',
  'legal_document',
  'acknowledgement_checklist',
  'co_signers',
  'persist_agreement',
  'generate_pdf',
  'deliver',
];

/**
 * Maps each trigger type to the entity types it is wired to fire for in the backend.
 * Used to warn users when they configure a workflow with an unwired combination.
 *
 * Updated for issue #200 — reflects all wired triggers as of this commit.
 */
export const SUPPORTED_TRIGGER_ENTITY_MAP: Record<string, string[]> = {
  // CRUD triggers
  on_create: ['catalog', 'schema', 'table', 'data_contract', 'data_product', 'domain'],
  on_update: ['data_contract', 'data_product', 'domain'],
  on_delete: ['data_contract', 'data_product', 'domain'],
  before_create: ['catalog', 'schema', 'table'],
  before_update: ['data_contract'],
  // Status & lifecycle
  before_status_change: ['data_contract', 'data_product'],
  on_status_change: ['data_contract', 'data_product', 'data_asset_review'],
  on_publish: ['data_contract', 'data_product'],
  on_unpublish: ['data_contract', 'data_product'],
  // Certification
  on_request_certify: ['data_contract', 'data_product'],
  on_certify: ['data_contract', 'data_product'],
  on_decertify: ['data_contract', 'data_product'],
  // Request triggers
  on_request_review: ['data_contract', 'data_product', 'data_asset_review'],
  on_request_access: ['access_grant', 'role', 'project'],
  on_request_publish: ['data_contract', 'data_product'],
  on_request_status_change: ['data_product'],
  // Job triggers
  on_job_success: ['job'],
  on_job_failure: ['job'],
  // Subscription triggers
  on_subscribe: ['subscription'],
  on_unsubscribe: ['subscription'],
  // Access lifecycle
  on_expiring: ['access_grant'],
  on_revoke: ['access_grant'],
  // Manual/scheduled — always supported (no entity dependency)
  scheduled: [],
  manual: [],
};

/**
 * Check if a trigger-entity combination is wired in the backend.
 * Returns true if supported, false if the combination will silently do nothing.
 */
export function isTriggerEntitySupported(triggerType: string, entityType: string): boolean {
  const supported = SUPPORTED_TRIGGER_ENTITY_MAP[triggerType];
  if (!supported) return false;
  // Empty array means all entities are valid (scheduled, manual)
  if (supported.length === 0) return true;
  return supported.includes(entityType);
}

/**
 * Special recipient values that are not role UUIDs.
 */
export const SPECIAL_RECIPIENTS: Record<string, string> = {
  'requester': 'Requester',
  'owner': 'Owner',
  'domain_owners': 'Domain Owners',
  'project_owners': 'Project Owners',
  'data_stewards': 'Data Stewards',
  'admins': 'Administrators',
};

/**
 * Resolve an approver/recipient identifier to a display name.
 * Handles both UUIDs (resolved via roles map) and special values.
 */
export function resolveRecipientDisplay(
  value: string | undefined,
  rolesMap: Record<string, string>
): string {
  if (!value) return 'Not configured';
  
  // Check special values first
  if (value in SPECIAL_RECIPIENTS) {
    return SPECIAL_RECIPIENTS[value];
  }
  
  // Check if it's a role UUID
  if (value in rolesMap) {
    return rolesMap[value];
  }
  
  // Fallback: return raw value (might be email or legacy role name)
  return value;
}

