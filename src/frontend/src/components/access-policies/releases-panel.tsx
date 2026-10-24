import { useCallback, useEffect, useMemo, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { useTranslation } from 'react-i18next';
import { ColumnDef } from '@tanstack/react-table';
import { PackagePlus } from 'lucide-react';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { DataTable } from '@/components/ui/data-table';
import { useApi } from '@/hooks/use-api';
import { useToast } from '@/hooks/use-toast';
import ReleaseStatusBadge from '@/components/access-policies/release-status-badge';
import type { AccessRelease } from '@/types/access-policy';

/** Releases tab: compiled deployments of all active policies to a target, newest first. */
export default function ReleasesPanel({ canWrite }: { canWrite: boolean }) {
  const { t } = useTranslation(['access-policies', 'common']);
  const navigate = useNavigate();
  const { get, post } = useApi();
  const { toast } = useToast();
  const [rows, setRows] = useState<AccessRelease[]>([]);
  const [loading, setLoading] = useState(true);
  const [creating, setCreating] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    const res = await get<AccessRelease[]>('/api/access-policies/releases');
    setRows(Array.isArray(res.data) ? res.data : []);
    setLoading(false);
  }, [get]);

  useEffect(() => {
    load();
  }, [load]);

  const create = async () => {
    setCreating(true);
    const res = await post<AccessRelease>('/api/access-policies/releases', { target: 'uc' });
    setCreating(false);
    if (res.error || !res.data) {
      toast({ title: t('access-policies:releases.createFailed'), description: res.error || '', variant: 'destructive' });
      return;
    }
    navigate(`/access-policies/releases/${res.data.id}`);
  };

  const columns = useMemo<ColumnDef<AccessRelease>[]>(
    () => [
      {
        accessorKey: 'name',
        header: t('common:labels.name'),
        cell: ({ row }) => (
          <div>
            <div className="font-medium">{row.original.name}</div>
            {row.original.notes && <div className="line-clamp-1 text-xs text-muted-foreground">{row.original.notes}</div>}
          </div>
        ),
      },
      {
        accessorKey: 'status',
        header: t('common:labels.status'),
        cell: ({ row }) => <ReleaseStatusBadge status={row.original.status} />,
      },
      {
        accessorKey: 'release_kind',
        header: t('access-policies:list.type'),
        cell: ({ row }) => <Badge variant="outline">{t(`access-policies:releases.kind.${row.original.release_kind}`)}</Badge>,
      },
      {
        id: 'changes',
        header: t('access-policies:releases.changes'),
        cell: ({ row }) => {
          const c = row.original.counts;
          return (
            <span className="text-xs">
              <span className="text-emerald-700 dark:text-emerald-400">+{c.add}</span>{' '}
              <span className="text-red-700 dark:text-red-400">−{c.remove}</span>{' '}
              <span className="text-muted-foreground">~{c.update}</span>
              {c.errors > 0 && (
                <Badge variant="destructive" className="ml-2 text-[10px]">
                  {t('access-policies:releases.errorCount', { count: c.errors })}
                </Badge>
              )}
            </span>
          );
        },
      },
      {
        id: 'delivery',
        header: t('access-policies:releases.delivery'),
        cell: ({ row }) => (
          <span className="text-xs text-muted-foreground">
            {row.original.delivery_modes.map((m) => t(`access-policies:releases.modes.${m}`)).join(', ') || '—'}
          </span>
        ),
      },
      {
        accessorKey: 'created_at',
        header: t('access-policies:releases.created'),
        cell: ({ row }) => (
          <span className="text-xs text-muted-foreground">
            {new Date(row.original.created_at).toLocaleString()} · {row.original.created_by}
          </span>
        ),
      },
    ],
    [t],
  );

  return (
    <div>
      <p className="mb-3 text-sm text-muted-foreground">{t('access-policies:releases.hint')}</p>
      <DataTable
        columns={columns}
        data={rows}
        searchColumn="name"
        isLoading={loading}
        storageKey="access-policy-releases-list"
        onRowClick={(row) => navigate(`/access-policies/releases/${row.original.id}`)}
        toolbarActions={
          canWrite ? (
            <Button size="sm" onClick={create} disabled={creating}>
              <PackagePlus className="mr-1 h-4 w-4" /> {t('access-policies:releases.compile')}
            </Button>
          ) : null
        }
      />
    </div>
  );
}
