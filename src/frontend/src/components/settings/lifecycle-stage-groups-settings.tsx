import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { Star } from 'lucide-react';
import { Badge } from '@/components/ui/badge';
import { Tabs, TabsList, TabsTrigger } from '@/components/ui/tabs';
import { ListItemSkeleton } from '@/components/common/list-view-skeleton';
import StageBadge from '@/components/lifecycle/stage-badge';
import { useLifecycleStageGroups } from '@/hooks/use-lifecycle-stage-groups';
import { groupName, orderedStages } from '@/lib/lifecycle-stages';
import {
  LIFECYCLE_ENTITY_TYPES,
  type LifecycleEntityType,
} from '@/types/lifecycle-stage-groups';

/**
 * Settings > Lifecycle Stage Groups: the groups of each entity type, the
 * type's default first.
 */
export default function LifecycleStageGroupsSettings() {
  const { t } = useTranslation(['lifecycle', 'common']);
  const [entityType, setEntityType] = useState<LifecycleEntityType>('data_product');
  const { groups, loading, error } = useLifecycleStageGroups(entityType);

  return (
    <div className="space-y-6">
      <div>
        <h2 className="text-lg font-semibold">{t('lifecycle:settings.title')}</h2>
        <p className="text-sm text-muted-foreground">{t('lifecycle:settings.description')}</p>
      </div>

      <Tabs value={entityType} onValueChange={(v) => setEntityType(v as LifecycleEntityType)}>
        <TabsList>
          {LIFECYCLE_ENTITY_TYPES.map((type) => (
            <TabsTrigger key={type} value={type}>
              {t(`lifecycle:entityType.${type}`)}
            </TabsTrigger>
          ))}
        </TabsList>
      </Tabs>

      {loading ? (
        <ListItemSkeleton count={2} height="h-16" className="space-y-2" />
      ) : error ? (
        <p className="text-sm text-destructive" role="alert">{error}</p>
      ) : groups.length === 0 ? (
        <p className="text-sm text-muted-foreground">{t('lifecycle:settings.empty')}</p>
      ) : (
        <ul className="space-y-3" aria-label={t('lifecycle:settings.groupList')}>
          {groups.map((group) => (
            <li key={group.id ?? group.name} className="rounded-md border p-4 space-y-2">
              <div className="flex items-center gap-2">
                <span className="font-medium">{groupName(group, t)}</span>
                {group.is_default_for_type && (
                  <Badge variant="secondary" className="gap-1">
                    <Star className="h-3 w-3" /> {t('lifecycle:settings.default')}
                  </Badge>
                )}
              </div>
              {group.description && (
                <p className="text-sm text-muted-foreground">{group.description}</p>
              )}
              <div className="flex flex-wrap gap-1">
                {orderedStages(group).map((stage) => (
                  <StageBadge key={stage.key} stage={stage} />
                ))}
              </div>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
