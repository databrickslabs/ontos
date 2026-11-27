import type { TFunction } from 'i18next';
import { useTranslation } from 'react-i18next';
import { AlertTriangle } from 'lucide-react';

import { Button } from '@/components/ui/button';
import type { AssetCodedWarning, AssetDescriptionSync } from '@/types/asset';

/** The translated text of a description write-back warning (the backend's code + params). */
export function descriptionSyncText(t: TFunction, warning: AssetCodedWarning): string {
  return String(
    t(`assets:descriptionSync.warnings.${warning.code}`, {
      ...(warning.params ?? {}),
      defaultValue: warning.message,
    })
  );
}

/**
 * Shown on an asset whose description could not be written to Unity Catalog.
 * `onUseUcComment`: opens the dialog that replaces the description with the Unity Catalog comment.
 */
export function DescriptionSyncNotice({
  sync, onUseUcComment,
}: { sync?: AssetDescriptionSync | null; onUseUcComment?: () => void }) {
  const { t } = useTranslation(['assets']);
  if (!sync) return null;
  return (
    <div
      role="status"
      className="mt-2 flex max-w-2xl items-start gap-2 text-sm text-amber-700 dark:text-amber-400"
    >
      <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" />
      <div>
        <span className="font-medium">
          {t('assets:descriptionSync.notInSync', 'Not in sync with Unity Catalog')}
        </span>
        <span className="text-muted-foreground"> {descriptionSyncText(t, sync)}</span>
        {onUseUcComment && (
          <Button
            type="button" variant="link" size="sm" className="ml-1 h-auto p-0 align-baseline"
            onClick={onUseUcComment}
          >
            {t('assets:descriptionReset.action')}
          </Button>
        )}
      </div>
    </div>
  );
}
