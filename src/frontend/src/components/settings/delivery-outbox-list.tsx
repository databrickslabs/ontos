import { useCallback, useEffect, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { Link } from 'react-router-dom';
import { Loader2, RefreshCw, Send } from 'lucide-react';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import {
  Table, TableBody, TableCell, TableHead, TableHeader, TableRow,
} from '@/components/ui/table';
import { useToast } from '@/hooks/use-toast';
import {
  DELIVERY_OUTBOX_REASON_CODES, outboxEntityPath,
  type DeliveryOutboxList as OutboxList, type DeliveryOutboxRow, type RedeliverResult,
} from '@/types/delivery-outbox';

const OUTBOX_URL = '/api/delivery/outbox';

type Translate = (key: string, options?: Record<string, unknown>) => string;

/** The translated reason of a coded outbox outcome; unknown codes read as a failure. */
export function outboxReasonText(code: string | null | undefined, t: Translate): string {
  const known = code && DELIVERY_OUTBOX_REASON_CODES.has(code) ? code : 'delivery_failed';
  return t(`settings:deliveryOutbox.reason.${known}`);
}

function formatDate(value: string | null | undefined, language: string): string {
  return value ? new Date(value).toLocaleString(language) : '';
}

/**
 * Changes committed in Ontos that a delivery mode hasn't delivered yet (#1688),
 * with "Deliver again" for an admin. Shown on Settings > Delivery Modes.
 */
export default function DeliveryOutboxList({ canWrite }: { canWrite: boolean }) {
  const { t, i18n } = useTranslation(['settings']);
  const { toast } = useToast();
  const [rows, setRows] = useState<DeliveryOutboxRow[]>([]);
  const [loading, setLoading] = useState(false);
  const [loadFailed, setLoadFailed] = useState(false);
  const [delivering, setDelivering] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const response = await fetch(OUTBOX_URL);
      if (!response.ok) throw new Error(String(response.status));
      const data: OutboxList = await response.json();
      setRows(data.rows ?? []);
      setLoadFailed(false);
    } catch {
      setLoadFailed(true);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  const deliverAgain = async (row: DeliveryOutboxRow) => {
    const key = `${row.entity_type}/${row.entity_id}`;
    setDelivering(key);
    try {
      const response = await fetch(
        `/api/delivery/${encodeURIComponent(row.entity_type)}/`
          + `${encodeURIComponent(row.entity_id)}/redeliver`,
        { method: 'POST' },
      );
      const body = await response.json().catch(() => null);
      if (!response.ok) {
        const code = body?.detail && typeof body.detail === 'object' ? body.detail.code : null;
        toast({
          title: t('settings:deliveryOutbox.result.refused'),
          description: outboxReasonText(code, t),
          variant: 'destructive',
        });
        return;
      }
      const delivery = (body as RedeliverResult | null)?.delivery;
      const status = delivery?.status ?? 'pending';
      toast({
        title: t(`settings:deliveryOutbox.result.${status}`, {
          reason: outboxReasonText(delivery?.code, t),
        }),
        variant: status === 'failed' ? 'destructive' : 'default',
      });
    } catch {
      toast({ title: t('settings:deliveryOutbox.result.refused'), variant: 'destructive' });
    } finally {
      setDelivering(null);
      await load();
    }
  };

  const changeText = (change: string) =>
    t(`settings:deliveryOutbox.change.${change}`, { defaultValue: change });

  return (
    <div className="space-y-3" data-testid="delivery-outbox">
      <div className="flex items-start justify-between gap-4">
        <div className="space-y-0.5">
          <h2 className="text-base font-medium">{t('settings:deliveryOutbox.title')}</h2>
          <p className="text-sm text-muted-foreground">
            {t('settings:deliveryOutbox.description', { max: rows[0]?.max_attempts ?? 5 })}
          </p>
        </div>
        <Button variant="outline" size="sm" onClick={load} disabled={loading}>
          <RefreshCw className={`mr-2 h-4 w-4 ${loading ? 'animate-spin' : ''}`} />
          {t('settings:deliveryOutbox.refresh')}
        </Button>
      </div>
      {loadFailed ? (
        <p className="text-sm text-destructive">{t('settings:deliveryOutbox.loadError')}</p>
      ) : rows.length === 0 ? (
        <p className="text-sm text-muted-foreground">
          {loading ? '' : t('settings:deliveryOutbox.empty')}
        </p>
      ) : (
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>{t('settings:deliveryOutbox.columns.entity')}</TableHead>
              <TableHead>{t('settings:deliveryOutbox.columns.change')}</TableHead>
              <TableHead>{t('settings:deliveryOutbox.columns.mode')}</TableHead>
              <TableHead>{t('settings:deliveryOutbox.columns.status')}</TableHead>
              <TableHead>{t('settings:deliveryOutbox.columns.reason')}</TableHead>
              <TableHead>{t('settings:deliveryOutbox.columns.attempts')}</TableHead>
              <TableHead>{t('settings:deliveryOutbox.columns.nextAttempt')}</TableHead>
              {canWrite && <TableHead />}
            </TableRow>
          </TableHeader>
          <TableBody>
            {rows.map((row) => {
              const path = outboxEntityPath(row);
              const name = row.entity_name || t('settings:deliveryOutbox.deletedEntity');
              const key = `${row.entity_type}/${row.entity_id}`;
              return (
                <TableRow key={row.id}>
                  <TableCell>
                    {path && row.entity_name ? (
                      <Link to={path} className="text-primary hover:underline">{name}</Link>
                    ) : name}
                  </TableCell>
                  <TableCell>{changeText(row.change_type)}</TableCell>
                  <TableCell>
                    {t(`settings:deliveryOutbox.mode.${row.mode}`, { defaultValue: row.mode })}
                  </TableCell>
                  <TableCell>
                    <Badge variant={row.status === 'failed' ? 'destructive' : 'secondary'}>
                      {t(`settings:deliveryOutbox.status.${row.status}`)}
                    </Badge>
                  </TableCell>
                  <TableCell className="max-w-xs text-sm">
                    {row.code ? outboxReasonText(row.code, t) : ''}
                  </TableCell>
                  <TableCell>
                    {t('settings:deliveryOutbox.attempts', {
                      attempts: row.attempts, max: row.max_attempts,
                    })}
                  </TableCell>
                  <TableCell className="text-sm">
                    {row.status === 'failed'
                      ? t('settings:deliveryOutbox.noRetry')
                      : formatDate(row.next_attempt_at, i18n.language)}
                  </TableCell>
                  {canWrite && (
                    <TableCell className="text-right">
                      <Button
                        size="sm"
                        variant="outline"
                        disabled={delivering !== null}
                        onClick={() => deliverAgain(row)}
                      >
                        {delivering === key ? (
                          <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                        ) : (
                          <Send className="mr-2 h-4 w-4" />
                        )}
                        {t('settings:deliveryOutbox.deliverAgain')}
                      </Button>
                    </TableCell>
                  )}
                </TableRow>
              );
            })}
          </TableBody>
        </Table>
      )}
    </div>
  );
}
