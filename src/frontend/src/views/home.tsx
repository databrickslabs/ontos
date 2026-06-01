import { useMemo } from 'react';
import { useTranslation } from 'react-i18next';
import SearchBar from '@/components/ui/search-bar';
import { AlertCircle } from 'lucide-react';
import { TileGridSkeleton } from '@/components/common/list-view-skeleton';
import { UnityCatalogLogo } from '@/components/unity-catalog-logo';
import { usePermissions } from '@/stores/permissions-store';
import { FeatureAccessLevel, HomeSection } from '@/types/settings';
import { Alert, AlertDescription } from "@/components/ui/alert";
import DiscoverySection from '@/components/home/discovery-section';
import DataCurationSection from '@/components/home/data-curation-section';
import RequiredActionsSection from '@/components/home/required-actions-section';
import RequestRoleSection from '@/components/home/request-role-section';
import QuickActions from '@/components/home/quick-actions';
import RecentActivity from '@/components/home/recent-activity';
import { useUserStore } from '@/stores/user-store';
import ConnectedOverviewTile from '@/components/home/connected-overview-tile';
import { tileRegistry, tileOrder } from '@/tiles';
import { Card, CardContent } from '@/components/ui/card';
import { useUICustomizationStore } from '@/stores/ui-customization-store';

export default function Home() {
  const { t } = useTranslation(['home', 'common']);
  const appName = useUICustomizationStore((s) => s.getAppName());
  const { permissions, isLoading: permissionsLoading, hasPermission, requestableRoles, appliedRoleId } = usePermissions();

  // Get available tiles based on permissions
  const availableTiles = useMemo(() => {
    if (permissionsLoading) return [];

    return tileOrder
      .map(id => tileRegistry[id])
      .filter(tile => hasPermission(tile.permission, tile.requiredLevel));
  }, [permissionsLoading, hasPermission, permissions, appliedRoleId]);

  const hasAnyAccess = useMemo(() => {
      if (permissionsLoading || !permissions) return false;
      return Object.values(permissions).some(level => level !== FeatureAccessLevel.NONE);
  }, [permissions, permissionsLoading]);

  const { availableRoles } = usePermissions();
  const { userInfo } = useUserStore();
  const userGroups = (userInfo as any)?.groups || [];

  const configuredSections: HomeSection[] = useMemo(() => {
    if (appliedRoleId) {
      const r = availableRoles.find(role => role.id === appliedRoleId);
      return (r?.home_sections || []) as HomeSection[];
    }
    if (Array.isArray(userGroups) && userGroups.length > 0) {
      const groupSet = new Set<string>(userGroups as string[]);
      const matched = availableRoles.filter(r => Array.isArray(r.assigned_groups) && r.assigned_groups.some(g => groupSet.has(g)));
      const union = new Set<HomeSection>();
      matched.forEach(r => (r.home_sections || []).forEach(s => union.add(s as HomeSection)));
      const order: HomeSection[] = [HomeSection.REQUIRED_ACTIONS, HomeSection.DATA_CURATION, HomeSection.DISCOVERY];
      const result = order.filter(s => union.has(s));
      return result.length > 0 ? result : [HomeSection.DISCOVERY];
    }
    return [];
  }, [availableRoles, appliedRoleId, userGroups]);

  const defaultSections: HomeSection[] = [HomeSection.DISCOVERY];
  const orderedSections = configuredSections.length > 0 ? configuredSections : defaultSections;

  return (
    <div className="container mx-auto px-4 py-8">
      {hasAnyAccess && (
        <>
          <div className="max-w-2xl mx-auto text-center mb-8">
            <div className="flex items-center justify-center mb-4">
              <UnityCatalogLogo className="h-16 w-16" />
              <h1 className="text-4xl font-bold ml-2">
                {t('home:title', { appName })}
              </h1>
            </div>
            <p className="text-lg text-muted-foreground mb-6">
              {t('home:tagline')}
            </p>
            <div className="mb-8">
              <SearchBar
                variant="large"
                placeholder={t('home:search.placeholder')}
              />
            </div>
          </div>

          {/* Overview Tiles */}
          <div className="mb-8">
            <h2 className="text-2xl font-semibold mb-4">{t('home:overview.title')}</h2>
            {permissionsLoading ? (
              <TileGridSkeleton count={8} columns={4} tileHeight="h-32" />
            ) : availableTiles.length > 0 ? (
              <div className="grid grid-cols-1 gap-4 md:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4">
                {availableTiles.map((tile) => (
                  <ConnectedOverviewTile key={tile.id} tile={tile} />
                ))}
              </div>
            ) : (
              <p className="text-muted-foreground text-center col-span-full">
                {t('home:overview.noData')}
              </p>
            )}
          </div>

          {/* My Actions */}
          <section className="mb-8">
            <h2 className="text-2xl font-semibold mb-4">My Actions</h2>
            <Card>
              <CardContent className="p-0">
                <div className="grid grid-cols-1 md:grid-cols-2 divide-y md:divide-y-0 md:divide-x">
                  {/* Approvals */}
                  <div className="flex flex-col h-[500px]">
                    <div className="px-6 py-4 border-b bg-muted/30">
                      <h3 className="font-semibold text-sm">Approvals</h3>
                    </div>
                    <div className="flex-1 overflow-hidden">
                      <RequiredActionsSection />
                    </div>
                  </div>

                  {/* Quick Actions */}
                  <div className="flex flex-col h-[500px]">
                    <div className="px-6 py-4 border-b bg-muted/30">
                      <h3 className="font-semibold text-sm">Quick Actions</h3>
                    </div>
                    <div className="flex-1 p-6 overflow-hidden">
                      <QuickActions />
                    </div>
                  </div>
                </div>
              </CardContent>
            </Card>
          </section>

          {/* Role-based sections */}
          {orderedSections.map(section => (
            section === HomeSection.REQUIRED_ACTIONS ? null :
            section === HomeSection.DATA_CURATION ? (
              <DataCurationSection key={section} />
            ) : (
              <DiscoverySection key={section} />
            )
          )).filter(Boolean)}

          {/* Recent Activity */}
          <section className="mb-8">
            <RecentActivity />
          </section>
        </>
      )}

      {/* Request Role Section */}
      {!permissionsLoading && !hasAnyAccess && requestableRoles && requestableRoles.length > 0 && (
        <div className="mb-8">
          <RequestRoleSection />
        </div>
      )}

      {/* No access fallback */}
      {!permissionsLoading && !hasAnyAccess && (!requestableRoles || requestableRoles.length === 0) && (
        <Alert variant="default" className="mb-8 bg-blue-50 border-blue-200 text-blue-800 dark:bg-blue-950 dark:border-blue-800 dark:text-blue-200">
          <AlertCircle className="h-4 w-4 !text-blue-600 dark:!text-blue-400" />
          <AlertDescription className="ml-2">
            {t('home:noAccess.message')} {t('home:noAccess.contactAdmin', 'Please contact an administrator to request access to the application.')}
          </AlertDescription>
        </Alert>
      )}
    </div>
  );
}
