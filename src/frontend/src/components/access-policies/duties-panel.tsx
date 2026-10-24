import { useCallback, useEffect, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { CheckCircle2, CircleDashed } from 'lucide-react';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Textarea } from '@/components/ui/textarea';
import { useApi } from '@/hooks/use-api';
import { useToast } from '@/hooks/use-toast';
import type { DutyStatus } from '@/types/access-policy';

/**
 * Duties on an Agreement (ODRL preconditions of its permissions). The grantee accepts the terms
 * themself; other duties are fulfilled by an Access Policies admin. Once all are fulfilled, the
 * access compiles into grants (and ships right away when auto-delivery is enabled).
 */
export default function DutiesPanel({
  agreementId,
  initial,
  onChange,
}: {
  agreementId: string;
  initial?: DutyStatus[];
  onChange?: (duties: DutyStatus[]) => void;
}) {
  const { t } = useTranslation(['access-policies', 'common']);
  const { get, post } = useApi();
  const { toast } = useToast();
  const [duties, setDuties] = useState<DutyStatus[]>(initial || []);
  const [note, setNote] = useState('');
  const [busy, setBusy] = useState<string | null>(null);

  const load = useCallback(async () => {
    const res = await get<DutyStatus[]>(`/api/access-policies/policies/${agreementId}/duties`);
    if (Array.isArray(res.data)) setDuties(res.data);
  }, [agreementId, get]);

  useEffect(() => {
    if (!initial) load();
  }, [initial, load]);

  const label = (action: string) => duties.find((d) => d.action === action)?.label || action;

  const fulfil = async (action: string) => {
    setBusy(action);
    const res = await post<DutyStatus[]>(`/api/access-policies/policies/${agreementId}/duties/fulfill`, {
      action,
      note: note || undefined,
    });
    setBusy(null);
    if (res.error || !Array.isArray(res.data)) {
      toast({ title: t('access-policies:duties.failed'), description: res.error || '', variant: 'destructive' });
      return;
    }
    setDuties(res.data);
    setNote('');
    onChange?.(res.data);
    toast({ title: t('access-policies:duties.done', { duty: label(action) }) });
  };

  if (!duties.length) return null;
  const open = duties.filter((d) => !d.fulfilled);

  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-lg">{t('access-policies:duties.title')}</CardTitle>
        <CardDescription>
          {open.length ? t('access-policies:duties.openHint', { count: open.length }) : t('access-policies:duties.allDone')}
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-3">
        {duties.map((d) => (
          <div key={d.action} className="flex items-start justify-between gap-4 rounded-md border p-3">
            <div className="flex items-start gap-2">
              {d.fulfilled ? (
                <CheckCircle2 className="mt-0.5 h-4 w-4 text-emerald-600" />
              ) : (
                <CircleDashed className="mt-0.5 h-4 w-4 text-amber-600" />
              )}
              <div>
                <div className="font-medium">{d.label || d.action}</div>
                <div className="text-xs text-muted-foreground">
                  {d.fulfilled
                    ? t('access-policies:duties.fulfilledBy', {
                        who: d.fulfilled_by,
                        at: d.fulfilled_at ? new Date(d.fulfilled_at).toLocaleString() : '',
                      }) + (d.note ? ` — ${d.note}` : '')
                    : d.fulfilled_by_assignee_only
                      ? t('access-policies:duties.byGrantee')
                      : t('access-policies:duties.byAdmin')}
                </div>
              </div>
            </div>
            {!d.fulfilled && d.can_fulfill && (
              <Button size="sm" disabled={busy !== null} onClick={() => fulfil(d.action)}>
                {d.fulfilled_by_assignee_only ? t('access-policies:duties.accept') : t('access-policies:duties.markFulfilled')}
              </Button>
            )}
            {!d.fulfilled && !d.can_fulfill && (
              <Badge variant="outline" className="shrink-0">
                {t('access-policies:duties.open')}
              </Badge>
            )}
          </div>
        ))}
        {open.some((d) => d.can_fulfill) && (
          <Textarea
            rows={2}
            aria-label={t('access-policies:duties.note')}
            placeholder={t('access-policies:duties.note')}
            value={note}
            onChange={(e) => setNote(e.target.value)}
          />
        )}
      </CardContent>
    </Card>
  );
}
