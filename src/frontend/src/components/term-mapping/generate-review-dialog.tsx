import { useEffect, useState } from 'react';
import { Loader2 } from 'lucide-react';
import { useNavigate } from 'react-router-dom';

import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Textarea } from '@/components/ui/textarea';
import { Checkbox } from '@/components/ui/checkbox';
import { Alert, AlertDescription } from '@/components/ui/alert';
import { useApi } from '@/hooks/use-api';
import { useToast } from '@/hooks/use-toast';
import type {
  GenerateReviewRequest,
  GenerateReviewResponse,
  Run,
} from '@/types/term-mapping';

interface Props {
  isOpen: boolean;
  onOpenChange: (open: boolean) => void;
  run: Run | null;
  currentUserEmail?: string;
  onCreated?: (reviewId: string) => void;
}

export default function GenerateReviewDialog({
  isOpen,
  onOpenChange,
  run,
  currentUserEmail,
  onCreated,
}: Props) {
  const { post } = useApi();
  const { toast } = useToast();
  const navigate = useNavigate();

  // Default reviewer to caller — mirrors the MDM "self-review" default. Stewards
  // who want to hand off to someone else can edit before submit.
  const [reviewerEmail, setReviewerEmail] = useState(currentUserEmail ?? '');
  const [notes, setNotes] = useState('');
  const [includeAccepted, setIncludeAccepted] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (isOpen) {
      setReviewerEmail(currentUserEmail ?? '');
      setNotes('');
      setIncludeAccepted(false);
      setError(null);
    }
  }, [isOpen, currentUserEmail]);

  const stats = (run?.stats ?? {}) as Record<string, number | undefined>;
  const pending = stats.suggestions_pending ?? 0;
  const accepted = stats.suggestions_accepted ?? 0;
  const eligible = pending + (includeAccepted ? accepted : 0);

  const handleSubmit = async () => {
    if (!run) return;
    if (!reviewerEmail.trim()) {
      setError('Reviewer email is required.');
      return;
    }
    setSubmitting(true);
    setError(null);
    try {
      const payload: GenerateReviewRequest = {
        reviewer_email: reviewerEmail.trim(),
        notes: notes.trim() || undefined,
        include_accepted: includeAccepted,
      };
      const res = await post<GenerateReviewResponse>(
        `/api/term-mappings/runs/${run.id}/review`,
        payload,
      );
      if (res.error) throw new Error(res.error);
      const data = res.data!;
      toast({
        title: 'Review created',
        description: `${data.suggestion_count} suggestions queued for review.`,
      });
      onCreated?.(data.review_request_id);
      onOpenChange(false);
      navigate(`/data-asset-reviews/${data.review_request_id}`);
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Failed to create review');
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <Dialog open={isOpen} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-lg">
        <DialogHeader>
          <DialogTitle>Generate Review for Run</DialogTitle>
          <DialogDescription>
            Spawn a Data Asset Review containing every suggestion in this run.
            Decisions made in the review flow back to the suggestion queue.
          </DialogDescription>
        </DialogHeader>

        <div className="space-y-4">
          <div className="space-y-2">
            <Label htmlFor="reviewer-email">Reviewer email *</Label>
            <Input
              id="reviewer-email"
              type="email"
              value={reviewerEmail}
              onChange={(e) => setReviewerEmail(e.target.value)}
              placeholder="steward@company.com"
            />
            <p className="text-xs text-muted-foreground">
              Defaults to you. Hand off to a domain steward if needed.
            </p>
          </div>

          <div className="space-y-2">
            <Label htmlFor="notes">Notes</Label>
            <Textarea
              id="notes"
              value={notes}
              onChange={(e) => setNotes(e.target.value)}
              placeholder="Optional context for the reviewer."
              className="min-h-[80px]"
            />
          </div>

          <div className="flex items-start gap-2">
            <Checkbox
              id="include-accepted"
              checked={includeAccepted}
              onCheckedChange={(v) => setIncludeAccepted(v === true)}
            />
            <Label htmlFor="include-accepted" className="text-sm font-normal leading-snug">
              Also include already-accepted suggestions
              <span className="block text-xs text-muted-foreground">
                Useful when you want the reviewer to confirm prior decisions, not just
                triage pending rows.
              </span>
            </Label>
          </div>

          <Alert>
            <AlertDescription>
              {eligible} suggestion{eligible === 1 ? '' : 's'} will become reviewable
              assets ({pending} pending{includeAccepted ? `, ${accepted} accepted` : ''}).
            </AlertDescription>
          </Alert>

          {error && (
            <Alert variant="destructive">
              <AlertDescription>{error}</AlertDescription>
            </Alert>
          )}
        </div>

        <DialogFooter>
          <Button variant="ghost" onClick={() => onOpenChange(false)} disabled={submitting}>
            Cancel
          </Button>
          <Button onClick={handleSubmit} disabled={submitting || eligible === 0}>
            {submitting && <Loader2 className="mr-2 h-4 w-4 animate-spin" />}
            Generate Review
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
