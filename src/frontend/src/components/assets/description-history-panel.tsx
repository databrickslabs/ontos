import { useCallback, useEffect, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { History, Loader2 } from 'lucide-react';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { RelativeDate } from '@/components/common/relative-date';
import { useApi } from '@/hooks/use-api';
import { useToast } from '@/hooks/use-toast';
import { descriptionSyncText } from '@/components/assets/description-sync-notice';
import type {
  AssetDescriptionHistory, AssetDescriptionHistoryEntry, AssetUpdateResult,
} from '@/types/asset';

const PREFIX = 'assets:descriptionHistory';
const PAGE_SIZE = 5;

/** Asset types whose description changes are kept (a table, a view or a column). */
const HISTORY_TYPES = ['table', 'view', 'column'];

export function hasDescriptionHistory(assetTypeName?: string | null): boolean {
  return HISTORY_TYPES.includes((assetTypeName ?? '').trim().toLowerCase());
}

interface Props {
  assetId: string;
  /** The description the asset has now: a version equal to it can't be restored. */
  currentDescription?: string | null;
  canRestore: boolean;
  /** Changes when the asset was saved, so the list is read again. */
  refreshKey?: string | null;
  /** Called after a description was restored, so the asset is read again. */
  onRestored: () => void;
}

const same = (a?: string | null, b?: string | null) => (a || null) === (b || null);

function Version({ title, text }: { title: string; text?: string | null }) {
  const { t } = useTranslation(['assets']);
  return (
    <div className="min-w-0 flex-1 space-y-1">
      <div className="text-xs font-medium text-muted-foreground">{title}</div>
      <div
        className={
          'max-h-32 overflow-auto whitespace-pre-wrap break-words rounded-md border '
          + 'bg-muted/40 p-2 text-sm'
        }
      >
        {text || <span className="italic text-muted-foreground">{t(`${PREFIX}.empty`)}</span>}
      </div>
    </div>
  );
}

/**
 * Who changed the description of a table, view or column, when, and from where, with the text
 * before and after. Restoring a version is a normal edit of the description (it is in the
 * history again, with the source "restore").
 */
export function DescriptionHistoryPanel({
  assetId, currentDescription, canRestore, refreshKey, onRestored,
}: Props) {
  const { t } = useTranslation(['assets', 'common']);
  const { get, post } = useApi();
  const { toast } = useToast();
  const [items, setItems] = useState<AssetDescriptionHistoryEntry[]>([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [restoring, setRestoring] = useState<string | null>(null);

  const load = useCallback(async (skip: number) => {
    setLoading(true);
    const res = await get<AssetDescriptionHistory>(
      `/api/assets/${assetId}/description/history?skip=${skip}&limit=${PAGE_SIZE}`
    );
    if (res.error || !res.data) {
      setError(res.error || t(`${PREFIX}.loadError`));
    } else {
      setError(null);
      setTotal(res.data.total);
      setItems((previous) => (skip === 0 ? res.data.items : [...previous, ...res.data.items]));
    }
    setLoading(false);
  }, [assetId, get, t]);

  useEffect(() => {
    void load(0);
  }, [load, refreshKey]);

  const restore = async (entry: AssetDescriptionHistoryEntry, version: 'after' | 'before') => {
    const key = `${entry.id}:${version}`;
    setRestoring(key);
    try {
      const res = await post<AssetUpdateResult>(
        `/api/assets/${assetId}/description/restore`, { entry_id: entry.id, version }
      );
      if (res.error || !res.data) {
        toast({
          title: t(`${PREFIX}.restoreFailed`),
          description: String(t(`${PREFIX}.errors.${res.errorCode}`, {
            ...(res.errorParams ?? {}), defaultValue: res.error ?? '',
          })),
          variant: 'destructive',
        });
        return;
      }
      const warning = res.data.warnings?.[0];
      toast({
        title: t(`${PREFIX}.restored`),
        description: warning ? descriptionSyncText(t, warning) : undefined,
      });
      onRestored();
    } finally {
      setRestoring(null);
    }
  };

  return (
    <Card data-testid="asset-description-history">
      <CardHeader className="pb-3">
        <CardTitle className="flex items-center gap-2 text-base">
          <History className="h-4 w-4" />
          {t(`${PREFIX}.title`)}
          {total > 0 && <Badge variant="secondary">{total}</Badge>}
        </CardTitle>
      </CardHeader>
      <CardContent className="space-y-4">
        {error && <p role="alert" className="text-sm text-red-700 dark:text-red-400">{error}</p>}
        {!error && !loading && items.length === 0 && (
          <p className="text-sm text-muted-foreground">{t(`${PREFIX}.none`)}</p>
        )}
        {items.map((entry) => (
          <div key={entry.id} className="space-y-2 border-b pb-4 last:border-b-0 last:pb-0">
            <div className="flex flex-wrap items-center gap-2 text-sm">
              <span className="font-medium">{entry.username || t(`${PREFIX}.unknownUser`)}</span>
              <span className="text-muted-foreground"><RelativeDate date={entry.timestamp} /></span>
              <Badge variant="outline" className="text-xs">
                {t(`${PREFIX}.sources.${entry.source}`, { defaultValue: entry.source ?? '' })}
              </Badge>
            </div>
            <div className="flex flex-col gap-3 sm:flex-row">
              <Version title={t(`${PREFIX}.before`)} text={entry.before} />
              <Version title={t(`${PREFIX}.after`)} text={entry.after} />
            </div>
            {canRestore && (
              <div className="flex flex-wrap gap-2">
                <Button
                  size="sm" variant="outline"
                  disabled={restoring !== null || same(entry.after, currentDescription)}
                  onClick={() => restore(entry, 'after')}
                >
                  {restoring === `${entry.id}:after` && (
                    <Loader2 className="mr-2 h-3 w-3 animate-spin" />
                  )}
                  {t(`${PREFIX}.restoreAfter`)}
                </Button>
                <Button
                  size="sm" variant="outline"
                  disabled={restoring !== null || same(entry.before, currentDescription)}
                  onClick={() => restore(entry, 'before')}
                >
                  {restoring === `${entry.id}:before` && (
                    <Loader2 className="mr-2 h-3 w-3 animate-spin" />
                  )}
                  {t(`${PREFIX}.restoreBefore`)}
                </Button>
              </div>
            )}
          </div>
        ))}
        {loading && (
          <div className="flex items-center gap-2 text-sm text-muted-foreground" role="status">
            <Loader2 className="h-4 w-4 animate-spin" /> {t(`${PREFIX}.loading`)}
          </div>
        )}
        {!loading && items.length < total && (
          <Button size="sm" variant="ghost" onClick={() => load(items.length)}>
            {t(`${PREFIX}.showMore`, { count: total - items.length })}
          </Button>
        )}
      </CardContent>
    </Card>
  );
}
