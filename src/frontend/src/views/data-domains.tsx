import { useState, useEffect, useCallback, useMemo } from 'react';
import { ColumnDef } from '@tanstack/react-table';
import { MoreHorizontal, PlusCircle, AlertCircle, BoxSelect, TableIcon, WorkflowIcon, Loader2, ChevronDown, Eye } from 'lucide-react';
import { ListViewSkeleton } from '@/components/common/list-view-skeleton';
import { Button } from "@/components/ui/button";
import { DataTable } from "@/components/ui/data-table";
import { DataDomain, DomainDeletionImpact } from '@/types/data-domain';
import { useApi } from '@/hooks/use-api';
import { useToast } from "@/hooks/use-toast";
import { DataDomainFormDialog } from '@/components/data-domains/data-domain-form-dialog';
import { RelativeDate } from '@/components/common/relative-date';
import {
    DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuLabel, DropdownMenuSeparator, DropdownMenuTrigger
} from "@/components/ui/dropdown-menu";
import {
    AlertDialog, AlertDialogAction, AlertDialogCancel, AlertDialogContent, AlertDialogDescription, AlertDialogFooter, AlertDialogHeader, AlertDialogTitle
} from "@/components/ui/alert-dialog";
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert';

import TagChip from '@/components/ui/tag-chip';
import { usePermissions } from '@/stores/permissions-store';
import { FeatureAccessLevel } from '@/types/settings';
import { Toaster } from "@/components/ui/toaster";
import SettingsPageWrapper from '@/components/settings/settings-page-wrapper';
import { useNavigate, useLocation } from 'react-router-dom';
import DataDomainGraphView from '@/components/data-domains/data-domain-graph-view';
import { ViewModeToggle } from '@/components/common/view-mode-toggle';
import { useProjectContext } from '@/stores/project-store';
import { useTranslation } from 'react-i18next';
import EntityInfoDialog from '@/components/metadata/entity-info-dialog';

// Placeholder for Graph View
// const DataDomainGraphViewPlaceholder = () => (
//   <div className="border rounded-lg p-8 text-center text-muted-foreground h-[calc(100vh-280px)] flex flex-col items-center justify-center">
//     <ListTree className="w-16 h-16 mb-4" />
//     <p className="text-lg font-semibold">Data Domain Graph View</p>
//     <p>This feature is under construction. Hierarchical relationships will be visualized here.</p>
//   </div>
// );

// Check API response helper (adjusted for nullable error)
const checkApiResponse = <T,>(response: { data?: T | { detail?: string }, error?: string | null | undefined }, name: string): T => {
    if (response.error) throw new Error(`${name} fetch failed: ${response.error}`);
    // Check if data exists, is an object, and has a 'detail' property that is a string
    if (response.data && typeof response.data === 'object' && response.data !== null && 'detail' in response.data && typeof (response.data as { detail: string }).detail === 'string') {
        throw new Error(`${name} fetch failed: ${(response.data as { detail: string }).detail}`);
    }
    if (response.data === null || response.data === undefined) throw new Error(`${name} fetch returned null or undefined data.`);
    return response.data as T;
};

