import { useCallback, useEffect, useMemo, useState } from 'react';
import { Link } from 'react-router-dom';
import { useTranslation } from 'react-i18next';
import { ColumnDef } from '@tanstack/react-table';
import { TimerOff } from 'lucide-react';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { DataTable } from '@/components/ui/data-table';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import { useApi } from '@/hooks/use-api';
import { useToast } from '@/hooks/use-toast';
import type { AccessRelease, LedgerEntry } from '@/types/access-policy';

/** Grant Ledger tab: what Ontos applied and tracks, incl. expiry of time-bound grants. */
export default function GrantLedgerPanel({ canAdmin }: { canAdmin: boolean }) {
  const { t } = useTranslation(['access-policies', 'common']);
  const { get, post } = useApi();
  const { toast } = useToast();
  const [rows, setRows] = useState<LedgerEntry[]>([]);
  const [status, setStatus] = useState<LedgerEntry['status']>('active');
  const [loading, setLoading] = useState(true);
  const [revoking, setRevoking] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    const res = await get<LedgerEntry[]>(`/api/access-policies/ledger?status=${status}`);
    setRows(Array.isArray(res.data) ? res.data : []);
    setLoading(false);
  }, [get, status]);

  useEffect(() => {
    load();
  }, [load]);

  const expiredCount = rows.filter((r) => r.status === 'active' && r.expired).length;

  const revokeExpired = async () => {
    setRevoking(true);
    const res = await post<{ release: AccessRelease | null; revoked: unknown[] }>(
      '/api/access-policies/ledger/revoke-expired',
      { target: 'uc' },
    );
    setRevoking(false);
    if (res.error || !res.data) {
      toast({ title: t('access-policies:ledger.revokeFailed'), description: res.error || '', variant: 'destructive' });
      return;
    }
    const rel = res.data.release;
    toast({
      title: rel
        ? t('access-policies:ledger.revokeDone', { count: res.data.revoked.length, status: t(`access-policies:releases.status.${rel.status}`) })
        : t('access-policies:ledger.nothingExpired'),
    });
    load();
  };

  const columns = useMemo<ColumnDef<LedgerEntry>[]>(
    () => [
      { accessorKey: 'principal', header: t('access-policies:ledger.principal') },
      {
        accessorKey: 'securable_name',
        header: t('access-policies:ledger.securable'),
        cell: ({ row }) => (
          <span className="font-mono text-xs">
            <Badge variant="outline" className="mr-1 text-[10px]">
              {row.original.securable_type}
            </Badge>
            {row.original.securable_name}
          </span>
        ),
      },
      {
        accessorKey: 'privilege',
        header: t('access-policies:ledger.privilege'),
        cell: ({ row }) => (
          <span className="text-xs">
            {row.original.privilege.replace(/_/g, ' ')}
            {row.original.implied && (
              <Badge variant="secondary" className="ml-1 text-[10px]" title={t('access-policies:ledger.impliedTitle')}>
                {t('access-policies:ledger.implied')}
              </Badge>
            )}
            {row.original.preexisting && (
              <Badge variant="outline" className="ml-1 text-[10px]" title={t('access-policies:ledger.preexistingTitle')}>
                {t('access-policies:ledger.preexisting')}
              </Badge>
            )}
          </span>
        ),
      },
      {
        accessorKey: 'expires_at',
        header: t('access-policies:ledger.expires'),
        cell: ({ row }) =>
          row.original.expires_at ? (
            <span className={`text-xs ${row.original.expired ? 'font-semibold text-red-700 dark:text-red-400' : ''}`}>
              {new Date(row.original.expires_at).toLocaleString()}
              {row.original.expired && ` · ${t('access-policies:ledger.expired')}`}
            </span>
          ) : (
            <span className="text-xs text-muted-foreground">—</span>
          ),
      },
      {
        id: 'sources',
        header: t('access-policies:ledger.sources'),
        cell: ({ row }) => (
          <span className="text-xs text-muted-foreground">
            {(row.original.sources || []).map((s) => `${s.policy_name}${s.policy_version ? ` v${s.policy_version}` : ''}`).join(', ')}
          </span>
        ),
      },
      {
        id: 'release',
        header: t('access-policies:ledger.release'),
        cell: ({ row }) => {
          const id = row.original.status === 'active' ? row.original.granted_release_id : row.original.revoked_release_id;
          return id ? (
            <Link className="text-xs text-primary hover:underline" to={`/access-policies/releases/${id}`} onClick={(e) => e.stopPropagation()}>
              {t('access-policies:ledger.viewRelease')}
            </Link>
          ) : null;
        },
      },
    ],
    [t],
  );

  return (
    <div>
      <p className="mb-3 text-sm text-muted-foreground">{t('access-policies:ledger.hint')}</p>
      <DataTable
        columns={columns}
        data={rows}
        searchColumn="principal"
        isLoading={loading}
        storageKey="access-grant-ledger-list"
        toolbarActions={
          <div className="flex items-center gap-2">
            <Select value={status} onValueChange={(v) => setStatus(v as LedgerEntry['status'])}>
              <SelectTrigger className="h-8 w-[140px]" aria-label={t('common:labels.status')}>
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="active">{t('access-policies:ledger.statusActive')}</SelectItem>
                <SelectItem value="revoked">{t('access-policies:ledger.statusRevoked')}</SelectItem>
                <SelectItem value="released">{t('access-policies:ledger.statusReleased')}</SelectItem>
              </SelectContent>
            </Select>
            {canAdmin && status === 'active' && (
              <Button size="sm" variant={expiredCount ? 'destructive' : 'outline'} onClick={revokeExpired} disabled={revoking}>
                <TimerOff className="mr-1 h-4 w-4" /> {t('access-policies:ledger.revokeExpired', { count: expiredCount })}
              </Button>
            )}
          </div>
        }
      />
    </div>
  );
}
