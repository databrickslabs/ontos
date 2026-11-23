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

    fetch('/api/compliance/trend')
      .then(response => {
        if (!response.ok) throw new Error(`HTTP ${response.status}`);
        return response.json();
      })
      .then(apiData => {
        const complianceArray = Array.isArray(apiData) ? apiData : [];
        // A day without a scored run has compliance null: "No score", never 0 %
        const latestCompliance: number | null = complianceArray.length > 0
          ? complianceArray[complianceArray.length - 1].compliance ?? null
          : null;

        setData({
          value: latestCompliance !== null
            ? `${latestCompliance}%`
            : complianceArray.length > 0
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
