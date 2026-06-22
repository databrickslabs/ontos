import { useMemo } from 'react';
import { useTranslation } from 'react-i18next';
import { Button } from '@/components/ui/button';
import { Link } from 'react-router-dom';
import { usePermissions } from '@/stores/permissions-store';
import { useFeatureVisibilityStore } from '@/stores/feature-visibility-store';
import { FeatureAccessLevel } from '@/types/settings';
import { features, type FeatureGroup } from '@/config/features';
import { SkeletonLine } from '@/components/common/list-view-skeleton';

interface QuickAction {
  name: string;
  path: string;
  group: FeatureGroup;
  featureId: string;
}

export default function QuickActions() {
  const { t } = useTranslation(['home', 'features']);
  const { isLoading: permissionsLoading, hasPermission } = usePermissions();
  const allowedMaturities = useFeatureVisibilityStore((state) => state.allowedMaturities);

  const actions: QuickAction[] = useMemo(() => {
    if (permissionsLoading) return [];
    const list: QuickAction[] = [];
    const addedFeatures = new Set<string>();

    // Map features to quick actions based on permissions
    const actionMapping: { featureId: string; requiredLevel: FeatureAccessLevel; action: string }[] = [
      // Discover - Browse actions for read-only
      { featureId: 'marketplace', requiredLevel: FeatureAccessLevel.READ_ONLY, action: 'browse' },
      { featureId: 'data-catalog', requiredLevel: FeatureAccessLevel.READ_ONLY, action: 'browse' },
      { featureId: 'search', requiredLevel: FeatureAccessLevel.READ_ONLY, action: 'search' },

      // Build - Create/Define actions (prefer write over read)
      { featureId: 'data-products', requiredLevel: FeatureAccessLevel.READ_WRITE, action: 'create' },
      { featureId: 'data-contracts', requiredLevel: FeatureAccessLevel.READ_WRITE, action: 'define' },
      { featureId: 'concepts', requiredLevel: FeatureAccessLevel.READ_WRITE, action: 'create' },
      { featureId: 'assets', requiredLevel: FeatureAccessLevel.READ_WRITE, action: 'manage' },

      // Build - Fallback to browse if no write access
      { featureId: 'data-products', requiredLevel: FeatureAccessLevel.READ_ONLY, action: 'browse' },
      { featureId: 'concepts', requiredLevel: FeatureAccessLevel.READ_ONLY, action: 'browse' },

      // Govern
      { featureId: 'data-asset-reviews', requiredLevel: FeatureAccessLevel.READ_ONLY, action: 'review' },
      { featureId: 'entitlements', requiredLevel: FeatureAccessLevel.READ_ONLY, action: 'manage' },
      { featureId: 'compliance', requiredLevel: FeatureAccessLevel.READ_ONLY, action: 'monitor' },

      // Deploy
      { featureId: 'catalog-commander', requiredLevel: FeatureAccessLevel.READ_ONLY, action: 'open' },
      { featureId: 'estate-manager', requiredLevel: FeatureAccessLevel.READ_ONLY, action: 'manage' },
    ];

    actionMapping.forEach(({ featureId, requiredLevel, action }) => {
      const feature = features.find(f => f.id === featureId || f.permissionId === featureId);
      // Respect feature maturity gating the same way the sidebar navigation does,
      // so hidden-maturity features (e.g. alpha) never leak in as quick actions.
      if (
        feature &&
        allowedMaturities.includes(feature.maturity) &&
        hasPermission(feature.permissionId || feature.id, requiredLevel)
      ) {
        // Skip if we already added an action for this feature (prefer write actions)
        if (addedFeatures.has(featureId)) return;

        const actionName = action.charAt(0).toUpperCase() + action.slice(1);
        list.push({
          name: `${actionName} ${feature.name}`,
          path: feature.path,
          group: feature.group,
          featureId: feature.id,
        });
        addedFeatures.add(featureId);
      }
    });

    return list;
  }, [permissionsLoading, hasPermission, allowedMaturities]);

  // Group actions by feature group
  const groupedActions = useMemo(() => {
    const groups: { [key in FeatureGroup]?: QuickAction[] } = {};
    actions.forEach(action => {
      if (!groups[action.group]) {
        groups[action.group] = [];
      }
      groups[action.group]!.push(action);
    });
    return groups;
  }, [actions]);

  const groupOrder: FeatureGroup[] = ['Discover', 'Build', 'Govern', 'Deploy'];
  const visibleGroups = groupOrder.filter(group => groupedActions[group]?.length);

  if (permissionsLoading) {
    return (
      <div className="space-y-4 p-6">
        <SkeletonLine height="h-3" width="w-24" />
        <div className="grid grid-cols-2 gap-2">
          <SkeletonLine height="h-10" />
          <SkeletonLine height="h-10" />
          <SkeletonLine height="h-10" />
          <SkeletonLine height="h-10" />
        </div>
      </div>
    );
  }

  if (actions.length === 0) {
    return <div className="text-sm text-muted-foreground">{t('home:quickActions.noActions')}</div>;
  }

  return (
    <div className="space-y-4">
      {visibleGroups.map(groupName => (
        <div key={groupName}>
          <h4 className="text-xs font-semibold text-muted-foreground uppercase tracking-wider mb-2">
            {groupName}
          </h4>
          <div className="grid grid-cols-2 gap-2">
            {groupedActions[groupName]!.map((action) => (
              <Button
                key={action.name}
                variant="outline"
                size="sm"
                className="justify-start text-left h-auto py-2 px-3"
                asChild
              >
                <Link to={action.path}>
                  <span className="truncate text-xs">{action.name}</span>
                </Link>
              </Button>
            ))}
          </div>
        </div>
      ))}
    </div>
  );
}
