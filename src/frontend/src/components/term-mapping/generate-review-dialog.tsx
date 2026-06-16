import { useEffect, useState } from 'react';
import { Loader2 } from 'lucide-react';
import { useNavigate } from 'react-router-dom';
import { useTranslation } from 'react-i18next';

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
  const { t } = useTranslation(['term-mapping', 'common']);
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
      setError(t('generateReview.validation.reviewerRequired'));
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
        title: t('generateReview.toast.created'),
        description: t(
          data.suggestion_count === 1
            ? 'generateReview.toast.createdDescriptionOne'
            : 'generateReview.toast.createdDescriptionMany',
          { count: data.suggestion_count },
        ),
      });
      onCreated?.(data.review_request_id);
      onOpenChange(false);
      navigate(`/data-asset-reviews/${data.review_request_id}`);
    } catch (e) {
      setError(e instanceof Error ? e.message : t('generateReview.toast.failed'));
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <Dialog open={isOpen} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-lg">
        <DialogHeader>
          <DialogTitle>{t('generateReview.title')}</DialogTitle>
          <DialogDescription>{t('generateReview.description')}</DialogDescription>
        </DialogHeader>

        <div className="space-y-4">
          <div className="space-y-2">
            <Label htmlFor="reviewer-email">{t('generateReview.reviewerEmail')}</Label>
            <Input
              id="reviewer-email"
              type="email"
              value={reviewerEmail}
              onChange={(e) => setReviewerEmail(e.target.value)}
              placeholder={t('generateReview.reviewerEmailPlaceholder')}
            />
            <p className="text-xs text-muted-foreground">{t('generateReview.reviewerEmailHelp')}</p>
          </div>

          <div className="space-y-2">
            <Label htmlFor="notes">{t('generateReview.notes')}</Label>
            <Textarea
              id="notes"
              value={notes}
              onChange={(e) => setNotes(e.target.value)}
              placeholder={t('generateReview.notesPlaceholder')}
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
              {t('generateReview.includeAccepted')}
              <span className="block text-xs text-muted-foreground">
                {t('generateReview.includeAcceptedHelp')}
              </span>
            </Label>
          </div>

          <Alert>
            <AlertDescription>
              {t(
                eligible === 1
                  ? 'generateReview.eligibleSummaryOne'
                  : 'generateReview.eligibleSummaryMany',
                {
                  eligible,
                  pending,
                  acceptedPart: includeAccepted
                    ? t('generateReview.acceptedPart', { accepted })
                    : '',
                },
              )}
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
            {t('actions.cancel')}
          </Button>
          <Button onClick={handleSubmit} disabled={submitting || eligible === 0}>
            {submitting && <Loader2 className="mr-2 h-4 w-4 animate-spin" />}
            {t('generateReview.submit')}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
