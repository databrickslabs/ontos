import { useTranslation } from 'react-i18next';
import { Button } from '@/components/ui/button';
import { Loader2, RotateCcw, Save } from 'lucide-react';
import { cn } from '@/lib/utils';

interface SettingsActionBarProps {
  /** Whether the page has pending edits. Bar only renders when true. */
  isDirty: boolean;
  /** True while a save request is in-flight. Disables both buttons. */
  isSaving?: boolean;
  /** Save handler. */
  onSave: () => void;
  /** Revert handler. Should restore local state to the last loaded snapshot. */
  onCancel: () => void;
  /** Optional override for the Save button label. */
  saveLabel?: string;
  /** Optional override for the Cancel/Revert button label. */
  cancelLabel?: string;
  /** Optional override for the saving spinner label. */
  savingLabel?: string;
  /** Optional override for the "unsaved changes" status text. */
  dirtyLabel?: string;
  /** Additional class names applied to the bar wrapper. */
  className?: string;
}

/**
 * Shared sticky action bar for settings sub-pages.
 *
 * Renders nothing when `isDirty` is false. When dirty, slides up from the
 * bottom of the viewport with a Save (primary) and Cancel/Revert (outline)
 * button, plus a small status pill. Pair with `<UnsavedChangesGuard />`
 * to also catch tab-close / reload.
 *
 * Layout choice: the bar is `sticky bottom-0` rather than `fixed` so it
 * respects the page's scroll container and the existing app shell layout.
 */
export default function SettingsActionBar({
  isDirty,
  isSaving = false,
  onSave,
  onCancel,
  saveLabel,
  cancelLabel,
  savingLabel,
  dirtyLabel,
  className,
}: SettingsActionBarProps) {
  const { t } = useTranslation(['common']);

  if (!isDirty) return null;

  return (
    <div
      className={cn(
        'sticky bottom-0 z-40 mt-6 -mx-4 sm:-mx-6 lg:-mx-8',
        'border-t bg-background/95 backdrop-blur supports-[backdrop-filter]:bg-background/80',
        'px-4 sm:px-6 lg:px-8 py-3',
        'flex items-center justify-end gap-3 shadow-[0_-2px_8px_rgba(0,0,0,0.04)]',
        className
      )}
      role="region"
      aria-label={t('common:confirmations.unsavedChanges', 'You have unsaved changes')}
    >
      <span className="mr-auto text-sm text-muted-foreground">
        {dirtyLabel ?? t('common:confirmations.unsavedChanges', 'You have unsaved changes')}
      </span>
      <Button
        type="button"
        variant="outline"
        onClick={onCancel}
        disabled={isSaving}
      >
        <RotateCcw className="mr-2 h-4 w-4" />
        {cancelLabel ?? t('common:actions.cancel', 'Cancel')}
      </Button>
      <Button type="button" onClick={onSave} disabled={isSaving}>
        {isSaving ? (
          <Loader2 className="mr-2 h-4 w-4 animate-spin" />
        ) : (
          <Save className="mr-2 h-4 w-4" />
        )}
        {isSaving
          ? savingLabel ?? t('common:actions.saving', 'Saving...')
          : saveLabel ?? t('common:actions.save', 'Save')}
      </Button>
    </div>
  );
}
