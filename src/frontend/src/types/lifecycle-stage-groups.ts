/**
 * Lifecycle Stage Groups (PRD #1208): the API shapes of
 * `/api/lifecycle-stage-groups` and `/api/lifecycle/{entity_type}/{id}`.
 *
 * An entity's `status` is the key of a stage of its group; code branches on the
 * stage's category, never on its label.
 */

export type StageCategory = 'draft' | 'review' | 'active' | 'deprecated' | 'retired';

export const STAGE_CATEGORIES: StageCategory[] = [
  'draft', 'review', 'active', 'deprecated', 'retired',
];

export type LifecycleEntityType = 'data_product' | 'data_contract' | 'asset';

export const LIFECYCLE_ENTITY_TYPES: LifecycleEntityType[] = [
  'data_product', 'data_contract', 'asset',
];

export interface LifecycleStage {
  key: string;
  label: string;
  category: StageCategory;
  color: string | null;
  order: number;
  is_initial: boolean;
}

export interface LifecycleStageTransition {
  from_key: string;
  to_key: string;
}

export interface LifecycleStageGroup {
  /** null only for a built-in default that isn't stored yet */
  id: string | null;
  name: string;
  description?: string | null;
  entity_type: LifecycleEntityType;
  is_default_for_type: boolean;
  stages: LifecycleStage[];
  transitions: LifecycleStageTransition[];
  created_by?: string | null;
  updated_by?: string | null;
  created_at?: string | null;
  updated_at?: string | null;
}

/** The body of a group save: the whole group, replacing its stages and transitions. */
export type LifecycleStageGroupWrite = Omit<
  LifecycleStageGroup, 'id' | 'created_by' | 'updated_by' | 'created_at' | 'updated_at'
>;

export interface LifecycleStageGroupSummary {
  id: string | null;
  name: string;
  entity_type: LifecycleEntityType;
  is_default_for_type: boolean;
}

/** `GET /api/lifecycle/{entity_type}/{id}`: the group, stage and allowed next stages. */
export interface EntityLifecycle {
  entity_type: LifecycleEntityType;
  entity_id: string;
  group: LifecycleStageGroupSummary;
  status: string;
  stage: LifecycleStage | null;
  allowed_transitions: LifecycleStage[];
}