export default function DataDomainsView() {
  const [domains, setDomains] = useState<DataDomain[]>([]);
  const [isFormOpen, setIsFormOpen] = useState(false);
  const [editingDomain, setEditingDomain] = useState<DataDomain | null>(null);
  const [isDeleteDialogOpen, setIsDeleteDialogOpen] = useState(false);
  const [deletingDomainId, setDeletingDomainId] = useState<string | null>(null);
  const [deletionImpact, setDeletionImpact] = useState<DomainDeletionImpact | null>(null);
  const [componentError, setComponentError] = useState<string | null>(null);
  const [viewMode, setViewMode] = useState<'table' | 'graph'>('table');
  const [previewDomainId, setPreviewDomainId] = useState<string | null>(null);
  const [previewDomainTitle, setPreviewDomainTitle] = useState('');

  const { get: apiGet, delete: apiDelete, loading: apiIsLoading } = useApi();
  const { toast } = useToast();
  const navigate = useNavigate();
  const { pathname } = useLocation();
  const { hasPermission, isLoading: permissionsLoading } = usePermissions();
  const { currentProject, hasProjectContext } = useProjectContext();
  const { t } = useTranslation(['data-domains', 'common']);

  const featureId = 'data-domains';
  const canRead = !permissionsLoading && hasPermission(featureId, FeatureAccessLevel.READ_ONLY);
  const canWrite = !permissionsLoading && hasPermission(featureId, FeatureAccessLevel.READ_WRITE);
  const canAdmin = !permissionsLoading && hasPermission(featureId, FeatureAccessLevel.ADMIN);

  const fetchDataDomains = useCallback(async () => {
    if (!canRead && !permissionsLoading) {
        setComponentError(t('permissions.deniedView'));
        return;
    }
    setComponentError(null);
    try {
      // Build URL with project context if available
      let endpoint = '/api/data-domains';
      if (hasProjectContext && currentProject) {
        endpoint += `?project_id=${currentProject.id}`;
      }

      const response = await apiGet<DataDomain[]>(endpoint);
      const data = checkApiResponse(response, 'Data Domains');
      const domainsData = Array.isArray(data) ? data : [];
      setDomains(domainsData);
      if (response.error) {
        setComponentError(response.error);
        setDomains([]);
        toast({ variant: "destructive", title: t('messages.errorFetchingDomains'), description: response.error });
      }
    } catch (err: any) {
      setComponentError(err.message || 'Failed to load data domains');
      setDomains([]);
      toast({ variant: "destructive", title: t('messages.errorFetchingDomains'), description: err.message });
    }
  }, [canRead, permissionsLoading, apiGet, toast, setComponentError, hasProjectContext, currentProject, t]);

  useEffect(() => {
    fetchDataDomains();
  }, [fetchDataDomains]);

  const handleOpenCreateDialog = () => {
    if (!canWrite) {
        toast({ variant: "destructive", title: t('permissions.permissionDenied'), description: t('permissions.deniedCreate') });
        return;
    }
    setEditingDomain(null);
    setIsFormOpen(true);
  };

  const handleOpenEditDialog = (domain: DataDomain) => {
    if (!canWrite) {
        toast({ variant: "destructive", title: t('permissions.permissionDenied'), description: t('permissions.deniedEdit') });
        return;
    }
    setEditingDomain(domain);
    setIsFormOpen(true);
  };

  const handleFormSubmitSuccess = (_savedDomain: DataDomain) => {
    fetchDataDomains();
  };

  const openDeleteDialog = (domainId: string) => {
    if (!canAdmin) {
         toast({ variant: "destructive", title: t('permissions.permissionDenied'), description: t('permissions.deniedDelete') });
         return;
    }
    setDeletingDomainId(domainId);
    setDeletionImpact(null);
    setIsDeleteDialogOpen(true);
    // Pre-check whether the domain can be deleted (#520): blocked if it (or a
    // descendant that cascade-deletes with it) is any entity's primary domain.
    apiGet<DomainDeletionImpact>(`/api/data-domains/${domainId}/deletion-impact`)
      .then((resp) => {
        if (resp.data && !resp.error) setDeletionImpact(resp.data);
      })
      .catch((e) => console.error('Failed to load domain deletion impact:', e));
  };

  const handleDeleteConfirm = async () => {
    if (!deletingDomainId || !canAdmin) return;
    try {
      const response = await apiDelete(`/api/data-domains/${deletingDomainId}`);
      if (response.error) {
        let errorMessage = response.error;
        // The delete-block 409 (#520) returns a structured `detail` object; surface its message.
        if (response.data && typeof response.data === 'object' && response.data !== null && 'detail' in response.data) {
            const detail = (response.data as { detail: unknown }).detail;
            if (typeof detail === 'string') {
                errorMessage = detail;
            } else if (detail && typeof detail === 'object' && 'message' in detail && typeof (detail as { message: string }).message === 'string') {
                errorMessage = (detail as { message: string }).message;
            }
        }
        throw new Error(errorMessage || 'Failed to delete domain.');
      }
      toast({ title: t('messages.domainDeleted'), description: t('messages.domainDeletedSuccess') });
      fetchDataDomains();
    } catch (err: any) {
       toast({ variant: "destructive", title: t('messages.errorDeletingDomain'), description: err.message || 'Failed to delete domain.' });
       setComponentError(err.message || 'Failed to delete domain.');
    } finally {
       setIsDeleteDialogOpen(false);
       setDeletingDomainId(null);
    }
  };

  const handleNavigateToDomain = (domainId: string) => {
    navigate(`/settings/data-domains/${domainId}`);
  };

  const columns = useMemo<ColumnDef<DataDomain>[]>(() => [
    {
      accessorKey: "name",
      header: ({ column }) => (
        <Button variant="ghost" onClick={() => column.toggleSorting(column.getIsSorted() === "asc")}>
          {t('table.name')}
          <ChevronDown className="ml-2 h-4 w-4" />
        </Button>
      ),
      cell: ({ row }) => {
        const domain = row.original;
        return (
          <div>
            <span
              className="font-medium cursor-pointer hover:underline"
              onClick={() => handleNavigateToDomain(domain.id)}
            >
              {domain.name}
            </span>
            {domain.parent_name && (
              <div
                className="text-xs text-muted-foreground cursor-pointer hover:underline"
                onClick={(e) => {
                    e.stopPropagation();
                    if (domain.parent_id) handleNavigateToDomain(domain.parent_id);
                }}
              >
                {t('table.parentPrefix')} {domain.parent_name}
              </div>
            )}
          </div>
        );
      },
    },
    {
      accessorKey: "description",
      header: ({ column }) => (
        <Button variant="ghost" onClick={() => column.toggleSorting(column.getIsSorted() === "asc")}>
          {t('table.description')}
          <ChevronDown className="ml-2 h-4 w-4" />
        </Button>
      ),
      cell: ({ row }) => (
        <div className="truncate max-w-sm text-sm text-muted-foreground">
          {row.getValue("description") || '-'}
        </div>
      ),
    },
    {
      accessorKey: "tags",
      header: t('table.tags'),
      cell: ({ row }) => {
        const tags = row.original.tags;
        if (!tags || tags.length === 0) return '-' ;
        return (
            <div className="flex flex-wrap gap-1">
                {tags.map((tag, index) => (
                    <TagChip key={index} tag={tag} size="sm" />
                ))}
            </div>
        );
      }
    },
    {
        accessorKey: "children_count",
        header: ({ column }) => (
          <Button variant="ghost" onClick={() => column.toggleSorting(column.getIsSorted() === "asc")}>
            {t('table.children')}
            <ChevronDown className="ml-2 h-4 w-4" />
          </Button>
        ),
        cell: ({ row }) => row.original.children_count ?? 0,
    },
    {
      accessorKey: "updated_at",
      header: ({ column }) => (
        <Button variant="ghost" onClick={() => column.toggleSorting(column.getIsSorted() === "asc")}>
          {t('table.lastUpdated')}
          <ChevronDown className="ml-2 h-4 w-4" />
        </Button>
      ),
      cell: ({ row }) => {
         const dateValue = row.getValue("updated_at");
         return dateValue ? <RelativeDate date={dateValue as string | Date | number} /> : t('common:states.notAvailable');
      },
    },
    {
      id: "actions",
      cell: ({ row }) => {
        const domain = row.original;
        return (
          <DropdownMenu>
            <DropdownMenuTrigger asChild>
              <Button variant="ghost" className="h-8 w-8 p-0">
                <span className="sr-only">Open menu</span>
                <MoreHorizontal className="h-4 w-4" />
              </Button>
            </DropdownMenuTrigger>
            <DropdownMenuContent align="end">
              <DropdownMenuLabel>{t('table.actions')}</DropdownMenuLabel>
              <DropdownMenuItem onClick={() => handleNavigateToDomain(domain.id)}>
                {t('viewDetails')}
              </DropdownMenuItem>
              <DropdownMenuItem onClick={() => { setPreviewDomainId(domain.id ?? null); setPreviewDomainTitle(domain.name ?? ''); }}>
                <Eye className="mr-2 h-4 w-4" /> Preview metadata
              </DropdownMenuItem>
              <DropdownMenuItem onClick={() => handleOpenEditDialog(domain)} disabled={!canWrite}>
                {t('editDomain')}
              </DropdownMenuItem>
              <DropdownMenuSeparator />
              <DropdownMenuItem
                onClick={() => openDeleteDialog(domain.id)}
                className="text-red-600 focus:text-red-600 focus:bg-red-50 dark:text-red-400 dark:focus:text-red-400 dark:focus:bg-red-950"
                disabled={!canAdmin}
              >
                {t('deleteDomain')}
              </DropdownMenuItem>
            </DropdownMenuContent>
          </DropdownMenu>
        );
      },
    },
  ], [canWrite, canAdmin, navigate, pathname, t]);

  return (
    <SettingsPageWrapper title={t('title')} permissionId="data-domains">
      <div className="mb-6">
        <h1 className="text-3xl font-bold flex items-center gap-2">
           <BoxSelect className="w-8 h-8" />
           {t('title')}
        </h1>
        <p className="text-muted-foreground mt-1">{t('subtitle')}</p>
      </div>

      {(apiIsLoading || permissionsLoading) ? (
        <ListViewSkeleton columns={6} rows={5} toolbarButtons={1} />
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
        <div className="space-y-4">
          <div className="flex items-center justify-end">
            <ViewModeToggle
              currentView={viewMode}
              onViewChange={setViewMode}
              tableViewIcon={<TableIcon className="h-4 w-4" />}
              graphViewIcon={<WorkflowIcon className="h-4 w-4" />}
            />
          </div>

          {viewMode === 'table' ? (
            <>
              <DataTable
                columns={columns}
                data={domains}
                searchColumn="name"
                storageKey="data-domains-sort"
                toolbarActions={
                  <Button onClick={handleOpenCreateDialog} disabled={!canWrite || permissionsLoading || apiIsLoading} className="h-9">
                    <PlusCircle className="mr-2 h-4 w-4" /> {t('addNewDomain')}
                  </Button>
                }
              />
              <DataDomainFormDialog
                isOpen={isFormOpen}
                onOpenChange={setIsFormOpen}
                domain={editingDomain}
                onSubmitSuccess={handleFormSubmitSuccess}
                allDomains={domains}
              />
            </>
          ) : (
            <DataDomainGraphView domains={domains} />
          )}
        </div>
      )}

      <EntityInfoDialog
        entityType="data_domain"
        entityId={previewDomainId}
        open={!!previewDomainId}
        onOpenChange={(o) => { if (!o) setPreviewDomainId(null); }}
        title={previewDomainTitle}
      />

      <AlertDialog open={isDeleteDialogOpen} onOpenChange={setIsDeleteDialogOpen}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>{t('deleteDialog.title')}</AlertDialogTitle>
            <AlertDialogDescription>
              {t('deleteDialog.description')}
            </AlertDialogDescription>
          </AlertDialogHeader>
          {deletionImpact && !deletionImpact.deletable && (
            <div className="rounded-md border border-red-300 bg-red-50 dark:bg-red-950/30 p-3 text-sm text-red-800 dark:text-red-300">
              <p className="font-medium">This domain can't be deleted.</p>
              <p className="mt-1">
                It is the primary domain for {deletionImpact.primary_assignments.length} entity assignment(s):
              </p>
              <ul className="mt-1 list-disc list-inside">
                {Object.entries(deletionImpact.assignment_counts)
                  .filter(([, counts]) => counts.primary > 0)
                  .map(([entityType, counts]) => (
                    <li key={entityType}>
                      {counts.primary} {entityType.replace(/_/g, ' ')}(s)
                    </li>
                  ))}
              </ul>
              <p className="mt-1">Reassign those to a different primary domain first.</p>
            </div>
          )}
          <AlertDialogFooter>
            <AlertDialogCancel onClick={() => { setDeletingDomainId(null); setDeletionImpact(null); }}>{t('deleteDialog.cancel')}</AlertDialogCancel>
            <AlertDialogAction
              onClick={handleDeleteConfirm}
              className="bg-red-600 hover:bg-red-700"
              disabled={apiIsLoading || permissionsLoading || (deletionImpact !== null && !deletionImpact.deletable)}
            >
               {(apiIsLoading || permissionsLoading) ? <Loader2 className="mr-2 h-4 w-4 animate-spin" /> : null} {t('deleteDialog.delete')}
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>

      <Toaster />
    </SettingsPageWrapper>
  );
}