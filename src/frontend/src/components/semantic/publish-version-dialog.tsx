import { useEffect, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { Loader2 } from 'lucide-react';
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog';
import { Button } from '@/components/ui/button';
import { Textarea } from '@/components/ui/textarea';
import { Label } from '@/components/ui/label';
import { useToast } from '@/hooks/use-toast';

// ---------------------------------------------------------------------------
// PublishVersionDialog — drives the signed-off versioning contract §4
// (POST /api/semantic-models/concepts/version/publish).
//
// Framed for the Simple view as "Save new version": you edit the definition,
// optionally say what changed, and a new current version is saved. NO version
// integers or IRIs are shown in Simple. Advanced view adds a quiet hint that
// this will create v{current+1}.
// ---------------------------------------------------------------------------

interface PublishVersionDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  iri: string;
  /** Prefill for the editable definition field (current definition). */
  currentDefinition: string;
  /** Current version integer, used ONLY for the advanced-view hint. */
  currentVersion?: number | null;
  /** Called after a successful publish so the parent can refetch. */
  onPublished: () => void | Promise<void>;
}

interface PublishResult {
  iri: string;
  label?: string | null;
  new_version: number;
  is_current: boolean;
}

export function PublishVersionDialog({
  open,
  onOpenChange,
  iri,
  currentDefinition,
  currentVersion,
  onPublished,
}: PublishVersionDialogProps) {
  const { t } = useTranslation(['semantic-models', 'common']);
  const { toast } = useToast();

  const [definition, setDefinition] = useState(currentDefinition);
  const [note, setNote] = useState('');
  const [busy, setBusy] = useState(false);

  // Reset the form to the current definition each time the dialog opens, so a
  // reopened dialog never shows a stale edit from a previous cancel.
  useEffect(() => {
    if (open) {
      setDefinition(currentDefinition);
      setNote('');
    }
  }, [open, currentDefinition]);

  const trimmedNew = definition.trim();
  const unchanged = trimmedNew === (currentDefinition ?? '').trim();
  const canSubmit = trimmedNew.length > 0 && !unchanged && !busy;

  const handleSubmit = async () => {
    if (!canSubmit) return;
    setBusy(true);
    try {
      const response = await fetch(
        '/api/semantic-models/concepts/version/publish',
        {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            iri,
            changes: { definition: trimmedNew },
            change_note: note.trim() || undefined,
          }),
        },
      );
      if (!response.ok) {
        const err = await response.json().catch(() => ({} as any));
        throw new Error(err?.detail || 'Failed to save new version');
      }
      const result: PublishResult = await response.json().catch(() => ({} as any));
      toast({
        title: t('common:toast.success'),
        description: t(
          'semantic-models:versionHistory.saved',
          'New version saved',
        ),
      });
      onOpenChange(false);
      // Kept for the advanced hint only; result is otherwise unused.
      void result;
      await onPublished();
    } catch (err: any) {
      toast({
        title: t('common:toast.error'),
        description: err?.message,
        variant: 'destructive',
      });
    } finally {
      setBusy(false);
    }
  };

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-lg">
        <DialogHeader>
          <DialogTitle>
            {t('semantic-models:versionHistory.saveNewVersion', 'Save new version')}
          </DialogTitle>
          <DialogDescription>
            {t(
              'semantic-models:versionHistory.saveDescription',
              'Edit the definition and save it as a new version. The previous definition is kept in the history.',
            )}
            {/* Advanced-only mechanic: which version integer this creates. */}
            {typeof currentVersion === 'number' && (
              <span className="adv-only block mt-1 font-mono text-xs">
                {t(
                  'semantic-models:versionHistory.willCreate',
                  'This will create v{{next}}.',
                  { next: currentVersion + 1 },
                )}
              </span>
            )}
          </DialogDescription>
        </DialogHeader>

        <div className="space-y-4 py-2">
          <div className="space-y-1.5">
            <Label htmlFor="version-definition">
              {t('semantic-models:fields.definition', 'Definition')}
            </Label>
            <Textarea
              id="version-definition"
              value={definition}
              onChange={(e) => setDefinition(e.target.value)}
              rows={4}
              autoFocus
            />
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="version-note">
              {t('semantic-models:versionHistory.whatChanged', 'What changed?')}
              <span className="ml-1 text-xs font-normal text-muted-foreground">
                {t('common:optional', '(optional)')}
              </span>
            </Label>
            <Textarea
              id="version-note"
              value={note}
              onChange={(e) => setNote(e.target.value)}
              rows={2}
              placeholder={t(
                'semantic-models:versionHistory.notePlaceholder',
                'e.g. tightened the wording for clarity',
              )}
            />
          </div>
        </div>

        <DialogFooter>
          <Button variant="outline" onClick={() => onOpenChange(false)} disabled={busy}>
            {t('common:actions.cancel', 'Cancel')}
          </Button>
          <Button onClick={handleSubmit} disabled={!canSubmit}>
            {busy && <Loader2 className="mr-2 h-4 w-4 animate-spin" />}
            {t('semantic-models:versionHistory.saveNewVersion', 'Save new version')}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

export default PublishVersionDialog;
