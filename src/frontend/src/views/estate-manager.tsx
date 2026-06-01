import { useState, useEffect } from 'react';
import { useTranslation } from 'react-i18next';
import { useToast } from '@/hooks/use-toast';
import { useApi } from '@/hooks/use-api';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Switch } from '@/components/ui/switch';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from '@/components/ui/dialog';
import { Badge } from '@/components/ui/badge';
import { MoreHorizontal, Globe, Plus, Share2, Database, Network } from 'lucide-react';
import {
  GraphCanvasSkeleton,
  ListViewSkeleton,
} from '@/components/common/list-view-skeleton';
import { ColumnDef } from "@tanstack/react-table"
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu"
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from "@/components/ui/tooltip"
import { useNavigate, useLocation } from 'react-router-dom';
import useBreadcrumbStore from '@/stores/breadcrumb-store';
import { ViewModeToggle } from '@/components/common/view-mode-toggle';
import { DataTable } from '@/components/ui/data-table';
import EstateGraphView from '@/components/estates/estate-graph-view';

// --- TypeScript Interfaces corresponding to Pydantic Models ---
type CloudType = 'aws' | 'azure' | 'gcp';
type SyncStatus = 'pending' | 'running' | 'success' | 'failed';
type ConnectionType = 'delta_share' | 'database';
type SharingResourceType = 'data_product' | 'business_glossary';
type SharingRuleOperator = 'equals' | 'contains' | 'starts_with' | 'regex';

interface SharingRule {
  filter_type: string;
  operator: SharingRuleOperator;
  filter_value: string;
}

interface SharingPolicy {
  id?: string;
  name: string;
  description?: string;
  resource_type: SharingResourceType;
  rules: SharingRule[];
  is_enabled: boolean;
  created_at: string; // ISO datetime string
  updated_at: string; // ISO datetime string
}

interface Estate {
  id: string;
  name: string;
  description: string;
  workspace_url: string;
  cloud_type: CloudType;
  metastore_name: string;
  connection_type: ConnectionType;
  sharing_policies: SharingPolicy[];
  is_enabled: boolean;
  sync_schedule: string;
  last_sync_time?: string;
  last_sync_status?: SyncStatus;
  last_sync_error?: string;
  created_at: string;
  updated_at: string;
}
// --- End TypeScript Interfaces ---

