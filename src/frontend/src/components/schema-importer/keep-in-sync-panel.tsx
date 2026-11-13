import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { CheckCircle2, Loader2, RefreshCcw } from 'lucide-react';

import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import { RelativeDate } from '@/components/common/relative-date';
import { useApi } from '@/hooks/use-api';
import { useToast } from '@/hooks/use-toast';
import type { ImportDepth } from '@/types/schema-import';
import {
  DEFAULT_RETIRE_AFTER, DEFAULT_SYNC_INTERVAL, SYNC_INTERVALS,
  type ConnectorSync, type ConnectorSyncCreate,
} from '@/types/connector-sync';

interface Props {
  connectionId: string;
  selectedPaths: string[];
  depth: ImportDepth;
  excludedPaths: string[];
  defaultName: string;
}

/** After an import: save the selection as a connector sync the scheduled job imports again. */
export default function KeepInSyncPanel({ connectionId, selectedPaths, depth, excludedPaths, defaultName }: Props) {
  const { t } = useTranslation(['database-schema', 'common']);
  const { post } = useApi();
  const { toast } = useToast();
  const [open, setOpen] = useState(false);
  const [name, setName] = useState(defaultName);
  const [interval, setInterval] = useState<number>(DEFAULT_SYNC_INTERVAL);
  const [retireAfter, setRetireAfter] = useState<number>(DEFAULT_RETIRE_AFTER);
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState<ConnectorSync | null>(null);

  if (!connectionId || selectedPaths.length === 0) return null;

  const save = async () => {
    setSaving(true);
    const body: ConnectorSyncCreate = {
      name: name.trim() || defaultName,
      connection_id: connectionId,
      selected_paths: selectedPaths,
      depth,
      excluded_paths: excludedPaths,
      interval_minutes: interval,
      retire_after_misses: Math.max(1, retireAfter || DEFAULT_RETIRE_AFTER),
    };
    const res = await post<ConnectorSync>('/api/connector-syncs', body);
    setSaving(false);
    if (res.error || !res.data) {
      toast({ title: t('database-schema:sync.saveFailed'), description: res.error, variant: 'destructive' });
      return;
    }
    setSaved(res.data);
  };

  if (saved) {
    return (
      <div className="rounded-md border p-3 text-sm space-y-1" data-testid="keep-in-sync-saved">
        <div className="flex items-center gap-2 font-medium">
          <CheckCircle2 className="h-4 w-4 text-green-600" />
          {t('database-schema:sync.saved', { name: saved.name })}
        </div>
        {saved.next_due_at && (
          <div className="text-xs text-muted-foreground">
            {t('database-schema:sync.nextRun')} <RelativeDate date={saved.next_due_at} />
          </div>
        )}
        {saved.job_warning && <div className="text-xs text-amber-700">{saved.job_warning}</div>}
      </div>
    );
  }

  if (!open) {
    return (
      <Button variant="outline" size="sm" onClick={() => setOpen(true)}>
        <RefreshCcw className="mr-2 h-4 w-4" />
        {t('database-schema:sync.keepInSync')}
      </Button>
    );
  }

  return (
    <div className="rounded-md border p-3 space-y-3">
      <div>
        <div className="text-sm font-medium">{t('database-schema:sync.keepInSync')}</div>
        <div className="text-xs text-muted-foreground">{t('database-schema:sync.description')}</div>
      </div>
      <div className="grid grid-cols-1 md:grid-cols-3 gap-3">
        <div className="space-y-1 md:col-span-3">
          <Label htmlFor="sync-name">{t('common:labels.name')}</Label>
          <Input id="sync-name" value={name} onChange={(e) => setName(e.target.value)} />
        </div>
        <div className="space-y-1">
          <Label>{t('database-schema:sync.interval')}</Label>
          <Select value={String(interval)} onValueChange={(v) => setInterval(Number(v))}>
            <SelectTrigger aria-label={t('database-schema:sync.interval')}><SelectValue /></SelectTrigger>
            <SelectContent>
              {SYNC_INTERVALS.map((minutes) => (
                <SelectItem key={minutes} value={String(minutes)}>
                  {t(`database-schema:sync.intervals.${minutes}`)}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>
        <div className="space-y-1 md:col-span-2">
          <Label htmlFor="sync-retire-after">{t('database-schema:sync.retireAfter')}</Label>
          <Input
            id="sync-retire-after" type="number" min={1} max={100} value={retireAfter}
            onChange={(e) => setRetireAfter(Number(e.target.value))}
          />
          <div className="text-xs text-muted-foreground">{t('database-schema:sync.retireAfterHint')}</div>
        </div>
      </div>
      <div className="flex justify-end gap-2">
        <Button variant="ghost" size="sm" onClick={() => setOpen(false)} disabled={saving}>
          {t('common:actions.cancel')}
        </Button>
        <Button size="sm" onClick={save} disabled={saving}>
          {saving && <Loader2 className="mr-2 h-4 w-4 animate-spin" />}
          {t('database-schema:sync.save')}
        </Button>
      </div>
    </div>
  );
}
