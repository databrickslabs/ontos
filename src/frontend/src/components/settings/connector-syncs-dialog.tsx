import { useCallback, useEffect, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { Link } from 'react-router-dom';
import { Loader2, Play, Trash2 } from 'lucide-react';

import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from '@/components/ui/dialog';
import { Switch } from '@/components/ui/switch';
import { RelativeDate } from '@/components/common/relative-date';
import { useApi } from '@/hooks/use-api';
import { useToast } from '@/hooks/use-toast';
import { usePermissions } from '@/stores/permissions-store';
import { FeatureAccessLevel } from '@/types/settings';
import type { Connection } from '@/types/connections';
import type { ConnectorSync } from '@/types/connector-sync';

const STATUS_VARIANT: Record<string, 'secondary' | 'outline' | 'destructive'> = {
  completed: 'secondary',
  incomplete: 'outline',
  failed: 'destructive',
};

/** The connector syncs of a connection: schedule, last run, enable, run now, delete. */
export function ConnectorSyncsDialog({ connection, onOpenChange }: {
  connection: Connection | null;
  onOpenChange: (open: boolean) => void;
}) {
  const { t } = useTranslation(['settings', 'database-schema', 'common']);
  const { get, put, post, delete: apiDelete } = useApi();
  const { toast } = useToast();
  const { hasPermission } = usePermissions();
  const canWrite = hasPermission('schema-importer', FeatureAccessLevel.READ_WRITE);
  const [syncs, setSyncs] = useState<ConnectorSync[] | null>(null);
  const [busy, setBusy] = useState<string | null>(null);

  const load = useCallback(async () => {
    if (!connection) return;
    const res = await get<ConnectorSync[]>(`/api/connector-syncs?connection_id=${encodeURIComponent(connection.id)}`);
    setSyncs(res.data || []);
  }, [connection, get]);

  useEffect(() => {
    setSyncs(null);
    load();
  }, [load]);

  const replace = (updated: ConnectorSync) => setSyncs((prev) => (prev || []).map((s) => (s.id === updated.id ? updated : s)));

  const toggle = async (sync: ConnectorSync, enabled: boolean) => {
    setBusy(sync.id);
    const res = await put<ConnectorSync>(`/api/connector-syncs/${sync.id}`, { enabled });
    setBusy(null);
    if (res.data) {
      replace(res.data);
      if (res.data.job_warning) toast({ title: t('settings:connectors.syncs.jobWarningTitle'), description: res.data.job_warning });
    } else {
      toast({ title: t('settings:connectors.syncs.updateFailed'), description: res.error, variant: 'destructive' });
    }
  };

  const runNow = async (sync: ConnectorSync) => {
    setBusy(sync.id);
    const res = await post<{ job_run_id: number }>(`/api/connector-syncs/${sync.id}/run`, {});
    setBusy(null);
    if (res.error) {
      toast({ title: t('settings:connectors.syncs.runFailed'), description: res.error, variant: 'destructive' });
    } else {
      toast({ title: t('settings:connectors.syncs.runStarted', { name: sync.name }) });
    }
  };

  const remove = async (sync: ConnectorSync) => {
    setBusy(sync.id);
    const res = await apiDelete(`/api/connector-syncs/${sync.id}`);
    setBusy(null);
    if (res.error) {
      toast({ title: t('settings:connectors.syncs.deleteFailed'), description: res.error, variant: 'destructive' });
    } else {
      setSyncs((prev) => (prev || []).filter((s) => s.id !== sync.id));
    }
  };

  return (
    <Dialog open={!!connection} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-3xl">
        <DialogHeader>
          <DialogTitle>{t('settings:connectors.syncs.title', { name: connection?.name })}</DialogTitle>
          <DialogDescription>{t('settings:connectors.syncs.description')}</DialogDescription>
        </DialogHeader>

        {syncs === null ? (
          <div className="flex justify-center py-8"><Loader2 className="h-5 w-5 animate-spin" /></div>
        ) : syncs.length === 0 ? (
          <div className="py-6 text-center text-sm text-muted-foreground">{t('settings:connectors.syncs.none')}</div>
        ) : (
          <div className="divide-y rounded-md border">
            {syncs.map((sync) => (
              <div key={sync.id} className="flex flex-wrap items-center gap-3 p-3 text-sm" data-testid={`sync-${sync.id}`}>
                <div className="min-w-[200px] flex-1 space-y-1">
                  <div className="font-medium">{sync.name}</div>
                  <div className="text-xs text-muted-foreground">
                    {t(`database-schema:sync.intervals.${sync.interval_minutes}`, {
                      defaultValue: t('settings:connectors.syncs.everyMinutes', { count: sync.interval_minutes }),
                    })}
                    {' · '}
                    {t('settings:connectors.syncs.retireAfter', { count: sync.retire_after_misses })}
                  </div>
                  <div className="flex flex-wrap items-center gap-2 text-xs text-muted-foreground">
                    {sync.last_status ? (
                      <>
                        <Badge variant={STATUS_VARIANT[sync.last_status] || 'outline'} className="text-xs font-normal">
                          {t(`settings:connectors.syncs.status.${sync.last_status}`, { defaultValue: sync.last_status })}
                        </Badge>
                        {sync.last_run_at && <RelativeDate date={sync.last_run_at} />}
                        {sync.last_run_id && (
                          <Link to={`/schema-importer?runId=${sync.last_run_id}`} className="text-primary hover:underline">
                            {t('settings:connectors.syncs.lastRun')}
                          </Link>
                        )}
                      </>
                    ) : (
                      <span>{t('settings:connectors.syncs.neverRun')}</span>
                    )}
                    {sync.enabled && sync.next_due_at && (
                      <span>· {t('database-schema:sync.nextRun')} <RelativeDate date={sync.next_due_at} /></span>
                    )}
                  </div>
                </div>
                <Switch
                  checked={sync.enabled}
                  disabled={!canWrite || busy === sync.id}
                  onCheckedChange={(value) => toggle(sync, value)}
                  aria-label={t('settings:connectors.syncs.enabled')}
                />
                {canWrite && (
                  <>
                    <Button variant="outline" size="sm" onClick={() => runNow(sync)} disabled={busy === sync.id}>
                      <Play className="mr-1 h-3.5 w-3.5" />
                      {t('settings:connectors.syncs.runNow')}
                    </Button>
                    <Button
                      variant="ghost" size="sm" onClick={() => remove(sync)} disabled={busy === sync.id}
                      aria-label={t('common:delete')}
                    >
                      <Trash2 className="h-4 w-4" />
                    </Button>
                  </>
                )}
              </div>
            ))}
          </div>
        )}
      </DialogContent>
    </Dialog>
  );
}