export default function EstateManager() {
  const { t } = useTranslation(['estates', 'common']);
  const { toast } = useToast();
  const { get, post, put, delete: deleteEstateApi } = useApi();
  const navigate = useNavigate();
  const { pathname } = useLocation();
  const setStaticSegments = useBreadcrumbStore((state) => state.setStaticSegments);
  const setDynamicTitle = useBreadcrumbStore((state) => state.setDynamicTitle);
  const [estates, setEstates] = useState<Estate[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [selectedEstate, setSelectedEstate] = useState<Estate | null>(null);
  const [isDialogOpen, setIsDialogOpen] = useState(false);
  const [formData, setFormData] = useState<Partial<Estate>>({
    name: '',
    description: '',
    workspace_url: '',
    cloud_type: 'aws',
    metastore_name: '',
    connection_type: 'delta_share',
    sharing_policies: [],
    is_enabled: true,
    sync_schedule: '0 0 * * *',
  });
  const [viewMode, setViewMode] = useState<'table' | 'graph'>('table');

  useEffect(() => {
    fetchEstates();
    // Set breadcrumbs for this top-level view
    setStaticSegments([]); // No static parents other than Home
    setDynamicTitle('Estate Manager');

    return () => {
        // Clear breadcrumbs when component unmounts
        setStaticSegments([]);
        setDynamicTitle(null);
    };
  }, [setStaticSegments, setDynamicTitle]);

  const fetchEstates = async () => {
    try {
      setIsLoading(true);
      const response = await get<Estate[]>('/api/estates');
      setEstates(response.data || []);
    } catch (error) {
      toast({
        title: t('estates:errors.fetchEstates'),
        description: error instanceof Error ? error.message : t('estates:errors.couldNotLoad'),
        variant: 'destructive',
      });
      setEstates([]);
    } finally {
      setIsLoading(false);
    }
  };

  const handleSubmit = async () => {
    if (!formData.name || !formData.description || !formData.workspace_url || !formData.metastore_name || !formData.cloud_type || !formData.connection_type) {
        toast({
            title: t('estates:errors.validationError'),
            description: t('estates:errors.validationMessage'),
            variant: "destructive",
        });
        return;
    }
    
    try {
      let response;
      const payload: Estate = {
        id: selectedEstate?.id || '',
        name: formData.name!,
        description: formData.description!,
        workspace_url: formData.workspace_url!,
        cloud_type: formData.cloud_type!,
        metastore_name: formData.metastore_name!,
        connection_type: formData.connection_type!,
        sharing_policies: formData.sharing_policies || [],
        is_enabled: formData.is_enabled === undefined ? true : formData.is_enabled,
        sync_schedule: formData.sync_schedule || '0 0 * * *',
        created_at: selectedEstate?.created_at || new Date().toISOString(),
        updated_at: new Date().toISOString(),
      };

      if (selectedEstate && selectedEstate.id) {
        response = await put<Estate>(`/api/estates/${selectedEstate.id}`, payload);
      } else {
        const createPayload = { ...payload };
        delete (createPayload as any).id; 
        delete (createPayload as any).created_at;
        delete (createPayload as any).updated_at;
        response = await post<Estate>('/api/estates', createPayload);
      }
      
      if (response.error) throw new Error(response.error);
      if (response.data && typeof response.data === 'object' && 'detail' in response.data && typeof response.data.detail === 'string') {
        throw new Error(response.data.detail);
      }
      
      toast({
        title: t('common:toast.success'),
        description: selectedEstate ? t('estates:toast.estateUpdated') : t('estates:toast.estateCreated'),
      });
      
      setIsDialogOpen(false);
      fetchEstates();
    } catch (error) {
      toast({
        title: t('estates:errors.savingEstate'),
        description: error instanceof Error ? error.message : t('common:errors.saveFailed'),
        variant: 'destructive',
      });
    }
  };

  const handleDelete = async (estateId: string) => {
    if (!confirm(t('estates:messages.deleteConfirm'))) return;
    try {
      const response = await deleteEstateApi(`/api/estates/${estateId}`);
      if (response.error) throw new Error(response.error);
      toast({
        title: t('common:toast.success'),
        description: t('estates:toast.estateDeleted'),
      });
      fetchEstates();
    } catch (error) {
      toast({
        title: t('estates:errors.deletingEstate'),
        description: error instanceof Error ? error.message : t('common:errors.deleteFailed'),
        variant: 'destructive',
      });
    }
  };

  const handleSync = async (id: string) => {
    toast({ title: t('estates:toast.triggeringSync'), description: t('estates:toast.syncRequested') });
    try {
      const response = await post(`/api/estates/${id}/sync`, {});
      if (response.error) throw new Error(response.error);
      if (response.data && typeof response.data === 'object' && 'detail' in response.data && typeof response.data.detail === 'string') {
        throw new Error(response.data.detail);
      }
      toast({
        title: t('common:toast.success'),
        description: t('estates:toast.syncTriggered'),
      });
      setTimeout(fetchEstates, 1000);
    } catch (error) {
      toast({
        title: t('estates:errors.triggeringSync'),
        description: error instanceof Error ? error.message : t('common:errors.updateFailed'),
        variant: 'destructive',
      });
    }
  };

  const openDialog = (estate?: Estate) => {
    if (estate) {
      setSelectedEstate(estate);
      setFormData({
        ...estate,
        connection_type: estate.connection_type || 'delta_share',
        sharing_policies: estate.sharing_policies || [],
      });
    } else {
      setSelectedEstate(null);
      setFormData({
        name: '',
        description: '',
        workspace_url: '',
        cloud_type: 'aws',
        metastore_name: '',
        connection_type: 'delta_share',
        sharing_policies: [],
        is_enabled: true,
        sync_schedule: '0 0 * * *',
      });
    }
    setIsDialogOpen(true);
  };
  
  const handleNodeClick = (estateId: string) => {
    navigate(`${pathname}/${estateId}`);
  };

  const columns: ColumnDef<Estate>[] = [
    {
      accessorKey: "name",
      header: t('common:labels.name'),
      cell: ({ row }) => (
        <div className="font-medium">{row.getValue("name")}</div>
      ),
    },
    {
      accessorKey: "workspace_url",
      header: t('common:labels.workspaceUrl'),
      cell: ({ row }) => <div>{row.getValue("workspace_url")}</div>,
    },
    {
      accessorKey: "cloud_type",
      header: t('common:labels.cloud'),
      cell: ({ row }) => <div className="capitalize">{row.getValue("cloud_type")}</div>,
    },
    {
      accessorKey: "connection_type",
      header: t('common:labels.connection'),
      cell: ({ row }) => {
        const connectionType = row.getValue("connection_type") as ConnectionType;
        return (
          <div className="flex items-center gap-1 capitalize">
            {connectionType === 'delta_share' ? 
              <Share2 className="h-4 w-4 text-blue-500" /> : 
              <Database className="h-4 w-4 text-green-500" />}
            {connectionType.replace('_', ' ')}
          </div>
        );
      },
    },
    {
      accessorKey: "metastore_name",
      header: t('common:labels.metastore'),
      cell: ({ row }) => <div>{row.getValue("metastore_name")}</div>,
    },
    {
      accessorKey: "is_enabled",
      header: t('common:labels.syncStatus'),
      cell: ({ row }) => (
        <Badge variant={row.getValue("is_enabled") ? "default" : "secondary"}>
          {row.getValue("is_enabled") ? t('common:labels.enabled') : t('common:labels.disabled')}
        </Badge>
      ),
    },
    {
      accessorKey: "last_sync_status",
      header: t('common:labels.lastSync'),
      cell: ({ row }) => {
        const lastSyncTime = row.original.last_sync_time;
        const status = row.original.last_sync_status;
        const error = row.original.last_sync_error;

        if (!status) return <Badge variant="outline">Never Synced</Badge>;

        let badgeVariant: "default" | "destructive" | "secondary" | "outline" = 'outline';
        if (status === 'success') badgeVariant = 'default';
        else if (status === 'failed') badgeVariant = 'destructive';
        else if (status === 'running' || status === 'pending') badgeVariant = 'secondary';
        
        const statusText = status.charAt(0).toUpperCase() + status.slice(1);

        return (
          <TooltipProvider delayDuration={100}>
            <Tooltip>
              <TooltipTrigger asChild>
                <span>
                  <Badge variant={badgeVariant} className="cursor-default">
                    {statusText}
                  </Badge>
                </span>
              </TooltipTrigger>
              <TooltipContent side="top">
                <p>Status: {statusText}</p>
                {lastSyncTime && <p>Time: {new Date(lastSyncTime).toLocaleString()}</p>}
                {status === 'failed' && error && <p className="text-red-400">Error: {error}</p>}
                {(status === 'running' || status === 'pending') && <p>Sync in progress or queued...</p>}
              </TooltipContent>
            </Tooltip>
          </TooltipProvider>
        );
      },
    },
    {
      id: "actions",
      enableHiding: false,
      cell: ({ row }) => {
        const estate = row.original;
        return (
          <DropdownMenu>
            <DropdownMenuTrigger asChild>
              <Button variant="ghost" className="h-8 w-8 p-0" onClick={(e) => e.stopPropagation()}>
                <span className="sr-only">Open menu</span>
                <MoreHorizontal className="h-4 w-4" />
              </Button>
            </DropdownMenuTrigger>
            <DropdownMenuContent align="end">
              <DropdownMenuLabel>{t('common:labels.actions')}</DropdownMenuLabel>
              <DropdownMenuItem onClick={(e) => { e.stopPropagation(); handleNodeClick(estate.id); }}>{t('estates:details.viewDetails')}</DropdownMenuItem>
              <DropdownMenuItem onClick={(e) => { e.stopPropagation(); handleSync(estate.id); }}>
                {t('estates:details.sync')}
              </DropdownMenuItem>
              <DropdownMenuItem onClick={(e) => { e.stopPropagation(); openDialog(estate); }}>
                {t('common:actions.edit')}
              </DropdownMenuItem>
              <DropdownMenuSeparator />
              <DropdownMenuItem
                className="text-red-600 focus:text-red-50 focus:bg-red-600 dark:text-red-400"
                onClick={(e) => { e.stopPropagation(); handleDelete(estate.id); }}
              >
                {t('common:actions.delete')}
              </DropdownMenuItem>
            </DropdownMenuContent>
          </DropdownMenu>
        );
      },
    },
  ];

  return (
    <div className="py-6">
      <h1 className="text-3xl font-bold mb-6 flex items-center gap-2">
        <Globe className="w-8 h-8" /> {t('estates:title')}
      </h1>

      <div className="space-y-4">
        <div className="flex items-center justify-end">
          <ViewModeToggle 
              currentView={viewMode}
              onViewChange={setViewMode}
              graphViewIcon={<Network className="h-4 w-4" />}
          />
        </div>

        {isLoading ? (
          viewMode === 'table' ? (
            <ListViewSkeleton columns={8} rows={5} toolbarButtons={1} />
          ) : (
            <GraphCanvasSkeleton showToolbar={false} height="h-[calc(100vh-280px)]" />
          )
        ) : viewMode === 'table' ? (
          <DataTable
            columns={columns}
            data={estates}
            searchColumn="name"
            storageKey="estate-manager-sort"
            toolbarActions={
              <Button onClick={() => openDialog()} className="h-9">
                <Plus className="h-4 w-4 mr-2" />
                {t('estates:addEstate')}
              </Button>
            }
            onRowClick={(row) => handleNodeClick(row.original.id)}
          />
        ) : (
          <div className="h-[calc(100vh-280px)] w-full border rounded-lg">
            <EstateGraphView estates={estates} onNodeClick={handleNodeClick} />
          </div>
        )}
      </div>

      <Dialog open={isDialogOpen} onOpenChange={setIsDialogOpen}>
        <DialogContent className="sm:max-w-[600px]">
          <DialogHeader>
            <DialogTitle>{selectedEstate ? t('estates:editEstate') : t('estates:form.createTitle')}</DialogTitle>
            <DialogDescription>
              {t('estates:form.dialogDescription')}
            </DialogDescription>
          </DialogHeader>
          <div className="grid gap-4 py-4">
            <div className="grid grid-cols-4 items-center gap-4">
              <Label htmlFor="name" className="text-right">{t('common:labels.name')}</Label>
              <Input
                id="name"
                value={formData.name}
                onChange={(e) => setFormData({ ...formData, name: e.target.value })}
                className="col-span-3"
                placeholder="e.g., US Production Workspace"
              />
            </div>
            <div className="grid grid-cols-4 items-center gap-4">
              <Label htmlFor="description" className="text-right">{t('common:labels.description')}</Label>
              <Input
                id="description"
                value={formData.description}
                onChange={(e) => setFormData({ ...formData, description: e.target.value })}
                className="col-span-3"
                placeholder="e.g., Primary production environment for US region"
              />
            </div>
            <div className="grid grid-cols-4 items-center gap-4">
              <Label htmlFor="workspace_url" className="text-right">{t('common:labels.workspaceUrl')}</Label>
              <Input
                id="workspace_url"
                value={formData.workspace_url}
                onChange={(e) => setFormData({ ...formData, workspace_url: e.target.value })}
                className="col-span-3"
                placeholder="e.g., https://myworkspace.cloud.databricks.com"
              />
            </div>
            <div className="grid grid-cols-4 items-center gap-4">
              <Label htmlFor="cloud_type" className="text-right">{t('common:labels.cloud')}</Label>
              <Select
                value={formData.cloud_type}
                onValueChange={(value) => setFormData({ ...formData, cloud_type: value as CloudType })}
              >
                <SelectTrigger className="col-span-3">
                  <SelectValue placeholder={t('common:placeholders.selectCloudProvider')} />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="aws">AWS</SelectItem>
                  <SelectItem value="azure">Azure</SelectItem>
                  <SelectItem value="gcp">GCP</SelectItem>
                </SelectContent>
              </Select>
            </div>
             <div className="grid grid-cols-4 items-center gap-4">
              <Label htmlFor="connection_type" className="text-right">{t('estates:form.connectionType')}</Label>
              <Select
                value={formData.connection_type}
                onValueChange={(value) => setFormData({ ...formData, connection_type: value as ConnectionType })}
              >
                <SelectTrigger className="col-span-3">
                  <SelectValue placeholder={t('common:placeholders.selectConnectionType')} />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="delta_share">{t('estates:connectionTypes.deltaShare')}</SelectItem>
                  <SelectItem value="database">{t('estates:connectionTypes.database')}</SelectItem>
                </SelectContent>
              </Select>
            </div>
            <div className="grid grid-cols-4 items-center gap-4">
              <Label htmlFor="metastore_name" className="text-right">{t('estates:form.metastoreName')}</Label>
              <Input
                id="metastore_name"
                value={formData.metastore_name}
                onChange={(e) => setFormData({ ...formData, metastore_name: e.target.value })}
                className="col-span-3"
                placeholder="e.g., primary_prod_metastore"
              />
            </div>
            <div className="grid grid-cols-4 items-center gap-4">
              <Label htmlFor="sync_schedule" className="text-right">{t('estates:form.syncSchedule')}</Label>
              <Input
                id="sync_schedule"
                value={formData.sync_schedule}
                onChange={(e) => setFormData({ ...formData, sync_schedule: e.target.value })}
                className="col-span-3"
                placeholder={t('common:placeholders.enterCronExpression')}
              />
            </div>
            <div className="grid grid-cols-4 items-center gap-4">
                <Label htmlFor="is_enabled" className="text-right">{t('estates:form.enableSync')}</Label>
                <div className="col-span-3 flex items-center">
                    <Switch
                        id="is_enabled"
                        checked={formData.is_enabled}
                        onCheckedChange={(checked) => setFormData({ ...formData, is_enabled: checked })}
                    />
                </div>
            </div>
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setIsDialogOpen(false)}>
              {t('common:actions.cancel')}
            </Button>
            <Button onClick={handleSubmit}>
              {selectedEstate ? t('common:actions.save') : t('common:actions.create')}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
} 