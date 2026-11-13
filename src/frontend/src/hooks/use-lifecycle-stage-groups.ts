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
 * type when it is undefined; null fetches nothing. `reload` fetches them again.
 */
export function useLifecycleStageGroups(entityType?: LifecycleEntityType | null) {
  const { get } = useApi();
  const [groups, setGroups] = useState<LifecycleStageGroup[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const reload = useCallback(async () => {
    if (entityType === null) {
      setGroups([]);
      setLoading(false);
      return;
    }
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
  /** Changing it fetches the lifecycle again (the entity's status changed). */
  refreshKey?: unknown,
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
    // refreshKey: a reload when the caller's entity changed
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [get, entityType, entityId, refreshKey]);

  useEffect(() => {
    reload();
  }, [reload]);

  return { lifecycle, loading, reload };
}

/**
 * The statuses an entity's status picker offers, from the API.
 *
 * - A new entity (`entityId` empty): the stages of `groupId`'s group (the
 *   type's default when empty), `initial` being where it starts.
 * - An existing one: its current stage and the stages its group allows next.
 */
export function useStatusOptions(
  entityType: LifecycleEntityType,
  { entityId, groupId, currentStatus, enabled = true }: {
    entityId?: string | null;
    groupId?: string | null;
    /** An existing entity's stored status: always offered, even before (or
     * without) its lifecycle, or when it isn't a stage of its group. */
    currentStatus?: string | null;
    enabled?: boolean;
  },
) {
  const { groups, loading: groupsLoading } = useLifecycleStageGroups(
    enabled ? entityType : null,
  );
  const { lifecycle, loading: lifecycleLoading, reload } = useEntityLifecycle(
    entityType, enabled ? entityId : null,
  );
  const group = useMemo(() => {
    const wanted = groupId ?? lifecycle?.group.id ?? null;
    return groups.find((g) => g.id && g.id === wanted)
      ?? groups.find((g) => g.is_default_for_type) ?? groups[0] ?? null;
  }, [groups, groupId, lifecycle]);
  const options = useMemo<LifecycleStage[]>(() => {
    if (entityId) {
      // The current stage first, then the allowed moves; each key once
      const listed = !lifecycle ? [] : lifecycle.stage
        ? [lifecycle.stage, ...lifecycle.allowed_transitions]
        : lifecycle.allowed_transitions;
      const stages = listed.filter((st, i) => listed.findIndex((o) => o.key === st.key) === i);
      const current = (currentStatus || '').toLowerCase();
      if (!current || stages.some((st) => st.key === current)) return stages;
      // Shown as stored (no label or colour of a stage to draw it with)
      const stored: LifecycleStage = {
        key: current, label: currentStatus as string, category: 'draft', color: null,
        order: -1, is_initial: false,
      };
      return [stored, ...stages];
    }
    return group ? [...group.stages].sort((a, b) => a.order - b.order) : [];
  }, [entityId, lifecycle, group, currentStatus]);
  const initial = group
    ? ([...group.stages].sort((a, b) => a.order - b.order).find((s) => s.is_initial) ?? null)
    : null;
  return {
    groups, group, options, initial, lifecycle, reload,
    loading: groupsLoading || (Boolean(entityId) && lifecycleLoading),
  };
}
