import { useState, useEffect } from 'react';
import { usePermissions } from '@/stores/permissions-store';
import { FeatureAccessLevel } from '@/types/settings';
import { TileData } from '../types';

/** Overview-tile data for Authority Resolution: count of Active Authority Relations. */
export function useAuthorityResolutionData(): TileData {
  const { hasPermission, appliedRoleId, isLoading: permissionsLoading } = usePermissions();
  const [data, setData] = useState<TileData>({ value: 0, loading: true, error: null });

  useEffect(() => {
    if (permissionsLoading) return;

    if (!hasPermission('authority-resolution', FeatureAccessLevel.READ_ONLY)) {
      setData({ value: 0, loading: false, error: null, customData: { relations: [] } });
      return;
    }

    fetch('/api/authority/relations')
      .then((response) => {
        if (!response.ok) throw new Error(`HTTP ${response.status}`);
        return response.json();
      })
      .then((apiData) => {
        const relations = Array.isArray(apiData) ? apiData : [];
        const active = relations.filter((r: any) => (r.status || '').toLowerCase() === 'active').length;
        setData({ value: active, loading: false, error: null, customData: { relations } });
      })
      .catch((error) => {
        console.error('Error fetching authority relations:', error);
        setData({ value: 0, loading: false, error: error.message, customData: { relations: [] } });
      });
  }, [hasPermission, appliedRoleId, permissionsLoading]);

  return data;
}
