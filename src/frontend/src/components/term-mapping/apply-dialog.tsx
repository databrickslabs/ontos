import { useState } from 'react';
import { CheckCircle2, Loader2 } from 'lucide-react';

import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog';
import { Button } from '@/components/ui/button';
import { Checkbox } from '@/components/ui/checkbox';
import { Label } from '@/components/ui/label';
import { Alert, AlertDescription } from '@/components/ui/alert';
import { useToast } from '@/hooks/use-toast';
import { useApi } from '@/hooks/use-api';
import type { ApplyResult, Run, RunStats } from '@/types/term-mapping';

interface ApplyDialogProps {
  isOpen: boolean;
  onOpenChange: (open: boolean) => void;
  run: Run | null;
  onApplied: (run: Run, result: ApplyResult) => void;
}

export default function ApplyDialog({ isOpen, onOpenChange, run, onApplied }: ApplyDialogProps) {
  const { toast } = useToast();
  const { post } = useApi();
  const [applyAuto, setApplyAuto] = useState(true);
  const [submitting, setSubmitting] = useState(false);

  if (!run) return null;

  const stats: RunStats = run.stats ?? {};
  const accepted = (stats.suggestions_accepted as number) ?? 0;
  const auto = (stats.suggestions_auto_apply as number) ?? 0;
  const pending = (stats.suggestions_pending as number) ?? 0;
  const willApply = accepted + (applyAuto ? auto : 0);

  const handleApply = async () => {
    setSubmitting(true);
    try {
      const res = await post<ApplyResult>(
        `/api/term-mappings/runs/${run.id}/apply`,
        { apply_auto: applyAuto },
      );
      if (res.error) throw new Error(res.error);
      const result = res.data;
      toast({
        title: 'Applied',
        description: `${result.links_created} link${result.links_created === 1 ? '' : 's'} created, ${result.links_skipped} skipped${
          result.errors && result.errors.length > 0 ? `, ${result.errors.length} errors` : ''
        }.`,
      });
      onApplied(run, result);
      onOpenChange(false);
    } catch (e) {
      toast({
        title: 'Apply failed',
        description: e instanceof Error ? e.message : 'Unknown error',
        variant: 'destructive',
      });
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <Dialog open={isOpen} onOpenChange={(open) => !submitting && onOpenChange(open)}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2">
            <CheckCircle2 className="h-5 w-5 text-emerald-600" />
            Apply run
          </DialogTitle>
          <DialogDescription>
            Persist accepted (and optionally auto-applicable) suggestions as semantic links on
            the source entities.
          </DialogDescription>
        </DialogHeader>

        <div className="space-y-4">
          <div className="grid grid-cols-3 gap-2 text-center">
            <Stat label="Accepted" value={accepted} tone="success" />
            <Stat label="Auto-apply" value={auto} tone="info" />
            <Stat label="Pending" value={pending} tone="muted" />
          </div>

          <label className="flex items-start gap-2">
            <Checkbox
              checked={applyAuto}
              onCheckedChange={(checked) => setApplyAuto(checked === true)}
              className="mt-0.5"
            />
            <div className="space-y-0.5">
              <Label className="text-sm font-medium leading-none">
                Also apply high-confidence auto-suggestions
              </Label>
              <p className="text-xs text-muted-foreground">
                Suggestions with confidence ≥ 0.9 will be applied without explicit review.
                Turn this off if you only want to apply suggestions you accepted manually.
              </p>
            </div>
          </label>

          <Alert>
            <AlertDescription>
              About <strong>{willApply}</strong> link{willApply === 1 ? '' : 's'} will be
              created. Already-linked source/concept pairs are skipped. The exact link IDs
              are recorded so an ADMIN can undo this run.
            </AlertDescription>
          </Alert>
        </div>

        <DialogFooter>
          <Button variant="outline" onClick={() => onOpenChange(false)} disabled={submitting}>
            Cancel
          </Button>
          <Button onClick={handleApply} disabled={submitting || willApply === 0}>
            {submitting ? (
              <>
                <Loader2 className="h-4 w-4 mr-2 animate-spin" />
                Applying…
              </>
            ) : (
              <>
                <CheckCircle2 className="h-4 w-4 mr-2" />
                Apply {willApply} link{willApply === 1 ? '' : 's'}
              </>
            )}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

function Stat({
  label,
  value,
  tone,
}: {
  label: string;
  value: number;
  tone: 'success' | 'info' | 'muted';
}) {
  const toneClass =
    tone === 'success'
      ? 'text-emerald-600'
      : tone === 'info'
        ? 'text-sky-600'
        : 'text-muted-foreground';
  return (
    <div className="rounded-md border p-3">
      <div className={`text-2xl font-bold ${toneClass}`}>{value}</div>
      <div className="text-xs uppercase tracking-wide text-muted-foreground">{label}</div>
    </div>
  );
}
