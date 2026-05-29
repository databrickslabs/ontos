import { useState, useEffect, useCallback } from 'react';
import { ColumnDef } from '@tanstack/react-table';
import { useTranslation } from 'react-i18next';
import { PlusCircle, MoreHorizontal, HeartPulse, Loader2, Plug } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Badge } from '@/components/ui/badge';
import { DataTable } from '@/components/ui/data-table';
import {
  DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuLabel,
  DropdownMenuSeparator, DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu';
import {
  AlertDialog, AlertDialogAction, AlertDialogCancel, AlertDialogContent,
  AlertDialogDescription, AlertDialogFooter, AlertDialogHeader, AlertDialogTitle,
} from '@/components/ui/alert-dialog';
import { useApi } from '@/hooks/use-api';
import { useToast } from '@/hooks/use-toast';
import { usePermissions } from '@/stores/permissions-store';
import { FeatureAccessLevel } from '@/types/settings';
import { Connection } from '@/types/connections';
import { RelativeDate } from '@/components/common/relative-date';
import { ConnectionFormDialog } from './connection-form-dialog';

const SYSTEM_CREATED_BY = 'system';

export default function ConnectorsSettings() {
  const { t } = useTranslation(['settings', 'common']);
  const { get: apiGet, delete: apiDelete } = useApi();
  const { toast } = useToast();
  const { hasPermission } = usePermissions();

  const hasWriteAccess = hasPermission('settings-connectors', FeatureAccessLevel.READ_WRITE);

  const [connections, setConnections] = useState<Connection[]>([]);
  const [isLoading, setIsLoading] = useState(false);
  const [isFormOpen, setIsFormOpen] = useState(false);
  const [editingConnection, setEditingConnection] = useState<Connection | null>(null);
  const [isDeleteDialogOpen, setIsDeleteDialogOpen] = useState(false);
  const [deletingId, setDeletingId] = useState<string | null>(null);
  const [testingId, setTestingId] = useState<string | null>(null);

  const fetchConnections = useCallback(async () => {
    setIsLoading(true);
    try {
      const response = await apiGet<Connection[]>('/api/connections');
      if (response.data) {
        setConnections(response.data);
      }
    } catch (error) {
      console.error('Failed to fetch connections:', error);
    } finally {
      setIsLoading(false);
    }
  }, [apiGet]);

  useEffect(() => {
    fetchConnections();
  }, [fetchConnections]);

  const handleTest = async (id: string) => {
    setTestingId(id);
    try {
      const response = await fetch(`/api/connections/${id}/test`, { method: 'POST' });
      const result = await response.json();
      if (result.healthy) {
        toast({
          title: t('settings:connectors.messages.testSuccess', 'Connection successful'),
          description: result.project ? `Project: ${result.project}` : undefined,
        });
      } else {
        toast({
          title: t('settings:connectors.messages.testFailed', 'Connection failed'),
          description: result.error || 'Unknown error',
          variant: 'destructive',
        });
      }
    } catch {
      toast({
        title: t('settings:connectors.messages.testError', 'Connection test error'),
        variant: 'destructive',
      });
    } finally {
      setTestingId(null);
    }
  };

  const handleDelete = async () => {
    if (!deletingId) return;
    try {
      const response = await apiDelete(`/api/connections/${deletingId}`);
      if (response.error) {
        toast({ title: 'Delete failed', description: response.error, variant: 'destructive' });
      } else {
        toast({ title: t('settings:connectors.messages.deleteSuccess', 'Connection deleted') });
        fetchConnections();
      }
    } catch {
      toast({ title: 'Delete failed', variant: 'destructive' });
    } finally {
      setIsDeleteDialogOpen(false);
      setDeletingId(null);
    }
  };

  const isSystem = (conn: Connection) => conn.created_by === SYSTEM_CREATED_BY;

  const columns: ColumnDef<Connection, any>[] = [
    {
      accessorKey: 'name',
      header: t('settings:connectors.columns.name', 'Name'),
      cell: ({ row }) => (
        <div className="flex items-center gap-2">
          <span className="font-medium">{row.original.name}</span>
          {isSystem(row.original) && (
            <Badge variant="outline" className="text-xs">System</Badge>
          )}
        </div>
      ),
    },
    {
      accessorKey: 'connector_type',
      header: t('settings:connectors.columns.type', 'Type'),
      cell: ({ row }) => (
        <Badge variant="secondary" className="capitalize">
          {row.original.connector_type}
        </Badge>
      ),
    },
    {
      accessorKey: 'description',
      header: t('settings:connectors.columns.description', 'Description'),
      cell: ({ row }) => (
        <span className="text-muted-foreground text-sm truncate max-w-[300px] block">
          {row.original.description || '—'}
        </span>
      ),
    },
    {
      accessorKey: 'enabled',
      header: t('settings:connectors.columns.status', 'Status'),
      cell: ({ row }) => {
        if (row.original.is_default) {
          return <Badge variant="default">Default</Badge>;
        }
        return row.original.enabled
          ? <Badge className="bg-green-600 hover:bg-green-700">Enabled</Badge>
          : <Badge variant="outline">Disabled</Badge>;
      },
    },
    {
      accessorKey: 'updated_at',
      header: t('settings:connectors.columns.updated', 'Updated'),
      cell: ({ row }) => <RelativeDate date={row.original.updated_at} />,
    },
    {
      id: 'actions',
      header: '',
      cell: ({ row }) => {
        const conn = row.original;
        const isTesting = testingId === conn.id;
        return (
          <div className="flex items-center justify-end gap-1">
            <Button
              variant="ghost"
              size="sm"
              onClick={(e) => { e.stopPropagation(); handleTest(conn.id); }}
              disabled={isTesting}
              title="Test Connection"
            >
              {isTesting
                ? <Loader2 className="w-4 h-4 animate-spin" />
                : <HeartPulse className="w-4 h-4" />}
            </Button>
            <DropdownMenu>
              <DropdownMenuTrigger asChild>
                <Button variant="ghost" size="sm" onClick={(e) => e.stopPropagation()}>
                  <MoreHorizontal className="w-4 h-4" />
                </Button>
              </DropdownMenuTrigger>
              <DropdownMenuContent align="end">
                <DropdownMenuLabel>{conn.name}</DropdownMenuLabel>
                <DropdownMenuSeparator />
                <DropdownMenuItem onClick={() => { setEditingConnection(conn); setIsFormOpen(true); }}>
                  {t('common:edit', 'Edit')}
                </DropdownMenuItem>
                <DropdownMenuItem onClick={() => handleTest(conn.id)}>
                  {t('settings:connectors.testConnection', 'Test Connection')}
                </DropdownMenuItem>
                {!isSystem(conn) && (
                  <>
                    <DropdownMenuSeparator />
                    <DropdownMenuItem
                      className="text-destructive"
                      onClick={() => { setDeletingId(conn.id); setIsDeleteDialogOpen(true); }}
                    >
                      {t('common:delete', 'Delete')}
                    </DropdownMenuItem>
                  </>
                )}
              </DropdownMenuContent>
            </DropdownMenu>
          </div>
        );
      },
    },
  ];

  return (
    <>
      <div className="mb-6">
        <h1 className="text-3xl font-bold flex items-center gap-2">
          <Plug className="w-8 h-8" />
          {t('settings:connectors.title', 'Connections')}
        </h1>
        <p className="text-muted-foreground mt-1">
          {t('settings:connectors.description', 'Manage connections to external data platforms for asset discovery and metadata retrieval.')}
        </p>
      </div>

      <DataTable
        columns={columns}
        data={connections}
        searchColumn="name"
        isLoading={isLoading}
        storageKey="connections-sort"
        onRowClick={(row) => { setEditingConnection(row.original); setIsFormOpen(true); }}
        toolbarActions={
          hasWriteAccess ? (
            <Button
              size="sm"
              onClick={() => { setEditingConnection(null); setIsFormOpen(true); }}
            >
              <PlusCircle className="w-4 h-4 mr-2" />
              {t('settings:connectors.addConnection', 'Add Connection')}
            </Button>
          ) : undefined
        }
      />

      <ConnectionFormDialog
        isOpen={isFormOpen}
        onOpenChange={setIsFormOpen}
        initialConnection={editingConnection}
        onSubmitSuccess={fetchConnections}
      />

      <AlertDialog open={isDeleteDialogOpen} onOpenChange={setIsDeleteDialogOpen}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>{t('settings:connectors.deleteTitle', 'Delete Connection')}</AlertDialogTitle>
            <AlertDialogDescription>
              {t('settings:connectors.deleteDescription', 'Are you sure you want to delete this connection? This action cannot be undone.')}
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>{t('common:cancel', 'Cancel')}</AlertDialogCancel>
            <AlertDialogAction onClick={handleDelete} className="bg-destructive text-destructive-foreground hover:bg-destructive/90">
              {t('common:delete', 'Delete')}
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </>
  );
}
