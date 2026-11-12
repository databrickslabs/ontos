import { useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { useTranslation } from 'react-i18next';
import type { Column, ColumnDef } from '@tanstack/react-table';
import { useApi } from '@/hooks/use-api';
import { usePermissions } from '@/stores/permissions-store';
import { FeatureAccessLevel } from '@/types/settings';
import { useToast } from '@/hooks/use-toast';
import { Button } from '@/components/ui/button';
import { Alert, AlertDescription } from '@/components/ui/alert';
import { DataTable } from '@/components/ui/data-table';
import { ListViewSkeleton } from '@/components/common/list-view-skeleton';
import { VersionCountBadge } from '@/components/common/version-count-badge';
import { AlertCircle, ChevronDown, Eye, Plus, ScrollText, Trash2 } from 'lucide-react';
import AuthorityNav from '@/components/authority-resolution/authority-nav';
import AuthorityPolicyDialog from '@/components/authority-resolution/authority-policy-dialog';
import { PolicyStatusBadge } from '@/components/authority-resolution/policy-citation-view';
import useBreadcrumbStore from '@/stores/breadcrumb-store';
import type { AuthorityPolicy } from '@/types/authority-resolution';

const FEATURE_ID = 'authority-resolution';

export const formatDay = (iso?: string | null) => (iso ? iso.slice(0, 10) : '—');

export default function AuthorityPolicies() {
  const { t } = useTranslation(['authority-resolution', 'common']);
  const navigate = useNavigate();
  const { toast } = useToast();
  const { get, delete: del } = useApi();
  const { hasPermission, isLoading: permissionsLoading } = usePermissions();
  const canWrite = !permissionsLoading && hasPermission(FEATURE_ID, FeatureAccessLevel.READ_WRITE);

  const [policies, setPolicies] = useState<AuthorityPolicy[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [createOpen, setCreateOpen] = useState(false);

  const [reloadKey, setReloadKey] = useState(0);
  const fetchPolicies = () => setReloadKey((k) => k + 1);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      const { data, error } = await get<AuthorityPolicy[]>('/api/authority/policies');
      if (cancelled) return;
      setError(error || null);
      setPolicies(!error && Array.isArray(data) ? data : []);
      setLoading(false);
    })();
    return () => { cancelled = true; };
  }, [get, reloadKey]);

  const setStaticSegments = useBreadcrumbStore((s) => s.setStaticSegments);
  const setDynamicTitle = useBreadcrumbStore((s) => s.setDynamicTitle);
  useEffect(() => {
    setStaticSegments([{ label: t('title.main'), path: '/authority-resolution' }]);
    setDynamicTitle(t('policy.list.title'));
    return () => { setStaticSegments([]); setDynamicTitle(null); };
  }, [setStaticSegments, setDynamicTitle, t]);

  const remove = async (p: AuthorityPolicy) => {
    if (!confirm(t('policy.list.confirmDelete', { key: p.policy_key, version: p.version }))) return;
    const { error } = await del(`/api/authority/policies/${p.id}`);
    if (error) toast({ title: t('common:toast.error'), description: error, variant: 'destructive' });
    else { toast({ title: t('common:toast.deleted'), description: p.title }); fetchPolicies(); }
  };

  const sortableHeader = (label: string) => function SortHeader({ column }: { column: Column<AuthorityPolicy> }) {
    return (
      <Button variant="ghost" onClick={() => column.toggleSorting(column.getIsSorted() === 'asc')}>
        {label}
        <ChevronDown className="ml-2 h-4 w-4" />
      </Button>
    );
  };

  const columns: ColumnDef<AuthorityPolicy>[] = [
    {
      accessorKey: 'title',
      header: sortableHeader(t('policy.fields.title')),
      cell: ({ row }) => (
        <div className="space-y-1">
          <div className="font-medium">{row.original.title}</div>
          <div className="text-xs text-muted-foreground font-mono">{row.original.policy_key}</div>
        </div>
      ),
    },
    {
      accessorKey: 'policy_type',
      header: sortableHeader(t('policy.fields.type')),
      cell: ({ row }) => <span className="text-sm">{t(`policy.type.${row.original.policy_type}`)}</span>,
    },
    {
      accessorKey: 'status',
      header: sortableHeader(t('common:labels.status')),
      cell: ({ row }) => <PolicyStatusBadge status={row.original.status} />,
    },
    {
      accessorKey: 'version',
      header: t('common:labels.version'),
      cell: ({ row }) => (
        <div className="flex items-center gap-1.5">
          <span className="text-sm">v{row.original.version}</span>
          <VersionCountBadge count={row.original.version_count ?? undefined}
                             onClick={() => navigate(`/authority-resolution/policies/${row.original.id}`)} />
        </div>
      ),
      enableSorting: false,
    },
    {
      accessorKey: 'effective_from',
      header: sortableHeader(t('policy.fields.effective')),
      cell: ({ row }) => (
        <span className="text-sm text-muted-foreground">
          {formatDay(row.original.effective_from)} → {row.original.effective_to ? formatDay(row.original.effective_to) : t('policy.openEnded')}
        </span>
      ),
    },
    {
      accessorKey: 'dependent_count',
      header: sortableHeader(t('policy.list.columnCitedBy')),
      cell: ({ row }) => <div className="text-right">{row.original.dependent_count ?? 0}</div>,
    },
    {
      id: 'actions',
      enableHiding: false,
      cell: ({ row }) => (
        <div className="flex space-x-1 justify-end">
          <Button variant="ghost" size="icon" title={t('common:actions.view')}
                  onClick={(e) => { e.stopPropagation(); navigate(`/authority-resolution/policies/${row.original.id}`); }}>
            <Eye className="h-4 w-4" />
          </Button>
          {canWrite && (row.original.status === 'draft' || row.original.status === 'withdrawn') && (
            <Button variant="ghost" size="icon" className="text-destructive hover:text-destructive" title={t('common:actions.delete')}
                    onClick={(e) => { e.stopPropagation(); remove(row.original); }}>
              <Trash2 className="h-4 w-4" />
            </Button>
          )}
        </div>
      ),
    },
  ];

  return (
    <div className="py-6">
      <h1 className="text-3xl font-bold mb-6 flex items-center gap-2">
        <ScrollText className="w-8 h-8" />
        {t('policy.list.title')}
      </h1>
      <AuthorityNav current="policies" />
      <p className="text-muted-foreground mb-6 max-w-3xl">{t('policy.list.description')}</p>

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
          data={policies}
          searchColumn="title"
          storageKey="authority-policies-sort"
          toolbarActions={canWrite && (
            <Button onClick={() => setCreateOpen(true)} className="gap-2 h-9">
              <Plus className="h-4 w-4" />
              {t('policy.list.buttonNew')}
            </Button>
          )}
          onRowClick={(row) => navigate(`/authority-resolution/policies/${row.original.id}`)}
        />
      )}

      <AuthorityPolicyDialog
        open={createOpen}
        onOpenChange={setCreateOpen}
        onSaved={(created) => {
          setCreateOpen(false);
          toast({ title: t('common:toast.created'), description: created.title });
          navigate(`/authority-resolution/policies/${created.id}`);
        }}
      />
    </div>
  );
}
