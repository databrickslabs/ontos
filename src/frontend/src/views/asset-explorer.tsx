import { useState, useEffect, useCallback, useMemo } from 'react';
import { useNavigate, useSearchParams } from 'react-router-dom';
import { ColumnDef, RowSelectionState, PaginationState } from '@tanstack/react-table';
import {
  Box, ChevronDown, MoreHorizontal, PlusCircle, AlertCircle, Trash2,
  Table2, Eye, Columns2, LayoutDashboard, Globe, FileCode, Brain, Activity,
  Server, Shield, BookOpen, Database, FolderOpen, Shapes, FileSpreadsheet, FileInput,
} from 'lucide-react';
import { ListViewSkeleton } from '@/components/common/list-view-skeleton';
import { Button } from '@/components/ui/button';
import { DataTable } from '@/components/ui/data-table';
import { Badge } from '@/components/ui/badge';
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from '@/components/ui/tooltip';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { ScrollArea } from '@/components/ui/scroll-area';
import { Separator } from '@/components/ui/separator';
import { AssetRead, AssetTypeRead } from '@/types/asset';
import { EntityTypeDefinition } from '@/types/ontology-schema';
import { AssetFormDialog } from '@/components/common/asset-form-dialog';
import EntityInfoDialog from '@/components/metadata/entity-info-dialog';
import AssetImportExportDialog from '@/components/assets/asset-import-export-dialog';
import { AssetDeleteDialog } from '@/components/assets/asset-delete-dialog';
import { useApi } from '@/hooks/use-api';
import { useToast } from '@/hooks/use-toast';
import { RelativeDate } from '@/components/common/relative-date';
import {
  DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuLabel,
  DropdownMenuSeparator, DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu';
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert';
import { usePermissions } from '@/stores/permissions-store';
import { FeatureAccessLevel } from '@/types/settings';
import useBreadcrumbStore from '@/stores/breadcrumb-store';
import { cn } from '@/lib/utils';

const ICON_MAP: Record<string, React.ElementType> = {
  Table2, Eye, Columns2, LayoutDashboard, Globe, FileCode, Brain, Activity,
  Server, Shield, BookOpen, Database, FolderOpen, Shapes, Box,
};

const CATEGORY_META: Record<string, { label: string; icon: React.ElementType; order: number }> = {
  data: { label: 'Data Assets', icon: Database, order: 1 },
  analytics: { label: 'Analytics', icon: LayoutDashboard, order: 2 },
  integration: { label: 'Integration', icon: Globe, order: 3 },
  system: { label: 'Systems', icon: Server, order: 4 },
  custom: { label: 'Custom', icon: Shapes, order: 5 },
};

const STATUS_VARIANT: Record<string, 'default' | 'secondary' | 'outline' | 'destructive'> = {
  draft: 'outline',
  active: 'default',
  deprecated: 'secondary',
  archived: 'destructive',
};

function getIconComponent(iconName?: string | null): React.ElementType {
  if (!iconName) return Box;
  return ICON_MAP[iconName] || Box;
}

export default function AssetExplorerView() {
  const [assetTypes, setAssetTypes] = useState<AssetTypeRead[]>([]);
  const [assets, setAssets] = useState<AssetRead[]>([]);
  const [selectedTypeId, setSelectedTypeId] = useState<string | null>(null);
  const [isDeleteDialogOpen, setIsDeleteDialogOpen] = useState(false);
  const [deletingId, setDeletingId] = useState<string | null>(null);
  const [componentError, setComponentError] = useState<string | null>(null);
  const [assetsLoading, setAssetsLoading] = useState(false);
  const [isFormOpen, setIsFormOpen] = useState(false);
  const [editingAsset, setEditingAsset] = useState<AssetRead | null>(null);
  const [ontologyTypes, setOntologyTypes] = useState<EntityTypeDefinition[]>([]);
  const [isImportExportOpen, setIsImportExportOpen] = useState(false);
  const [rowSelection, setRowSelection] = useState<RowSelectionState>({});
  const [assetsTotal, setAssetsTotal] = useState(0);
  const [pagination, setPagination] = useState<PaginationState>({ pageIndex: 0, pageSize: 10 });
  const [nameFilter, setNameFilter] = useState('');
  const [debouncedNameFilter, setDebouncedNameFilter] = useState('');
  const [previewAssetId, setPreviewAssetId] = useState<string | null>(null);
  const [previewAssetTitle, setPreviewAssetTitle] = useState('');

  const navigate = useNavigate();
  const [searchParams, setSearchParams] = useSearchParams();
  const { get: apiGet, delete: apiDelete, loading: apiIsLoading } = useApi();
  const { toast } = useToast();
  const { hasPermission, isLoading: permissionsLoading } = usePermissions();
  const setStaticSegments = useBreadcrumbStore((state) => state.setStaticSegments);
  const setDynamicTitle = useBreadcrumbStore((state) => state.setDynamicTitle);

  const featureId = 'assets';
  const canRead = !permissionsLoading && hasPermission(featureId, FeatureAccessLevel.READ_ONLY);
  const canWrite = !permissionsLoading && hasPermission(featureId, FeatureAccessLevel.READ_WRITE);
  const canAdmin = !permissionsLoading && hasPermission(featureId, FeatureAccessLevel.ADMIN);

  const selectedAssetIds = useMemo(() => Object.keys(rowSelection), [rowSelection]);
  const hasSelection = selectedAssetIds.length > 0;

  const selectType = useCallback((typeId: string | null, typeName?: string) => {
    setSelectedTypeId(typeId);
    setSearchParams((prev) => {
      const next = new URLSearchParams(prev);
      if (typeId && typeName) {
        next.set('type', typeName);
      } else {
        next.delete('type');
      }
      return next;
    }, { replace: true });
  }, [setSearchParams]);

  const fetchAssetTypes = useCallback(async () => {
    if (!canRead && !permissionsLoading) return;
    try {
      const response = await apiGet<AssetTypeRead[]>('/api/asset-types');
      if (response.error) throw new Error(response.error);
      const types = Array.isArray(response.data) ? response.data : [];
      setAssetTypes(types);
      if (selectedTypeId === null && types.length > 0) {
        const urlType = searchParams.get('type');
        if (urlType) {
          const match = types.find(t => t.name === urlType);
          if (match) setSelectedTypeId(match.id);
        }
      }
    } catch (err: any) {
      setComponentError(err.message || 'Failed to load asset types');
      toast({ variant: 'destructive', title: 'Error', description: err.message });
    }
  }, [canRead, permissionsLoading, apiGet, toast, searchParams, selectedTypeId]);

  interface PaginatedResponse {
    items: AssetRead[];
    total: number;
    skip: number;
    limit: number;
  }

  const fetchAssets = useCallback(async (typeId: string | null, page: PaginationState, nameSearch?: string) => {
    setAssetsLoading(true);
    try {
      const skip = page.pageIndex * page.pageSize;
      const params = new URLSearchParams({ skip: String(skip), limit: String(page.pageSize) });
      if (typeId) params.set('asset_type_id', typeId);
      if (nameSearch) params.set('name', nameSearch);
      const response = await apiGet<PaginatedResponse>(`/api/assets?${params}`);
      if (response.error) throw new Error(response.error);
      const data = response.data;
      setAssets(data?.items ?? []);
      setAssetsTotal(data?.total ?? 0);
    } catch (err: any) {
      setAssets([]);
      setAssetsTotal(0);
      toast({ variant: 'destructive', title: 'Error loading assets', description: err.message });
    } finally {
      setAssetsLoading(false);
    }
  }, [apiGet, toast]);

  const fetchOntologyTypes = useCallback(async () => {
    try {
      const response = await apiGet<EntityTypeDefinition[]>('/api/ontology/entity-types?tier=asset');
      if (!response.error && Array.isArray(response.data)) {
        setOntologyTypes(response.data);
      }
    } catch { /* non-critical */ }
  }, [apiGet]);

  const getOntologyIri = useCallback((typeName: string): string | null => {
    const match = ontologyTypes.find(
      (t) => t.label === typeName || t.local_name === typeName
    );
    return match?.iri ?? null;
  }, [ontologyTypes]);

  useEffect(() => {
    fetchAssetTypes();
    fetchOntologyTypes();
    setStaticSegments([]);
    setDynamicTitle('Asset Explorer');
    return () => { setStaticSegments([]); setDynamicTitle(null); };
  }, [fetchAssetTypes, fetchOntologyTypes, setStaticSegments, setDynamicTitle]);

  useEffect(() => {
    const timer = setTimeout(() => setDebouncedNameFilter(nameFilter), 300);
    return () => clearTimeout(timer);
  }, [nameFilter]);

  useEffect(() => {
    setPagination(prev => prev.pageIndex === 0 ? prev : { ...prev, pageIndex: 0 });
  }, [debouncedNameFilter]);

  useEffect(() => {
    fetchAssets(selectedTypeId, pagination, debouncedNameFilter);
    setRowSelection({});
  }, [selectedTypeId, pagination, debouncedNameFilter, fetchAssets]);

  const handleTypeChange = useCallback((typeId: string | null, typeName?: string) => {
    setPagination(prev => ({ ...prev, pageIndex: 0 }));
    selectType(typeId, typeName);
  }, [selectType]);

  const selectedType = useMemo(
    () => assetTypes.find(t => t.id === selectedTypeId),
    [assetTypes, selectedTypeId]
  );

  const visibleAssetTypes = assetTypes;

  const groupedTypes = useMemo(() => {
    const groups: Record<string, AssetTypeRead[]> = {};
    for (const t of visibleAssetTypes) {
      const cat = t.category || 'custom';
      if (!groups[cat]) groups[cat] = [];
      groups[cat].push(t);
    }
    return Object.entries(groups)
      .sort(([a], [b]) => (CATEGORY_META[a]?.order ?? 99) - (CATEGORY_META[b]?.order ?? 99));
  }, [visibleAssetTypes]);

  const totalAssetCount = useMemo(
    () => visibleAssetTypes.reduce((sum, t) => sum + (t.asset_count || 0), 0),
    [visibleAssetTypes]
  );

  const openDeleteDialog = (id: string) => {
    if (!canAdmin) {
      toast({ variant: 'destructive', title: 'Permission denied', description: 'Admin access required to delete assets' });
      return;
    }
    setDeletingId(id);
    setIsDeleteDialogOpen(true);
  };

  const handleBulkDelete = async (selectedRows: AssetRead[]) => {
    if (!canAdmin) {
      toast({ variant: 'destructive', title: 'Permission denied', description: 'Admin access required to delete assets' });
      return;
    }
    const selectedIds = selectedRows.map(r => r.id).filter((id): id is string => !!id);
    if (selectedIds.length === 0) return;
    if (!confirm(`Are you sure you want to delete ${selectedIds.length} asset(s)? This action cannot be undone.`)) return;

    const results = await Promise.allSettled(selectedIds.map(async (id) => {
      const response = await apiDelete(`/api/assets/${id}`);
      if (response.error) throw new Error(response.error);
      return id;
    }));

    const successes = results.filter(r => r.status === 'fulfilled').length;
    const failures = results.filter(r => r.status === 'rejected').length;

    if (successes > 0) {
      toast({ title: 'Assets deleted', description: `Successfully deleted ${successes} asset(s).` });
    }
    if (failures > 0) {
      const firstError = (results.find(r => r.status === 'rejected') as PromiseRejectedResult)?.reason?.message || 'Unknown error';
      toast({ variant: 'destructive', title: 'Some deletions failed', description: `${failures} asset(s) failed to delete: ${firstError}` });
    }
    setRowSelection({});
    fetchAssets(selectedTypeId, pagination, debouncedNameFilter);
    fetchAssetTypes();
  };

  const columns = useMemo<ColumnDef<AssetRead>[]>(() => {
    const cols: ColumnDef<AssetRead>[] = [
    {
      accessorKey: 'name',
      header: ({ column }) => (
        <Button variant="ghost" onClick={() => column.toggleSorting(column.getIsSorted() === 'asc')}>
          Name <ChevronDown className="ml-2 h-4 w-4" />
        </Button>
      ),
      cell: ({ row }) => (
        <div>
          <span className="font-medium">{row.original.name}</span>
          {row.original.parent_name && (
            <div
              className="text-xs text-muted-foreground cursor-pointer hover:underline truncate max-w-sm"
              onClick={(e) => {
                e.stopPropagation();
                if (row.original.parent_id) navigate(`/assets/${row.original.parent_id}`);
              }}
            >
              in {row.original.parent_name}
            </div>
          )}
          {!row.original.parent_name && row.original.description && (
            <div className="text-xs text-muted-foreground truncate max-w-sm">{row.original.description}</div>
          )}
        </div>
      ),
    },
    ...(!selectedTypeId ? [{
      accessorKey: 'asset_type_name',
      header: 'Type',
      cell: ({ row }: { row: any }) => (
        <Badge variant="outline" className="text-xs">
          {row.original.asset_type_name || '-'}
        </Badge>
      ),
    } as ColumnDef<AssetRead>] : []),
    {
      accessorKey: 'platform',
      header: 'Platform',
      cell: ({ row }) => row.original.platform
        ? <Badge variant="outline">{row.original.platform}</Badge>
        : <span className="text-muted-foreground">-</span>,
    },
    {
      accessorKey: 'location',
      header: 'Location',
      cell: ({ row }) => (
        <div className="truncate max-w-xs text-sm text-muted-foreground font-mono">
          {row.original.location || '-'}
        </div>
      ),
    },
    {
      accessorKey: 'status',
      header: 'Status',
      cell: ({ row }) => (
        <Badge variant={STATUS_VARIANT[row.original.status] ?? 'outline'}>
          {row.original.status}
        </Badge>
      ),
    },
    {
      id: 'tags',
      header: 'Tags',
      cell: ({ row }) => {
        const tags = row.original.tags;
        if (!tags || tags.length === 0) return <span className="text-muted-foreground">-</span>;
        const visible = tags.slice(0, 2);
        const overflow = tags.slice(2);
        return (
          <div className="flex flex-wrap gap-1">
            {visible.map((tag) => (
              <Badge key={tag} variant="secondary" className="text-xs">{tag}</Badge>
            ))}
            {overflow.length > 0 && (
              <TooltipProvider>
                <Tooltip>
                  <TooltipTrigger asChild>
                    <Badge variant="outline" className="text-xs cursor-default">+{overflow.length}</Badge>
                  </TooltipTrigger>
                  <TooltipContent side="top" className="flex flex-col gap-1">
                    {overflow.map((tag) => (
                      <Badge key={tag} variant="secondary" className="text-xs">{tag}</Badge>
                    ))}
                  </TooltipContent>
                </Tooltip>
              </TooltipProvider>
            )}
          </div>
        );
      },
    },
    {
      accessorKey: 'updated_at',
      header: ({ column }) => (
        <Button variant="ghost" onClick={() => column.toggleSorting(column.getIsSorted() === 'asc')}>
          Updated <ChevronDown className="ml-2 h-4 w-4" />
        </Button>
      ),
      cell: ({ row }) => row.original.updated_at
        ? <RelativeDate date={row.original.updated_at} />
        : '-',
    },
    {
      id: 'actions',
      header: '',
      cell: ({ row }) => (
        <div onClick={(e) => e.stopPropagation()}>
          <DropdownMenu>
            <DropdownMenuTrigger asChild>
              <Button variant="ghost" className="h-8 w-8 p-0">
                <MoreHorizontal className="h-4 w-4" />
              </Button>
            </DropdownMenuTrigger>
            <DropdownMenuContent align="end">
              <DropdownMenuLabel>Actions</DropdownMenuLabel>
              <DropdownMenuItem
                onClick={() => navigate(`/assets/${row.original.id}`)}
              >
                View details
              </DropdownMenuItem>
              <DropdownMenuItem
                onClick={() => { setPreviewAssetId(row.original.id ?? null); setPreviewAssetTitle(row.original.name ?? ''); }}
              >
                <Eye className="mr-2 h-4 w-4" /> Preview metadata
              </DropdownMenuItem>
              <DropdownMenuItem
                disabled={!canWrite}
                onClick={() => { setEditingAsset(row.original); setIsFormOpen(true); }}
              >
                Edit
              </DropdownMenuItem>
              <DropdownMenuSeparator />
              <DropdownMenuItem
                onClick={() => openDeleteDialog(row.original.id)}
                className="text-red-600 focus:text-red-600 focus:bg-red-50 dark:text-red-400 dark:focus:bg-red-950"
                disabled={!canAdmin}
              >
                Delete
              </DropdownMenuItem>
            </DropdownMenuContent>
          </DropdownMenu>
        </div>
      ),
    },
    ];
    return cols;
  }, [canWrite, canAdmin, navigate, selectedTypeId]);

  if (apiIsLoading && assetTypes.length === 0) {
    return (
      <div className="py-6">
        <ListViewSkeleton columns={5} rows={5} toolbarButtons={1} />
      </div>
    );
  }

  if (!canRead && !permissionsLoading) {
    return (
      <div className="py-6">
        <Alert variant="destructive">
          <AlertCircle className="h-4 w-4" />
          <AlertTitle>Permission Denied</AlertTitle>
          <AlertDescription>You don't have access to view assets.</AlertDescription>
        </Alert>
      </div>
    );
  }

  return (
    <div className="py-6">
      <div className="mb-6">
        <h1 className="text-3xl font-bold flex items-center gap-2">
          <Box className="w-8 h-8" />
          Asset Explorer
        </h1>
        <p className="text-muted-foreground mt-1">
          Browse and manage all governed assets across {visibleAssetTypes.length} types ({totalAssetCount} total assets)
        </p>
      </div>

      {componentError && (
        <Alert variant="destructive" className="mb-4">
          <AlertCircle className="h-4 w-4" />
          <AlertTitle>Error</AlertTitle>
          <AlertDescription>{componentError}</AlertDescription>
        </Alert>
      )}

      <div className="flex gap-6">
        {/* Sidebar: Asset Types grouped by category */}
        <div className="w-72 flex-shrink-0">
          <Card>
            <CardHeader className="pb-3">
              <CardTitle className="text-sm font-medium">Asset Types</CardTitle>
              <CardDescription className="text-xs">
                {assetTypes.length} types across {groupedTypes.length} categories
              </CardDescription>
            </CardHeader>
            <CardContent className="p-0">
              <ScrollArea className="h-[calc(100vh-320px)]">
                <div className="px-2 pb-2">
                  {/* "All" option */}
                  <button
                    onClick={() => handleTypeChange(null)}
                    className={cn(
                      'w-full flex items-center gap-2 rounded-md px-3 py-2 text-sm transition-colors mb-1',
                      !selectedTypeId
                        ? 'bg-primary text-primary-foreground'
                        : 'hover:bg-muted text-foreground'
                    )}
                  >
                    <Shapes className="h-4 w-4 flex-shrink-0" />
                    <span className="flex-1 text-left">All Assets</span>
                    <Badge variant={!selectedTypeId ? 'secondary' : 'outline'} className="text-xs ml-auto">
                      {totalAssetCount}
                    </Badge>
                  </button>

                  <Separator className="my-2" />

                  {groupedTypes.map(([category, types]) => {
                    const meta = CATEGORY_META[category] || CATEGORY_META.custom;
                    const CategoryIcon = meta.icon;
                    const categoryCount = types.reduce((s, t) => s + (t.asset_count || 0), 0);

                    return (
                      <div key={category} className="mb-3">
                        <div className="flex items-center gap-2 px-3 py-1.5 text-xs font-semibold text-muted-foreground uppercase tracking-wider">
                          <CategoryIcon className="h-3.5 w-3.5" />
                          {meta.label}
                          <span className="ml-auto text-xs font-normal">{categoryCount}</span>
                        </div>
                        {types
                          .sort((a, b) => (b.asset_count || 0) - (a.asset_count || 0))
                          .map((assetType) => {
                            const TypeIcon = getIconComponent(assetType.icon);
                            const isSelected = selectedTypeId === assetType.id;
                            return (
                              <button
                                key={assetType.id}
                                onClick={() => handleTypeChange(assetType.id, assetType.name)}
                                className={cn(
                                  'w-full flex items-center gap-2 rounded-md px-3 py-1.5 text-sm transition-colors',
                                  isSelected
                                    ? 'bg-primary text-primary-foreground'
                                    : 'hover:bg-muted text-foreground'
                                )}
                              >
                                <TypeIcon className="h-4 w-4 flex-shrink-0" />
                                <span className="flex-1 text-left truncate">{assetType.name}</span>
                                <Badge
                                  variant={isSelected ? 'secondary' : 'outline'}
                                  className="text-xs ml-auto"
                                >
                                  {assetType.asset_count || 0}
                                </Badge>
                              </button>
                            );
                          })}
                      </div>
                    );
                  })}
                </div>
              </ScrollArea>
            </CardContent>
          </Card>
        </div>

        {/* Main content: Asset table */}
        <div className="flex-1 min-w-0">
          <Card>
            <CardHeader className="pb-3">
              <div className="flex items-center justify-between">
                <div className="flex items-center gap-2">
                  {selectedType && (() => {
                    const Icon = getIconComponent(selectedType.icon);
                    return <Icon className="h-5 w-5 text-muted-foreground" />;
                  })()}
                  <div>
                    <CardTitle className="text-lg">
                      {selectedType ? selectedType.name : 'All Assets'}
                    </CardTitle>
                    {selectedType?.description && (
                      <CardDescription className="text-xs mt-0.5">
                        {selectedType.description}
                      </CardDescription>
                    )}
                  </div>
                </div>
                <div className="flex items-center gap-2">
                  {selectedType?.category && (
                    <Badge variant="outline" className="text-xs">
                      {CATEGORY_META[selectedType.category]?.label || selectedType.category}
                    </Badge>
                  )}
                  <Badge variant="secondary">{selectedType ? selectedType.asset_count : totalAssetCount} assets</Badge>
                </div>
              </div>
            </CardHeader>
            <CardContent>
                <DataTable
                  isLoading={assetsLoading}
                  columns={columns}
                  data={assets}
                  searchColumn="name"
                  searchValue={nameFilter}
                  onSearchChange={setNameFilter}
                  storageKey={`asset-explorer-${selectedTypeId || 'all'}`}
                  onRowClick={(row) => navigate(`/assets/${row.id}`)}
                  rowSelection={rowSelection}
                  onRowSelectionChange={setRowSelection}
                  manualPagination
                  pageCount={Math.ceil(assetsTotal / pagination.pageSize)}
                  paginationState={pagination}
                  onPaginationChange={setPagination}
                  toolbarActions={
                    <div className="flex items-center gap-2">
                      {canWrite && (
                        <Button
                          size="sm"
                          variant="outline"
                          className="h-9"
                          onClick={() => navigate('/schema-importer')}
                        >
                          <FileInput className="mr-2 h-4 w-4" />
                          Schema Importer
                        </Button>
                      )}
                      {canRead && (
                        <Button
                          size="sm"
                          variant="outline"
                          className="h-9"
                          onClick={() => setIsImportExportOpen(true)}
                        >
                          <FileSpreadsheet className="mr-2 h-4 w-4" />
                          {hasSelection ? `Export ${selectedAssetIds.length} Selected` : 'Import / Export'}
                        </Button>
                      )}
                      {canWrite && selectedType && (
                        <Button
                          size="sm"
                          className="h-9"
                          onClick={() => { setEditingAsset(null); setIsFormOpen(true); }}
                        >
                          <PlusCircle className="mr-2 h-4 w-4" />
                          Add {selectedType.name}
                        </Button>
                      )}
                    </div>
                  }
                  bulkActions={(selectedRows) => (
                    <Button
                      variant="destructive"
                      size="sm"
                      className="h-9 gap-1"
                      onClick={() => handleBulkDelete(selectedRows)}
                      disabled={selectedRows.length === 0 || !canAdmin}
                      title={canAdmin ? 'Delete selected assets' : 'Admin access required'}
                    >
                      <Trash2 className="w-4 h-4 mr-1" />
                      Delete {selectedRows.length} Selected
                    </Button>
                  )}
                />
            </CardContent>
          </Card>
        </div>
      </div>

      {selectedType && (
        <AssetFormDialog
          isOpen={isFormOpen}
          onOpenChange={(open) => { setIsFormOpen(open); if (!open) setEditingAsset(null); }}
          onSuccess={() => {
            fetchAssets(selectedTypeId, pagination, debouncedNameFilter);
            fetchAssetTypes();
          }}
          assetTypeId={selectedType.id}
          assetTypeName={selectedType.name}
          assetTypeIri={getOntologyIri(selectedType.name)}
          asset={editingAsset}
        />
      )}

      {deletingId && (
        <AssetDeleteDialog
          open={isDeleteDialogOpen}
          onOpenChange={(open) => {
            setIsDeleteDialogOpen(open);
            if (!open) setDeletingId(null);
          }}
          assetId={deletingId}
          assetName={assets.find(a => a.id === deletingId)?.name || ''}
          onDeleted={() => {
            fetchAssets(selectedTypeId, pagination, debouncedNameFilter);
            fetchAssetTypes();
            setDeletingId(null);
          }}
        />
      )}

      <EntityInfoDialog
        entityType="asset"
        entityId={previewAssetId}
        open={!!previewAssetId}
        onOpenChange={(o) => { if (!o) setPreviewAssetId(null); }}
        title={previewAssetTitle}
      />

      <AssetImportExportDialog
        isOpen={isImportExportOpen}
        onOpenChange={(open) => {
          setIsImportExportOpen(open);
          if (!open) setRowSelection({});
        }}
        selectedAssetTypeId={selectedTypeId}
        selectedAssetTypeName={selectedType?.name}
        selectedAssetIds={selectedAssetIds}
        canImport={canWrite}
        onImportComplete={() => {
          fetchAssets(selectedTypeId, pagination, debouncedNameFilter);
          fetchAssetTypes();
          setRowSelection({});
        }}
      />
    </div>
  );
}
