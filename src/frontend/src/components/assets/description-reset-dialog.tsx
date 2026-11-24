import { useCallback, useEffect, useState } from 'react';
import type { TFunction } from 'i18next';
import { useTranslation } from 'react-i18next';
import { AlertTriangle, Loader2 } from 'lucide-react';
import {
  Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle,
} from '@/components/ui/dialog';
import { Button } from '@/components/ui/button';
import { cn } from '@/lib/utils';
import { useApi } from '@/hooks/use-api';
import { useToast } from '@/hooks/use-toast';
import type {
  AssetCodedWarning, AssetDescriptionResetResult, AssetUcCommentPreview,
} from '@/types/asset';

const PREFIX = 'assets:descriptionReset';

/** Asset types whose description is a Unity Catalog comment (a table, a view or a column). */
const RESET_TYPES = ['table', 'view', 'column'];

/** Whether the "use the Unity Catalog comment" action applies to an asset. */
export function canResetDescription(
  assetTypeName?: string | null, platform?: string | null,
): boolean {
  return (
    (platform ?? '').trim().toLowerCase() === 'databricks'
    && RESET_TYPES.includes((assetTypeName ?? '').trim().toLowerCase())
  );
}

/** The text of a coded error or warning of the reset, in the user's language. */
export function descriptionResetText(
  t: TFunction,
  kind: 'errors' | 'warnings',
  code: string | null | undefined,
  message: string | null | undefined,
  params?: Record<string, unknown> | null,
): string {
  const fallback = message || String(t(`${PREFIX}.errors.generic`));
  if (!code) return fallback;
  return String(t(`${PREFIX}.${kind}.${code}`, { ...(params ?? {}), defaultValue: fallback }));
}

interface Props {
  assetId: string;
  open: boolean;
  onOpenChange: (open: boolean) => void;
  /** Called after the description was replaced, so the asset is read again. */
  onReset: () => void;
}

interface LoadError {
  code?: string | null;
  message?: string | null;
  params?: Record<string, unknown> | null;
}

function TextPane({ title, text, tone }: {
  title: string; text?: string | null; tone: 'old' | 'new';
}) {
  const { t } = useTranslation(['assets']);
  const toneClass = tone === 'old'
    ? 'border-red-200 bg-red-50 dark:border-red-900 dark:bg-red-950/40'
    : 'border-green-200 bg-green-50 dark:border-green-900 dark:bg-green-950/40';
  return (
    <div className="min-w-0 flex-1 space-y-1">
      <div className="text-xs font-medium text-muted-foreground">{title}</div>
      <div
        data-testid={`description-reset-${tone}`}
        className={cn(
          'max-h-48 overflow-auto whitespace-pre-wrap break-words rounded-md border p-2 text-sm',
          toneClass,
        )}
      >
        {text ? text : (
          <span className="italic text-muted-foreground">{t(`${PREFIX}.empty`)}</span>
        )}
      </div>
    </div>
  );
}

/**
 * Shows the Ontos description next to the Unity Catalog comment of a table, view or column
 * (read as the user) and, once confirmed, replaces the first with the second. An empty comment
 * is never applied; the confirmed comment is sent back, so a comment changed meanwhile is
 * refused by the server rather than applied unseen.
 */
export function DescriptionResetDialog({ assetId, open, onOpenChange, onReset }: Props) {
  const { t } = useTranslation(['assets', 'common']);
  const { get, post } = useApi();
  const { toast } = useToast();
  const [preview, setPreview] = useState<AssetUcCommentPreview | null>(null);
  const [loading, setLoading] = useState(false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<LoadError | null>(null);

  const load = useCallback(async (keepError?: LoadError | null) => {
    setLoading(true);
    const res = await get<AssetUcCommentPreview>(`/api/assets/${assetId}/description/uc-comment`);
    if (res.error || !res.data) {
      setPreview(null);
      setError({ code: res.errorCode, message: res.error, params: res.errorParams });
    } else {
      setPreview(res.data);
      setError(keepError ?? null);
    }
    setLoading(false);
  }, [assetId, get]);

  useEffect(() => {
    if (!open) return;
    setPreview(null);
    setError(null);
    void load();
  }, [open, load]);

  const confirm = async () => {
    if (!preview) return;
    setSaving(true);
    try {
      const res = await post<AssetDescriptionResetResult>(
        `/api/assets/${assetId}/description/reset-to-uc`,
        { expected_uc_comment: preview.uc_comment ?? null },
      );
      if (res.error || !res.data) {
        const failure = { code: res.errorCode, message: res.error, params: res.errorParams };
        setError(failure);
        // The comment changed since it was shown: show the new one, and keep the message
        if (res.errorCode === 'uc_reset_uc_changed') await load(failure);
        return;
      }
      const warning: AssetCodedWarning | undefined = res.data.warnings?.[0];
      toast({
        title: res.data.changed
          ? t(`${PREFIX}.toast.done`)
          : t(`${PREFIX}.toast.unchanged`),
        description: warning
          ? descriptionResetText(t, 'warnings', warning.code, warning.message, warning.params)
          : undefined,
      });
      onOpenChange(false);
      onReset();
    } finally {
      setSaving(false);
    }
  };

  const ucEmpty = !!preview && !preview.uc_comment;
  const canConfirm = !!preview && !preview.in_sync && !ucEmpty && !saving;

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-2xl">
        <DialogHeader>
          <DialogTitle>{t(`${PREFIX}.title`)}</DialogTitle>
          <DialogDescription>
            {preview
              ? t(`${PREFIX}.description`, { object: preview.target })
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

        {preview && (
          <div className="space-y-3">
            <div className="flex flex-col gap-3 sm:flex-row">
              <TextPane title={t(`${PREFIX}.inOntos`)} text={preview.description} tone="old" />
              <TextPane
                title={t(`${PREFIX}.inUnityCatalog`)} text={preview.uc_comment} tone="new"
              />
            </div>
            {preview.in_sync && (
              <p role="status" className="text-sm text-muted-foreground">
                {t(`${PREFIX}.alreadyInSync`)}
              </p>
            )}
            {ucEmpty && !preview.in_sync && (
              <p role="status" className="text-sm text-amber-700 dark:text-amber-400">
                {t(`${PREFIX}.ucEmpty`)}
              </p>
            )}
            {canConfirm && (
              <p className="text-sm text-muted-foreground">{t(`${PREFIX}.replaceNote`)}</p>
            )}
          </div>
        )}

        <DialogFooter>
          <Button variant="outline" onClick={() => onOpenChange(false)} disabled={saving}>
            {t('common:actions.cancel')}
          </Button>
          <Button onClick={confirm} disabled={!canConfirm}>
            {saving && <Loader2 className="mr-2 h-4 w-4 animate-spin" />}
            {t(`${PREFIX}.confirm`)}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
