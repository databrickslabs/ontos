import { useCallback, useEffect, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { AlertTriangle, ExternalLink, Loader2, RefreshCcw } from 'lucide-react';

import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Label } from '@/components/ui/label';
import { Switch } from '@/components/ui/switch';
import { RelativeDate } from '@/components/common/relative-date';
import { useApi } from '@/hooks/use-api';
import { useToast } from '@/hooks/use-toast';

export const DASHBOARD_TYPE = 'Dashboard';

export interface SnapshotState {
  status?: string;
  document_id?: string | null;
  captured_at?: string;
  source?: string | null;
  error?: string | null;
  risks?: string[];
}

interface SnapshotResponse {
  snapshot: SnapshotState;
  opt_out: boolean;
  supported: boolean;
}

const OK_STATUS = 'ok';

/** Visual preview of a BI dashboard: the stored snapshot, its freshness, refresh and opt-out. */
export default function DashboardSnapshotCard({ assetId, assetTypeName, dashboardUrl, canWrite }: {
  assetId: string;
  assetTypeName?: string | null;
  dashboardUrl?: string | null;
  canWrite: boolean;
}) {
  const { t } = useTranslation('assets');
  const { get, post, put } = useApi();
  const { toast } = useToast();
  const [data, setData] = useState<SnapshotResponse | null>(null);
  const [refreshing, setRefreshing] = useState(false);
  const isDashboard = assetTypeName === DASHBOARD_TYPE;

  const load = useCallback(async () => {
    const res = await get<SnapshotResponse>(`/api/assets/${assetId}/snapshot`);
    if (res.data) setData(res.data);
  }, [assetId, get]);

  useEffect(() => {
    if (isDashboard) load();
  }, [isDashboard, load]);

  if (!isDashboard || !data) return null;
  const { snapshot, opt_out: optOut, supported } = data;
  if (!supported && !snapshot.document_id) return null;

  const status = snapshot.status || 'none';
  const refresh = async () => {
    setRefreshing(true);
    const res = await post<SnapshotResponse>(`/api/assets/${assetId}/snapshot`, {});
    setRefreshing(false);
    if (res.error || !res.data) {
      toast({ title: t('snapshot.refreshFailed'), description: res.error, variant: 'destructive' });
      return;
    }
    setData(res.data);
  };
  const toggleOptOut = async (value: boolean) => {
    const res = await put<SnapshotResponse>(`/api/assets/${assetId}/snapshot/settings`, { opt_out: value });
    if (res.data) setData(res.data);
  };

  return (
    <Card>
      <CardHeader className="pb-3">
        <CardTitle className="text-base flex items-center gap-2">
          {t('snapshot.title')}
          <Badge variant={status === OK_STATUS ? 'secondary' : 'outline'} className="text-xs font-normal">
            {t(`snapshot.status.${status}`, { defaultValue: status })}
          </Badge>
        </CardTitle>
        <CardDescription>{t('snapshot.rlsNotice')}</CardDescription>
      </CardHeader>
      <CardContent className="space-y-3">
        {snapshot.document_id ? (
          <a href={`/api/documents/${snapshot.document_id}/content`} target="_blank" rel="noreferrer">
            <img
              src={`/api/documents/${snapshot.document_id}/content?v=${encodeURIComponent(snapshot.captured_at || '')}`}
              alt={t('snapshot.imageAlt')}
              className="max-h-[420px] w-auto rounded-md border"
            />
          </a>
        ) : (
          <div className="text-sm text-muted-foreground">{t('snapshot.none')}</div>
        )}

        {snapshot.source === 'preview_image' && (
          <div className="text-xs text-muted-foreground">{t('snapshot.thumbnailNotice')}</div>
        )}
        {snapshot.error && status !== OK_STATUS && (
          <div className="text-xs text-muted-foreground break-words">{snapshot.error}</div>
        )}
        {(snapshot.risks?.length ?? 0) > 0 && (
          <div className="flex gap-2 rounded-md border border-amber-500/40 bg-amber-500/5 p-2 text-xs">
            <AlertTriangle className="h-4 w-4 shrink-0 text-amber-600" />
            <div>
              <div className="font-medium">{t('snapshot.risksTitle')}</div>
              <ul className="list-disc pl-4">{snapshot.risks!.map(r => <li key={r}>{r}</li>)}</ul>
            </div>
          </div>
        )}

        <div className="flex flex-wrap items-center gap-3 text-sm">
          {snapshot.captured_at && (
            <span className="text-muted-foreground">
              {t('snapshot.capturedAt')} <RelativeDate date={snapshot.captured_at} />
            </span>
          )}
          {dashboardUrl && (
            <a href={dashboardUrl} target="_blank" rel="noreferrer" className="inline-flex items-center gap-1 text-primary hover:underline">
              <ExternalLink className="h-3.5 w-3.5" />{t('snapshot.openLive')}
            </a>
          )}
          {canWrite && supported && (
            <Button variant="outline" size="sm" onClick={refresh} disabled={refreshing || optOut}>
              {refreshing ? <Loader2 className="mr-2 h-4 w-4 animate-spin" /> : <RefreshCcw className="mr-2 h-4 w-4" />}
              {t('snapshot.refresh')}
            </Button>
          )}
          {canWrite && (
            <div className="flex items-center gap-2">
              <Switch id={`snapshot-opt-out-${assetId}`} checked={optOut} onCheckedChange={toggleOptOut} />
              <Label htmlFor={`snapshot-opt-out-${assetId}`} className="text-sm">{t('snapshot.optOut')}</Label>
            </div>
          )}
        </div>
      </CardContent>
    </Card>
  );
}
