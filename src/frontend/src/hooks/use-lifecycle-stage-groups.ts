import { useCallback, useEffect, useMemo, useState } from 'react';
import { useApi } from '@/hooks/use-api';
import type {
  EntityLifecycle,
  LifecycleEntityType,
  LifecycleStage,
  LifecycleStageGroup,
} from '@/types/lifecycle-stage-groups';

/**
 * The Lifecycle Stage Groups of an entity type (default first), or of every
 * type without one. `reload` fetches them again (after a save).
 */
export function useLifecycleStageGroups(entityType?: LifecycleEntityType | null) {
  const { get } = useApi();
  const [groups, setGroups] = useState<LifecycleStageGroup[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const reload = useCallback(async () => {
    setLoading(true);
    const url = entityType
      ? `/api/lifecycle-stage-groups?entity_type=${entityType}`
      : '/api/lifecycle-stage-groups';
    const response = await get<LifecycleStageGroup[]>(url);
    if (response.error) {
      setError(response.error);
      setGroups([]);
    } else {
      setError(null);
      setGroups(Array.isArray(response.data) ? response.data : []);
    }
    setLoading(false);
  }, [get, entityType]);

  useEffect(() => {
    reload();
  }, [reload]);

  return { groups, loading, error, reload };
}

/** A stage by its entity's group and key: the stage data badges are drawn from. */
export type StageLookup = (
  groupId: string | null | undefined,
  key: string | null | undefined,
) => LifecycleStage | null;

/**
 * The stage of an entity from its `lifecycle_stage_group_id` and `status`,
 * over the groups of its type: its own group's stage, else the default
 * group's (an entity without a group follows the default).
 */
export function buildStageLookup(groups: LifecycleStageGroup[]): StageLookup {
  const byGroup = new Map<string, Map<string, LifecycleStage>>();
  let fallback: Map<string, LifecycleStage> | null = null;
  for (const group of groups) {
    const stages = new Map(group.stages.map((s) => [s.key, s]));
    if (group.id) byGroup.set(group.id, stages);
    if (group.is_default_for_type) fallback = stages;
  }
  return (groupId, key) => {
    const normalized = (key || '').toLowerCase();
    if (!normalized) return null;
    const own = groupId ? byGroup.get(groupId) : undefined;
    return own?.get(normalized) ?? (own ? null : fallback?.get(normalized) ?? null);
  };
}

/** `buildStageLookup` over the groups of `entityType`, fetched once. */
export function useStageLookup(entityType: LifecycleEntityType): StageLookup {
  const { groups } = useLifecycleStageGroups(entityType);
  return useMemo(() => buildStageLookup(groups), [groups]);
}

/**
 * An entity's lifecycle: its group, current stage and allowed next stages,
 * from `GET /api/lifecycle/{entity_type}/{id}`. Nothing is fetched without an id.
 */
export function useEntityLifecycle(
  entityType: LifecycleEntityType,
  entityId: string | null | undefined,
) {
  const { get } = useApi();
  const [lifecycle, setLifecycle] = useState<EntityLifecycle | null>(null);
  const [loading, setLoading] = useState(Boolean(entityId));

  const reload = useCallback(async () => {
    if (!entityId) {
      setLifecycle(null);
      setLoading(false);
      return;
    }
    setLoading(true);
    const response = await get<EntityLifecycle>(
      `/api/lifecycle/${entityType}/${encodeURIComponent(entityId)}`,
    );
    setLifecycle(response.error ? null : response.data);
    setLoading(false);
  }, [get, entityType, entityId]);

  useEffect(() => {
    reload();
  }, [reload]);

  return { lifecycle, loading, reload };
}
