import { useCallback, useEffect, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { Loader2, RefreshCw } from 'lucide-react';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { useApi } from '@/hooks/use-api';
import { useToast } from '@/hooks/use-toast';
import type { DriftGrant, DriftReport } from '@/types/access-policy';

const VARIANT = { in_sync: 'secondary', drift: 'destructive', partial: 'outline', error: 'outline' } as const;

function GrantList({ rows }: { rows: DriftGrant[] }) {
  return (
    <ul className="space-y-0.5 font-mono text-xs">
      {rows.slice(0, 50).map((g, i) => (
        <li key={i}>
          {g.principal} · {g.privilege.replace(/_/g, ' ')} · {g.securable_type} {g.securable_name}
        </li>
      ))}
    </ul>
  );
}

/** Report-only drift: the target's Grant Ledger vs live platform grants. */
export default function DriftPanel({ targetKey, canRun, readable }: { targetKey: string; canRun: boolean; readable: boolean }) {
  const { t } = useTranslation(['access-policies', 'common']);
  const { get, post } = useApi();
  const { toast } = useToast();
  const [reports, setReports] = useState<DriftReport[]>([]);
  const [latest, setLatest] = useState<DriftReport | null>(null);
  const [running, setRunning] = useState(false);

  const load = useCallback(
    async (isCurrent: () => boolean = () => true) => {
      try {
        const res = await get<DriftReport[]>(
          `/api/access-policies/drift-reports?target=${encodeURIComponent(targetKey)}&limit=10`,
        );
        const rows = Array.isArray(res.data) ? res.data : [];
        const full = rows[0] ? await get<DriftReport>(`/api/access-policies/drift-reports/${rows[0].id}`) : null;
        if (!isCurrent()) return; // another target's panel by now
        setReports(rows);
        setLatest(full?.data || null);
      } catch {
        if (isCurrent()) setLatest(null);
      }
    },
    [get, targetKey],
  );

  useEffect(() => {
    let current = true;
    load(() => current);
    return () => {
      current = false;
    };
  }, [load]);

  const run = async () => {
    setRunning(true);
    try {
      const res = await post<DriftReport>('/api/access-policies/drift-reports', { target: targetKey });
      if (res.error || !res.data) {
        toast({ title: t('access-policies:drift.failed'), description: res.error || '', variant: 'destructive' });
        return;
      }
      await load();
    } catch (e: any) {
      toast({ title: t('access-policies:drift.failed'), description: e?.message || '', variant: 'destructive' });
    } finally {
      setRunning(false);
    }
  };

  return (
    <Card data-testid="drift-panel">
      <CardHeader className="flex flex-row items-start justify-between space-y-0">
        <div>
          <CardTitle className="text-base">{t('access-policies:drift.title')}</CardTitle>
          <CardDescription>{readable ? t('access-policies:drift.hint') : t('access-policies:drift.unreadable')}</CardDescription>
        </div>
        {canRun && readable && (
          <Button size="sm" variant="outline" onClick={run} disabled={running}>
            {running ? <Loader2 className="mr-1 h-4 w-4 animate-spin" /> : <RefreshCw className="mr-1 h-4 w-4" />}
            {t('access-policies:drift.run')}
          </Button>
        )}
      </CardHeader>
      <CardContent className="space-y-3 text-sm">
        {!latest ? (
          <p className="text-muted-foreground">{t('access-policies:drift.none')}</p>
        ) : (
          <>
            <div className="flex flex-wrap items-center gap-2">
              <Badge variant={VARIANT[latest.status]}>{t(`access-policies:drift.status.${latest.status}`)}</Badge>
              <span className="text-xs text-muted-foreground">
                {new Date(latest.checked_at).toLocaleString()} · {latest.checked_by}
              </span>
              <span className="text-xs">
                {t('access-policies:drift.counts', {
                  missing: latest.counts.missing ?? 0,
                  unmanaged: latest.counts.unmanaged ?? 0,
                  tracked: latest.counts.tracked ?? 0,
                })}
              </span>
            </div>
            {!!latest.report?.missing.length && (
              <div>
                <div className="text-xs text-muted-foreground">{t('access-policies:drift.missing')}</div>
                <GrantList rows={latest.report.missing} />
              </div>
            )}
            {!!latest.report?.unmanaged.length && (
              <div>
                <div className="text-xs text-muted-foreground">{t('access-policies:drift.unmanaged')}</div>
                <GrantList rows={latest.report.unmanaged} />
              </div>
            )}
            {latest.report?.truncated && <p className="text-xs text-amber-700">{t('access-policies:drift.truncated')}</p>}
            {reports.length > 1 && (
              <div className="text-xs text-muted-foreground">
                {t('access-policies:drift.history')}:{' '}
                {reports
                  .slice(1)
                  .map((r) => `${new Date(r.checked_at).toLocaleDateString()} ${t(`access-policies:drift.status.${r.status}`)}`)
                  .join(' · ')}
              </div>
            )}
          </>
        )}
      </CardContent>
    </Card>
  );
}
