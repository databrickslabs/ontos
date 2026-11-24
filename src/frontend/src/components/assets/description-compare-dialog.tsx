import { useCallback, useEffect, useMemo, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { AlertTriangle, Loader2 } from 'lucide-react';
import {
  Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle,
} from '@/components/ui/dialog';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Checkbox } from '@/components/ui/checkbox';
import { useApi } from '@/hooks/use-api';
import { useToast } from '@/hooks/use-toast';
import { descriptionResetText } from '@/components/assets/description-reset-dialog';
import type {
  AssetDescriptionDrift, AssetDriftField, AssetResetFieldResult, AssetResetSelectedResult,
} from '@/types/asset';

const PREFIX = 'assets:descriptionDrift';

interface Props {
  assetId: string;
  open: boolean;
  onOpenChange: (open: boolean) => void;
  /** Called after descriptions were replaced, so the asset is read again. */
  onReset: () => void;
}

interface LoadError {
  code?: string | null;
  message?: string | null;
  params?: Record<string, unknown> | null;
}

/** A field the user can reset: it differs, still exists in Unity Catalog and has a comment. */
const selectable = (field: AssetDriftField) =>
  field.differs && !field.missing_in_uc && !!field.uc_comment;

function Cell({ text }: { text?: string | null }) {
  const { t } = useTranslation(['assets']);
  return (
    <div className="max-h-24 overflow-auto whitespace-pre-wrap break-words text-sm">
      {text || <span className="italic text-muted-foreground">{t(`${PREFIX}.empty`)}</span>}
    </div>
  );
}

/**
 * Compares a table or view and its columns with Unity Catalog (one read as the user) and resets
 * the selected descriptions to their comments in one request. Nothing is selected at first: a
 * reset replaces what was written in Ontos. A field whose comment changed after it was shown, or
 * whose column is gone, is reported and the others still apply.
 */
