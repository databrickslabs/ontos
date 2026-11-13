import type { ApiResponse } from '@/hooks/use-api';
import type {
  LifecycleEntityType,
  LifecycleStage,
  LifecycleStageGroup,
} from '@/types/lifecycle-stage-groups';

/** A translate function, as `t` from useTranslation or a narrower one. */
type Translate = (key: string, options?: Record<string, unknown>) => string;

/**
 * The English labels the seeded default groups give their stages. A stage whose
 * label is still this one is shown through `lifecycle:stage.<key>` (the UI
 * language); a label an admin changed is user data and shown as written.
 */
export const SEEDED_STAGE_LABELS: Record<string, string> = {
  draft: 'Draft',
  sandbox: 'Sandbox',
  proposed: 'Proposed',
  under_review: 'Under Review',
  approved: 'Approved',
  active: 'Active',
  deprecated: 'Deprecated',
  retired: 'Retired',
};

/** A stage's label in the UI language while it is a seeded, unchanged one. */
export function stageLabel(
  stage: Pick<LifecycleStage, 'key' | 'label'>,
  t: Translate,
): string {
  if (SEEDED_STAGE_LABELS[stage.key] === stage.label) {
    return t(`lifecycle:stage.${stage.key}`, { defaultValue: stage.label });
  }
  return stage.label;
}

/** A seeded stage whose label is unchanged: its app texts (descriptions, hints) apply. */
export function isSeededStage(stage: Pick<LifecycleStage, 'key' | 'label'>): boolean {
  return SEEDED_STAGE_LABELS[stage.key] === stage.label;
}

/**
 * In a review stage that awaits a steward's decision (Approve / Reject): any
 * review-category stage but the approve action's own `approved`, as the
 * backend's lifecycle service decides (proposed / under_review by default). A
 * row without its category (an older API) falls back to the seeded keys.
 */
export function awaitsReviewDecision(
  entity: { status?: string | null; status_category?: string | null },
): boolean {
  const status = (entity.status || '').toLowerCase();
  const category = entity.status_category
    ?? (['proposed', 'under_review'].includes(status) ? 'review' : null);
  return category === 'review' && status !== 'approved';
}

/** A Stage Category in the UI language. */
export function categoryLabel(category: string, t: Translate): string {
  return t(`lifecycle:category.${category}`, { defaultValue: category });
}

/** A group's name in the UI language while it is a seeded default's unchanged name. */
export function groupName(
  group: { name: string; entity_type: LifecycleEntityType | string },
  t: Translate,
): string {
  const seeded = SEEDED_GROUP_NAMES[group.entity_type as LifecycleEntityType];
  if (seeded && seeded === group.name) {
    return t(`lifecycle:defaultGroupName.${group.entity_type}`, { defaultValue: group.name });
  }
  return group.name;
}

const SEEDED_GROUP_DESCRIPTION = 'Seeded lifecycle; reproduces the built-in transitions.';

/** A group's description, in the UI language while it is the seeded one. */
export function groupDescription(
  group: { description?: string | null },
  t: Translate,
): string {
  if (!group.description) return '';
  if (group.description === SEEDED_GROUP_DESCRIPTION) {
    return t('lifecycle:defaultGroupDescription', { defaultValue: group.description });
  }
  return group.description;
}

const SEEDED_GROUP_NAMES: Record<LifecycleEntityType, string> = {
  data_product: 'Default data product lifecycle',
  data_contract: 'Default data contract lifecycle',
  asset: 'Default asset lifecycle',
};

/** Colours a stage can have, with the badge classes each one renders with. */
export const STAGE_COLORS: Record<string, string> = {
  gray: 'bg-gray-100 text-gray-800 border-gray-300 dark:bg-gray-800 dark:text-gray-200',
  slate: 'bg-slate-100 text-slate-800 border-slate-300 dark:bg-slate-800 dark:text-slate-200',
  purple:
    'bg-purple-100 text-purple-800 border-purple-300 dark:bg-purple-900 dark:text-purple-200',
  indigo:
    'bg-indigo-100 text-indigo-800 border-indigo-300 dark:bg-indigo-900 dark:text-indigo-200',
  blue: 'bg-blue-100 text-blue-800 border-blue-300 dark:bg-blue-900 dark:text-blue-200',
  sky: 'bg-sky-100 text-sky-800 border-sky-300 dark:bg-sky-900 dark:text-sky-200',
  teal: 'bg-teal-100 text-teal-800 border-teal-300 dark:bg-teal-900 dark:text-teal-200',
  emerald:
    'bg-emerald-100 text-emerald-800 border-emerald-300 dark:bg-emerald-900 dark:text-emerald-200',
  green: 'bg-green-100 text-green-800 border-green-300 dark:bg-green-900 dark:text-green-200',
  yellow:
    'bg-yellow-100 text-yellow-800 border-yellow-300 dark:bg-yellow-900 dark:text-yellow-200',
  amber: 'bg-amber-100 text-amber-800 border-amber-300 dark:bg-amber-900 dark:text-amber-200',
  orange:
    'bg-orange-100 text-orange-800 border-orange-300 dark:bg-orange-900 dark:text-orange-200',
  red: 'bg-red-100 text-red-800 border-red-300 dark:bg-red-900 dark:text-red-200',
  pink: 'bg-pink-100 text-pink-800 border-pink-300 dark:bg-pink-900 dark:text-pink-200',
};

/** The colour a stage without one gets, by its category. */
const CATEGORY_COLORS: Record<string, string> = {
  draft: 'gray',
  review: 'blue',
  active: 'green',
  deprecated: 'orange',
  retired: 'red',
};

/** The badge classes of a stage: its colour, else its category's. */
export function stageColorClass(
  stage: Pick<LifecycleStage, 'color' | 'category'> | null | undefined,
): string {
  const color = stage?.color && STAGE_COLORS[stage.color]
    ? stage.color
    : CATEGORY_COLORS[stage?.category ?? 'draft'] ?? 'gray';
  return STAGE_COLORS[color];
}

/** The stages of a group in their order. */
export function orderedStages(group: Pick<LifecycleStageGroup, 'stages'>): LifecycleStage[] {
  return [...group.stages].sort((a, b) => a.order - b.order);
}

/**
 * The error of a lifecycle request (`lifecycle_*` codes of the backend's
 * lifecycle service), in the user's language from `lifecycle:errors.<code>`.
 * Stage keys in the parameters are kept as keys; lists are joined. Any other
 * error is the API's text.
 */
export function lifecycleErrorText(
  response: Pick<ApiResponse<unknown>, 'error' | 'errorCode' | 'errorParams'>,
  t: Translate,
): string {
  const error = response.error || '';
  const code = response.errorCode;
  if (!code || !(code.startsWith('lifecycle_') || code === 'invalid_status_transition')) {
    return error;
  }
  const params: Record<string, unknown> = {};
  for (const [name, value] of Object.entries(response.errorParams ?? {})) {
    params[name] = Array.isArray(value) ? value.map(String).join(', ') : value;
  }
  if (code === 'lifecycle_stage_invalid_category' && typeof params.category === 'string') {
    params.category = categoryLabel(params.category, t);
  }
  if (code === 'invalid_status_transition' && !params.allowed) {
    params.allowed = t('lifecycle:errors.none', { defaultValue: 'none' });
  }
  return t(`lifecycle:errors.${code}`, { ...params, defaultValue: error });
}
