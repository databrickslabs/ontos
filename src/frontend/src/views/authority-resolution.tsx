import { useState, useEffect, useCallback } from 'react';
import { useNavigate, useLocation } from 'react-router-dom';
import { ColumnDef } from '@tanstack/react-table';
import { useApi } from '@/hooks/use-api';
import { usePermissions } from '@/stores/permissions-store';
import { FeatureAccessLevel } from '@/types/settings';
import { useToast } from '@/hooks/use-toast';
import { Button } from '@/components/ui/button';
import { Badge } from '@/components/ui/badge';
import { Alert, AlertDescription } from '@/components/ui/alert';
import { DataTable } from '@/components/ui/data-table';
import { ListViewSkeleton } from '@/components/common/list-view-skeleton';
import { VersionCountBadge } from '@/components/common/version-count-badge';
import { Plus, AlertCircle, ShieldCheck, Eye, Pencil, Trash2, ChevronDown } from 'lucide-react';
import CreateAuthorityRelationDialog from '@/components/authority-resolution/create-authority-relation-dialog';
import useBreadcrumbStore from '@/stores/breadcrumb-store';
import type { AuthorityRelation } from '@/types/authority-resolution';

const FEATURE_ID = 'authority-resolution';

/** Tailwind status pill colours, mirroring the Data Contracts list. */
function getStatusColor(status: string): string {
  switch ((status || '').toLowerCase()) {
    case 'active':
      return 'bg-green-100 text-green-800 dark:bg-green-900 dark:text-green-300';
    case 'needs_review':
      return 'bg-red-100 text-red-800 dark:bg-red-900 dark:text-red-300';
    case 'retired':
      return 'bg-gray-100 text-gray-800 dark:bg-gray-700 dark:text-gray-300';
    default: // draft
      return 'bg-yellow-100 text-yellow-800 dark:bg-yellow-900 dark:text-yellow-300';
  }
}

/** DNAco is a divergence: 0 is best, higher is worse (rendered like a defect rate). */
export function formatDna(magnitude: number | null | undefined, direction?: string | null): string {
  if (magnitude === null || magnitude === undefined) return '—';
  const arrow = direction === 'actual-exceeds-documented' ? ' ▲'
    : direction === 'documented-exceeds-actual' ? ' ▼' : '';
  return `${magnitude.toFixed(2)}${arrow}`;
}