export function DescriptionCompareDialog({ assetId, open, onOpenChange, onReset }: Props) {
  const { t } = useTranslation(['assets', 'common']);
  const { get, post } = useApi();
  const { toast } = useToast();
  const [drift, setDrift] = useState<AssetDescriptionDrift | null>(null);
  const [loading, setLoading] = useState(false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<LoadError | null>(null);
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [failures, setFailures] = useState<AssetResetFieldResult[]>([]);

  const load = useCallback(async () => {
    setLoading(true);
    const res = await get<AssetDescriptionDrift>(`/api/assets/${assetId}/description/drift`);
    if (res.error || !res.data) {
      setDrift(null);
      setError({ code: res.errorCode, message: res.error, params: res.errorParams });
    } else {
      setDrift(res.data);
      setError(null);
    }
    setSelected(new Set());
    setLoading(false);
  }, [assetId, get]);

  useEffect(() => {
    if (!open) return;
    setFailures([]);
    void load();
  }, [open, load]);

  const rows = useMemo(
    () => (drift?.fields ?? []).filter((f) => f.differs && !f.missing_in_uc),
    [drift],
  );
  const choices = rows.filter(selectable);
  const nameOf = (id: string) => drift?.fields.find((f) => f.asset_id === id)?.name ?? id;

  const toggle = (id: string, on: boolean) =>
    setSelected((previous) => {
      const next = new Set(previous);
      if (on) next.add(id); else next.delete(id);
      return next;
    });

  const confirm = async () => {
    if (!drift || selected.size === 0) return;
    setSaving(true);
    try {
      const fields = rows.filter((f) => selected.has(f.asset_id)).map((f) => ({
        asset_id: f.asset_id, expected_uc_comment: f.uc_comment ?? null,
      }));
      const res = await post<AssetResetSelectedResult>(
        `/api/assets/${assetId}/description/reset-selected`, { fields },
      );
      if (res.error || !res.data) {
        setError({ code: res.errorCode, message: res.error, params: res.errorParams });
        return;
      }
      const failed = res.data.results.filter((r) => r.error);
      toast({
        title: t(`${PREFIX}.toast.done`, { count: res.data.changed }),
        description: failed.length > 0
          ? t(`${PREFIX}.toast.failed`, { count: failed.length }) : undefined,
        variant: failed.length > 0 ? 'destructive' : undefined,
      });
      if (res.data.changed > 0) onReset();
      if (failed.length === 0) {
        onOpenChange(false);
      } else {
        setFailures(failed);
        await load();
      }
    } finally {
      setSaving(false);
    }
  };

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-4xl">
        <DialogHeader>
          <DialogTitle>{t(`${PREFIX}.title`)}</DialogTitle>
          <DialogDescription>
            {drift
              ? t(`${PREFIX}.description`, { object: drift.target })
              : t(`${PREFIX}.descriptionLoading`)}
          </DialogDescription>
        </DialogHeader>

        {loading && (
          <div className="flex items-center gap-2 text-sm text-muted-foreground" role="status">
            <Loader2 className="h-4 w-4 animate-spin" /> {t(`${PREFIX}.loading`)}
          </div>
        )}

        {error && (
          <div
            role="alert"
            className="flex items-start gap-2 text-sm text-red-700 dark:text-red-400"
          >
            <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" />
            <span>
              {descriptionResetText(t, 'errors', error.code, error.message, error.params)}
            </span>
          </div>
        )}

        {failures.length > 0 && (
          <ul role="alert" className="space-y-1 text-sm text-red-700 dark:text-red-400">
            {failures.map((f) => (
              <li key={f.asset_id}>
                <span className="font-medium">{nameOf(f.asset_id)}</span>{': '}
                {descriptionResetText(
                  t, 'errors', f.error?.code, f.error?.message, f.error?.params,
                )}
              </li>
            ))}
          </ul>
        )}

        {drift && rows.length === 0 && !loading && (
          <p role="status" className="text-sm text-muted-foreground">
            {t(`${PREFIX}.noDifferences`)}
          </p>
        )}

        {drift && rows.length > 0 && (
          <div className="space-y-2">
            <div className="flex items-center justify-between">
              <span className="text-sm text-muted-foreground">
                {t(`${PREFIX}.differences`, { count: rows.length })}
              </span>
              <Button
                type="button" variant="ghost" size="sm" disabled={choices.length === 0}
                onClick={() => setSelected(
                  selected.size === choices.length
                    ? new Set() : new Set(choices.map((f) => f.asset_id)),
                )}
              >
                {selected.size === choices.length && choices.length > 0
                  ? t(`${PREFIX}.selectNone`) : t(`${PREFIX}.selectAll`)}
              </Button>
            </div>
            <div className="max-h-[50vh] overflow-auto rounded-md border">
              <table className="w-full text-left">
                <thead className="sticky top-0 bg-muted text-xs text-muted-foreground">
                  <tr>
                    <th className="w-8 p-2" />
                    <th className="p-2">{t(`${PREFIX}.colName`)}</th>
                    <th className="p-2">{t(`${PREFIX}.colOntos`)}</th>
                    <th className="p-2">{t(`${PREFIX}.colUc`)}</th>
                  </tr>
                </thead>
                <tbody>
                  {rows.map((f) => (
                    <tr key={f.asset_id} className="border-t align-top">
                      <td className="p-2">
                        <Checkbox
                          aria-label={t(`${PREFIX}.select`, { name: f.name })}
                          checked={selected.has(f.asset_id)}
                          disabled={!selectable(f)}
                          onCheckedChange={(on) => toggle(f.asset_id, on === true)}
                        />
                      </td>
                      <td className="p-2 text-sm">
                        <div className="font-medium">{f.name}</div>
                        <div className="flex flex-wrap gap-1 pt-1">
                          <Badge variant="outline" className="text-xs">{f.object_type}</Badge>
                          {f.changed_in_uc && (
                            <Badge variant="secondary" className="text-xs">
                              {t(`${PREFIX}.changedBadge`)}
                            </Badge>
                          )}
                        </div>
                      </td>
                      <td className="p-2"><Cell text={f.description} /></td>
                      <td className="p-2">
                        <Cell text={f.uc_comment} />
                        {!f.uc_comment && (
                          <p className="pt-1 text-xs text-amber-700 dark:text-amber-400">
                            {t(`${PREFIX}.ucEmptyRow`)}
                          </p>
                        )}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            {drift.truncated && (
              <p className="text-xs text-muted-foreground">{t(`${PREFIX}.truncated`)}</p>
            )}
            <p className="text-sm text-muted-foreground">{t(`${PREFIX}.replaceNote`)}</p>
          </div>
        )}

        <DialogFooter>
          <Button variant="outline" onClick={() => onOpenChange(false)} disabled={saving}>
            {t('common:actions.cancel')}
          </Button>
          <Button onClick={confirm} disabled={selected.size === 0 || saving}>
            {saving && <Loader2 className="mr-2 h-4 w-4 animate-spin" />}
            {t(`${PREFIX}.resetSelected`, { count: selected.size })}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
