import { useState, useEffect, useCallback, useMemo } from 'react';
import { ColumnDef } from '@tanstack/react-table';
import { MoreHorizontal, PlusCircle, AlertCircle, Truck, ChevronDown, Loader2 } from 'lucide-react';
import { ListViewSkeleton } from '@/components/common/list-view-skeleton';
import { Button } from '@/components/ui/button';
import { DataTable } from '@/components/ui/data-table';
import { Badge } from '@/components/ui/badge';
import { DeliveryMethodRead } from '@/types/delivery-method';
import { useApi } from '@/hooks/use-api';
import { useToast } from '@/hooks/use-toast';
import { RelativeDate } from '@/components/common/relative-date';
import {
  DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuLabel, DropdownMenuSeparator, DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu';
import {
  AlertDialog, AlertDialogAction, AlertDialogCancel, AlertDialogContent, AlertDialogDescription,
  AlertDialogFooter, AlertDialogHeader, AlertDialogTitle,
} from '@/components/ui/alert-dialog';
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert';
import { usePermissions } from '@/stores/permissions-store';
import { FeatureAccessLevel } from '@/types/settings';
import SettingsPageWrapper from '@/components/settings/settings-page-wrapper';
import { useTranslation } from 'react-i18next';
import { DeliveryMethodFormDialog } from '@/components/delivery-methods/delivery-method-form-dialog';

export default function DeliveryMethodsView() {
  const [methods, setMethods] = useState<DeliveryMethodRead[]>([]);
  const [isDeleteDialogOpen, setIsDeleteDialogOpen] = useState(false);
  const [deletingId, setDeletingId] = useState<string | null>(null);
  const [componentError, setComponentError] = useState<string | null>(null);
  const [isFormOpen, setIsFormOpen] = useState(false);
  const [editingMethod, setEditingMethod] = useState<DeliveryMethodRead | null>(null);

  const { t } = useTranslation(['delivery-methods', 'common']);
  const { get: apiGet, delete: apiDelete, loading: apiIsLoading } = useApi();
  const { toast } = useToast();
  const { hasPermission, isLoading: permissionsLoading } = usePermissions();

  const featureId = 'delivery-methods';
  const canRead = !permissionsLoading && hasPermission(featureId, FeatureAccessLevel.READ_ONLY);
  const canWrite = !permissionsLoading && hasPermission(featureId, FeatureAccessLevel.READ_WRITE);
  const canAdmin = !permissionsLoading && hasPermission(featureId, FeatureAccessLevel.ADMIN);

  const fetchMethods = useCallback(async () => {
    if (!canRead && !permissionsLoading) {
      setComponentError(t('permissions.deniedView'));
      return;
    }
    setComponentError(null);
    try {
      const response = await apiGet<DeliveryMethodRead[]>('/api/delivery-methods');
      if (response.error) throw new Error(response.error);
      setMethods(Array.isArray(response.data) ? response.data : []);
    } catch (err: any) {
      setComponentError(err.message || 'Failed to load delivery methods');
      setMethods([]);
      toast({ variant: 'destructive', title: t('messages.errorFetching'), description: err.message });
    }
  }, [canRead, permissionsLoading, apiGet, toast, t]);

  useEffect(() => {
    fetchMethods();
  }, [fetchMethods]);

  const openDeleteDialog = (id: string) => {
    if (!canAdmin) {
      toast({ variant: 'destructive', title: t('permissions.permissionDenied'), description: t('permissions.deniedDelete') });
      return;
    }
    setDeletingId(id);
    setIsDeleteDialogOpen(true);
  };

  const handleDeleteConfirm = async () => {
    if (!deletingId || !canAdmin) return;
    try {
      const response = await apiDelete(`/api/delivery-methods/${deletingId}`);
      if (response.error) throw new Error(response.error);
      toast({ title: t('messages.deleted'), description: t('messages.deletedSuccess') });
      fetchMethods();
    } catch (err: any) {
      toast({ variant: 'destructive', title: t('messages.errorDeleting'), description: err.message });
    } finally {
      setIsDeleteDialogOpen(false);
      setDeletingId(null);
    }
  };

  const columns = useMemo<ColumnDef<DeliveryMethodRead>[]>(() => [
    {
      accessorKey: 'name',
      header: ({ column }) => (
        <Button variant="ghost" onClick={() => column.toggleSorting(column.getIsSorted() === 'asc')}>
          {t('table.name')} <ChevronDown className="ml-2 h-4 w-4" />
        </Button>
      ),
      cell: ({ row }) => (
        <div>
          <span className="font-medium">{row.original.name}</span>
          {row.original.is_system && (
            <Badge variant="outline" className="ml-2 text-xs">System</Badge>
          )}
        </div>
      ),
    },
    {
      accessorKey: 'description',
      header: t('table.description'),
      cell: ({ row }) => (
        <div className="truncate max-w-sm text-sm text-muted-foreground">
          {row.original.description || '-'}
        </div>
      ),
    },
    {
      accessorKey: 'category',
      header: t('table.category'),
      cell: ({ row }) => row.original.category
        ? <Badge variant="outline">{t(`categories.${row.original.category}`)}</Badge>
        : '-',
    },
    {
      accessorKey: 'status',
      header: t('table.status'),
      cell: ({ row }) => (
        <Badge variant={row.original.status === 'active' ? 'default' : 'secondary'}>
          {t(`statuses.${row.original.status}`)}
        </Badge>
      ),
    },
    {
      accessorKey: 'updated_at',
      header: ({ column }) => (
        <Button variant="ghost" onClick={() => column.toggleSorting(column.getIsSorted() === 'asc')}>
          {t('table.lastUpdated')} <ChevronDown className="ml-2 h-4 w-4" />
        </Button>
      ),
      cell: ({ row }) => row.original.updated_at
        ? <RelativeDate date={row.original.updated_at} />
        : t('common:states.notAvailable'),
    },
    {
      id: 'actions',
      header: t('table.actions'),
      cell: ({ row }) => (
        <DropdownMenu>
          <DropdownMenuTrigger asChild>
            <Button variant="ghost" className="h-8 w-8 p-0">
              <span className="sr-only">Open menu</span>
              <MoreHorizontal className="h-4 w-4" />
            </Button>
          </DropdownMenuTrigger>
          <DropdownMenuContent align="end">
            <DropdownMenuLabel>{t('table.actions')}</DropdownMenuLabel>
            <DropdownMenuItem disabled={!canWrite} onClick={() => { setEditingMethod(row.original); setIsFormOpen(true); }}>{t('editMethod')}</DropdownMenuItem>
            <DropdownMenuSeparator />
            <DropdownMenuItem
              onClick={() => openDeleteDialog(row.original.id)}
              className="text-red-600 focus:text-red-600 focus:bg-red-50 dark:text-red-400 dark:focus:text-red-400 dark:focus:bg-red-950"
              disabled={!canAdmin}
            >
              {t('deleteMethod')}
            </DropdownMenuItem>
          </DropdownMenuContent>
        </DropdownMenu>
      ),
    },
  ], [canWrite, canAdmin, t]);

  return (
    <SettingsPageWrapper title={t('title')} permissionId="settings-delivery-methods">
      <div className="mb-6">
        <h1 className="text-3xl font-bold flex items-center gap-2">
          <Truck className="w-8 h-8" />
          {t('title')}
        </h1>
        <p className="text-muted-foreground mt-1">{t('subtitle')}</p>
      </div>

      {(apiIsLoading || permissionsLoading) ? (
        <ListViewSkeleton columns={4} rows={5} toolbarButtons={1} />
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
          data={methods}
          searchColumn="name"
          storageKey="delivery-methods-sort"
          toolbarActions={
            <Button onClick={() => { setEditingMethod(null); setIsFormOpen(true); }} disabled={!canWrite || apiIsLoading} className="h-9">
              <PlusCircle className="mr-2 h-4 w-4" /> {t('addNew')}
            </Button>
          }
        />
      )}

      <DeliveryMethodFormDialog
        isOpen={isFormOpen}
        onOpenChange={setIsFormOpen}
        method={editingMethod}
        onSubmitSuccess={fetchMethods}
      />

      <AlertDialog open={isDeleteDialogOpen} onOpenChange={setIsDeleteDialogOpen}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>{t('deleteDialog.title')}</AlertDialogTitle>
            <AlertDialogDescription>{t('deleteDialog.description')}</AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel onClick={() => setDeletingId(null)}>{t('deleteDialog.cancel')}</AlertDialogCancel>
            <AlertDialogAction onClick={handleDeleteConfirm} className="bg-red-600 hover:bg-red-700" disabled={apiIsLoading}>
              {apiIsLoading ? <Loader2 className="mr-2 h-4 w-4 animate-spin" /> : null} {t('deleteDialog.delete')}
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </SettingsPageWrapper>
  );
}
