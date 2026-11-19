import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { GitBranch } from 'lucide-react';
import { Button } from '@/components/ui/button';
import StageBadge from '@/components/lifecycle/stage-badge';
import ChangeLifecycleDialog from '@/components/lifecycle/change-lifecycle-dialog';
import {
  useEntityLifecycle,
  useLifecycleStageGroups,
} from '@/hooks/use-lifecycle-stage-groups';
import { groupName } from '@/lib/lifecycle-stages';
import type { LifecycleEntityType } from '@/types/lifecycle-stage-groups';

interface EntityLifecycleStatusProps {
  entityType: LifecycleEntityType;
  entityId: string;
  /** The stored status, shown until the lifecycle is loaded. */
  status?: string | null;
  /** Bump to reload the lifecycle (after a status change on the page). */
  refreshKey?: unknown;
  /** After a group change: the page reloads the entity (its status was reset). */
  onChanged?: () => void;
  /** `badge`: the status badge with the group under it; `inline`: side by side. */
  layout?: 'badge' | 'inline';
}

/**
 * An entity's status badge (from its stage), the name of its Lifecycle Stage
 * Group next to it, and "Change lifecycle" for admins and owners when the
 * entity type has another group.
 */
export default function EntityLifecycleStatus({
  entityType, entityId, status, refreshKey, onChanged, layout = 'inline',
}: EntityLifecycleStatusProps) {
  const { t } = useTranslation(['lifecycle']);
  const { lifecycle, reload } = useEntityLifecycle(entityType, entityId, refreshKey);
  const { groups } = useLifecycleStageGroups(entityType);
  const [open, setOpen] = useState(false);
  const canChange = Boolean(lifecycle?.can_change_group)
    && groups.some((g) => g.id && g.id !== lifecycle?.group.id);

  return (
    <div
      className={layout === 'badge'
        ? 'flex flex-col items-center gap-1'
        : 'flex flex-wrap items-center gap-2'}
      data-testid="entity-lifecycle-status"
    >
      <StageBadge stage={lifecycle?.stage} status={lifecycle?.status ?? status} />
      {lifecycle && (
        <span className="text-xs text-muted-foreground" title={t('lifecycle:status.groupTitle')}>
          {groupName(lifecycle.group, t)}
        </span>
      )}
      {canChange && lifecycle && (
        <>
          <Button
            variant="ghost" size="sm" className="h-6 px-2 text-xs"
            onClick={() => setOpen(true)}
          >
            <GitBranch className="h-3 w-3 mr-1" />
            {t('lifecycle:change.action')}
          </Button>
          <ChangeLifecycleDialog
            open={open}
            onOpenChange={setOpen}
            entityType={entityType}
            entityId={entityId}
            lifecycle={lifecycle}
            groups={groups}
            onChanged={() => {
              setOpen(false);
              reload();
              onChanged?.();
            }}
          />
        </>
      )}
    </div>
  );
}
