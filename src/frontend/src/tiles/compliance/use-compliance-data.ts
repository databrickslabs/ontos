import { useState, useEffect } from 'react';
import { usePermissions } from '@/stores/permissions-store';
import { FeatureAccessLevel } from '@/types/settings';
import { TileData } from '../types';
import { useTranslation } from 'react-i18next';

export function useComplianceData(): TileData {
  const { t } = useTranslation(['home', 'compliance']);
  const { hasPermission, appliedRoleId, isLoading: permissionsLoading } = usePermissions();
  const [data, setData] = useState<TileData>({
    value: t('home:overview.tiles.compliance.notAvailable'),
    loading: true,
    error: null,
  });

  useEffect(() => {
    // Don't fetch while permissions are loading
    if (permissionsLoading) {
      return;
    }

    if (!hasPermission('compliance', FeatureAccessLevel.READ_ONLY)) {
      setData({
        value: t('home:overview.tiles.compliance.notAvailable'),
        loading: false,
        error: null,
        customData: {
          trendData: undefined,
        },
      });
      return;
    }

    const getJson = (url: string) => fetch(url).then(response => {
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      return response.json();
    });
    // The value is the Compliance page's overall score (#1617): the latest
    // trend day is often a day without runs yet. The trend feeds the sparkline.
    Promise.all([getJson('/api/compliance/policies'), getJson('/api/compliance/trend')])
      .then(([policiesData, trendData]) => {
        const complianceArray = Array.isArray(trendData) ? trendData : [];
        const overall = policiesData?.stats?.overall_compliance;
        // null: no policy has a score yet. "No score", never 0 %
        const score: number | null = typeof overall === 'number' ? overall : null;
        const hasPolicies = (policiesData?.stats?.active_policies ?? 0) > 0;

        setData({
          value: score !== null
            ? `${Math.round(score)}%`
            : hasPolicies || complianceArray.length > 0
              ? t('compliance:runScoreCoverage.noScore')
              : t('home:overview.tiles.compliance.notAvailable'),
          loading: false,
          error: null,
          customData: {
            trendData: complianceArray.map((d: any) => d.compliance ?? null),
          },
        });
      })
      .catch(error => {
        console.error('Error fetching compliance data:', error);
        setData({
          value: t('home:overview.tiles.compliance.notAvailable'),
          loading: false,
          error: error.message,
          customData: {
            trendData: undefined,
          },
        });
      });
  }, [hasPermission, appliedRoleId, permissionsLoading, t]);

  return data;
}
