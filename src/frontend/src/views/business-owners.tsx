import { useState, useEffect, useCallback, useMemo } from 'react';
import { ColumnDef } from '@tanstack/react-table';
import { AlertCircle, Users2, ChevronDown } from 'lucide-react';
import { ListViewSkeleton } from '@/components/common/list-view-skeleton';
import { Button } from '@/components/ui/button';
import { DataTable } from '@/components/ui/data-table';
import { Badge } from '@/components/ui/badge';
import { BusinessOwnerRead } from '@/types/business-owner';
import { useApi } from '@/hooks/use-api';
import { useToast } from '@/hooks/use-toast';
import { RelativeDate } from '@/components/common/relative-date';
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert';
import { usePermissions } from '@/stores/permissions-store';
import { FeatureAccessLevel } from '@/types/settings';
import useBreadcrumbStore from '@/stores/breadcrumb-store';
import { useTranslation } from 'react-i18next';

export default function BusinessOwnersView() {
  const [owners, setOwners] = useState<BusinessOwnerRead[]>([]);
  const [componentError, setComponentError] = useState<string | null>(null);

  const { t } = useTranslation(['business-owners', 'common']);
  const { get: apiGet, loading: apiIsLoading } = useApi();
  const { toast } = useToast();
  const { hasPermission, isLoading: permissionsLoading } = usePermissions();
  const setStaticSegments = useBreadcrumbStore((state) => state.setStaticSegments);
  const setDynamicTitle = useBreadcrumbStore((state) => state.setDynamicTitle);

  const featureId = 'business-owners';
  const canRead = !permissionsLoading && hasPermission(featureId, FeatureAccessLevel.READ_ONLY);

  const fetchOwners = useCallback(async () => {
    if (!canRead && !permissionsLoading) {
      setComponentError(t('permissions.deniedView'));
      return;
    }
    setComponentError(null);
    try {
      const response = await apiGet<BusinessOwnerRead[]>('/api/business-owners');
      if (response.error) throw new Error(response.error);
      setOwners(Array.isArray(response.data) ? response.data : []);
    } catch (err: any) {
      setComponentError(err.message || 'Failed to load business owners');
      setOwners([]);
      toast({ variant: 'destructive', title: t('messages.errorFetching'), description: err.message });
    }
  }, [canRead, permissionsLoading, apiGet, toast, t]);

  useEffect(() => {
    fetchOwners();
    setStaticSegments([]);
    setDynamicTitle(t('title'));
    return () => { setStaticSegments([]); setDynamicTitle(null); };
  }, [fetchOwners, setStaticSegments, setDynamicTitle, t]);

  const columns = useMemo<ColumnDef<BusinessOwnerRead>[]>(() => [
    {
      accessorKey: 'user_email',
      header: ({ column }) => (
        <Button variant="ghost" onClick={() => column.toggleSorting(column.getIsSorted() === 'asc')}>
          {t('table.owner')} <ChevronDown className="ml-2 h-4 w-4" />
        </Button>
      ),
      cell: ({ row }) => (
        <div>
          <span className="font-medium">{row.original.user_name || row.original.user_email}</span>
          {row.original.user_name && (
            <div className="text-xs text-muted-foreground">{row.original.user_email}</div>
          )}
        </div>
      ),
    },
    {
      accessorKey: 'role_name',
      header: t('table.role'),
      cell: ({ row }) => (
        <Badge variant="outline">{row.original.role_name || '-'}</Badge>
      ),
    },
    {
      accessorKey: 'object_type',
      header: t('table.objectType'),
      cell: ({ row }) => (
        <Badge variant="secondary">{t(`objectTypes.${row.original.object_type}`)}</Badge>
      ),
    },
    {
      accessorKey: 'object_id',
      header: t('table.object'),
      cell: ({ row }) => (
        <span className="text-sm text-muted-foreground font-mono truncate max-w-[200px] inline-block">
          {row.original.object_id}
        </span>
      ),
    },
    {
      id: 'status',
      header: t('table.status'),
      cell: ({ row }) => (
        <Badge variant={row.original.is_active ? 'default' : 'secondary'}>
          {row.original.is_active ? t('statusLabels.active') : t('statusLabels.inactive')}
        </Badge>
      ),
    },
    {
      accessorKey: 'assigned_at',
      header: ({ column }) => (
        <Button variant="ghost" onClick={() => column.toggleSorting(column.getIsSorted() === 'asc')}>
          {t('table.assignedAt')} <ChevronDown className="ml-2 h-4 w-4" />
        </Button>
      ),
      cell: ({ row }) => row.original.assigned_at
        ? <RelativeDate date={row.original.assigned_at} />
        : t('common:states.notAvailable'),
    },
  ], [t]);

  return (
    <div className="py-6">
      <div className="mb-6">
        <h1 className="text-3xl font-bold flex items-center gap-2">
          <Users2 className="w-8 h-8" />
          {t('title')}
        </h1>
        <p className="text-muted-foreground mt-1">{t('subtitle')}</p>
      </div>

      {(apiIsLoading || permissionsLoading) ? (
        <ListViewSkeleton columns={6} rows={5} toolbarButtons={0} />
      ) : !canRead ? (
        <Alert variant="destructive" className="mb-4">
          <AlertCircle className="h-4 w-4" />
          <AlertTitle>{t('permissions.permissionDenied')}</AlertTitle>
          <AlertDescription>{t('permissions.deniedView')}</AlertDescription>
        </Alert>
      ) : componentError ? (
        <Alert variant="destructive" className="mb-4">
          <AlertCircle className="h-4 w-4" />
          <AlertTitle>{t('messages.errorLoadingData')}</AlertTitle>
          <AlertDescription>{componentError}</AlertDescription>
        </Alert>
      ) : (
        <DataTable
          columns={columns}
          data={owners}
          searchColumn="user_email"
          storageKey="business-owners-sort"
        />
      )}
    </div>
  );
}