export default function AuthorityResolution() {
  const navigate = useNavigate();
  const { pathname } = useLocation();
  const { toast } = useToast();
  const { get, delete: del } = useApi();
  const { hasPermission, isLoading: permissionsLoading } = usePermissions();
  const canWrite = !permissionsLoading && hasPermission(FEATURE_ID, FeatureAccessLevel.READ_WRITE);

  const [relations, setRelations] = useState<AuthorityRelation[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [createOpen, setCreateOpen] = useState(false);
  const [editRelation, setEditRelation] = useState<AuthorityRelation | null>(null);

  const fetchRelations = useCallback(async () => {
    setLoading(true);
    const { data, error } = await get<AuthorityRelation[]>('/api/authority/relations');
    if (error) {
      setError(error);
      setRelations([]);
    } else {
      setError(null);
      setRelations(Array.isArray(data) ? data : []);
    }
    setLoading(false);
  }, [get]);

  useEffect(() => { fetchRelations(); }, [fetchRelations]);

  const setStaticSegments = useBreadcrumbStore((s) => s.setStaticSegments);
  const setDynamicTitle = useBreadcrumbStore((s) => s.setDynamicTitle);
  useEffect(() => {
    setStaticSegments([]);
    setDynamicTitle('Authority Resolution');
    return () => { setStaticSegments([]); setDynamicTitle(null); };
  }, [setStaticSegments, setDynamicTitle]);

  const handleDelete = async (r: AuthorityRelation) => {
    if (!confirm(`Delete Authority Relation "${r.name}"?`)) return;
    const { error } = await del(`/api/authority/relations/${r.id}`);
    if (error) toast({ title: 'Delete failed', description: error, variant: 'destructive' });
    else { toast({ title: 'Deleted', description: r.name }); fetchRelations(); }
  };

  const handleBulkDelete = async (ids: string[]) => {
    if (ids.length === 0) return;
    if (!confirm(`Delete ${ids.length} selected Authority Relation(s)?`)) return;
    const results = await Promise.allSettled(ids.map((id) => del(`/api/authority/relations/${id}`)));
    const ok = results.filter((r) => r.status === 'fulfilled').length;
    if (ok > 0) toast({ title: 'Deleted', description: `${ok} Authority Relation(s) deleted.` });
    fetchRelations();
  };

  const sortableHeader = (label: string) => ({ column }: any) => (
    <Button variant="ghost" onClick={() => column.toggleSorting(column.getIsSorted() === 'asc')}>
      {label}
      <ChevronDown className="ml-2 h-4 w-4" />
    </Button>
  );

  const columns: ColumnDef<AuthorityRelation>[] = [
    {
      accessorKey: 'name',
      header: sortableHeader('Name'),
      cell: ({ row }) => (
        <div className="space-y-1">
          <div className="font-medium">{row.original.name}</div>
          {row.original.slug && <div className="text-xs text-muted-foreground">{row.original.slug}</div>}
        </div>
      ),
    },
    {
      accessorKey: 'status',
      header: sortableHeader('Status'),
      cell: ({ row }) => (
        <Badge variant="outline" className={getStatusColor(row.original.status)}>{row.original.status}</Badge>
      ),
    },
    {
      accessorKey: 'version',
      header: 'Version',
      cell: ({ row }) => (
        <div className="flex items-center gap-1.5">
          <span className="text-sm">v{row.original.version}</span>
          <VersionCountBadge
            count={row.original.version_count ?? undefined}
            onClick={() => navigate(`${pathname}/${row.original.id}`)}
          />
        </div>
      ),
      enableSorting: false,
    },
    {
      accessorKey: 'dna_magnitude',
      header: sortableHeader('DNAco'),
      cell: ({ row }) => formatDna(row.original.dna_magnitude, row.original.dna_direction),
    },
    {
      accessorKey: 'maturity_level_order',
      header: 'Maturity',
      cell: ({ row }) => (
        row.original.maturity_level_order != null
          ? <Badge variant="outline">L{row.original.maturity_level_order}</Badge>
          : <span className="text-muted-foreground">—</span>
      ),
      enableSorting: false,
    },
    {
      accessorKey: 'action',
      header: 'Action',
      cell: ({ row }) => <span className="text-muted-foreground">{row.original.action || '—'}</span>,
      enableSorting: false,
    },
    {
      accessorKey: 'usage_count',
      header: sortableHeader('Usage'),
      cell: ({ row }) => <div className="text-right">{row.original.usage_count ?? 0}</div>,
    },
    {
      id: 'actions',
      enableHiding: false,
      cell: ({ row }) => {
        const r = row.original;
        return (
          <div className="flex space-x-1 justify-end">
            <Button variant="ghost" size="icon" title="View" onClick={(e) => { e.stopPropagation(); navigate(`${pathname}/${r.id}`); }}>
              <Eye className="h-4 w-4" />
            </Button>
            {canWrite && (
              <>
                <Button variant="ghost" size="icon" title="Edit" onClick={(e) => { e.stopPropagation(); setEditRelation(r); }}>
                  <Pencil className="h-4 w-4" />
                </Button>
                <Button
                  variant="ghost"
                  size="icon"
                  className="text-destructive hover:text-destructive"
                  title="Delete"
                  onClick={(e) => { e.stopPropagation(); handleDelete(r); }}
                >
                  <Trash2 className="h-4 w-4" />
                </Button>
              </>
            )}
          </div>
        );
      },
    },
  ];

  return (
    <div className="py-6">
      <h1 className="text-3xl font-bold mb-6 flex items-center gap-2">
        <ShieldCheck className="w-8 h-8" />
        Authority Resolution
      </h1>

      <p className="text-muted-foreground mb-6 max-w-3xl">
        Author <strong>Authority Relations</strong> (ARF) that make soft decision authority explicit
        and agent-callable. Each relation carries a DNA-Coefficient — a divergence measure where
        <strong> 0.0 is best</strong> — computed from bound evidence, and becomes active only once it
        is within its threshold and fully affirmed.
      </p>

      {error && (
        <Alert variant="destructive" className="mb-4">
          <AlertCircle className="h-4 w-4" />
          <AlertDescription>{error}</AlertDescription>
        </Alert>
      )}

      {loading ? (
        <ListViewSkeleton columns={7} rows={5} toolbarButtons={1} />
      ) : (
        <DataTable
          columns={columns}
          data={relations}
          searchColumn="name"
          storageKey="authority-relations-sort"
          toolbarActions={
            canWrite && (
              <Button onClick={() => setCreateOpen(true)} className="gap-2 h-9">
                <Plus className="h-4 w-4" />
                New Authority Relation
              </Button>
            )
          }
          bulkActions={(selectedRows) => (
            <Button
              variant="destructive"
              size="sm"
              className="h-9 gap-1"
              onClick={() => handleBulkDelete(selectedRows.map((r) => r.id).filter(Boolean))}
            >
              <Trash2 className="w-4 h-4 mr-1" />
              Delete Selected ({selectedRows.length})
            </Button>
          )}
          onRowClick={(row) => navigate(`${pathname}/${row.original.id}`)}
        />
      )}

      <CreateAuthorityRelationDialog
        open={createOpen}
        onOpenChange={setCreateOpen}
        onCreated={(created) => {
          setCreateOpen(false);
          toast({ title: 'Authority Relation created', description: created.name });
          if (created.id) navigate(`${pathname}/${created.id}`);
          else fetchRelations();
        }}
      />

      <CreateAuthorityRelationDialog
        open={!!editRelation}
        onOpenChange={(o) => !o && setEditRelation(null)}
        relation={editRelation}
        onCreated={(updated) => {
          setEditRelation(null);
          toast({ title: 'Authority Relation updated', description: updated.name });
          fetchRelations();
        }}
      />
    </div>
  );
}
