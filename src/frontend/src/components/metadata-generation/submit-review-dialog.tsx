import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { AlertCircle, Loader2 } from 'lucide-react';

import { Alert, AlertDescription } from '@/components/ui/alert';
import { Button } from '@/components/ui/button';
import {
  Dialog,
  DialogClose,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog';
import { Label } from '@/components/ui/label';
import { Textarea } from '@/components/ui/textarea';
import { PrincipalPicker } from '@/components/common/principal-picker';
import { useApi } from '@/hooks/use-api';
import type { SubmitReviewRequest, SubmitReviewResponse } from '@/types/metadata-generation';

interface Props {
  runId: string;
  /** Pending suggestions that will go into the review */
  count: number;
  isOpen: boolean;
  onOpenChange: (open: boolean) => void;
  onSubmitted: (result: SubmitReviewResponse) => void;
}

export default function SubmitReviewDialog({ runId, count, isOpen, onOpenChange, onSubmitted }: Props) {
  const { t } = useTranslation(['metadata-generation', 'common']);
  const { post } = useApi();
  const [reviewer, setReviewer] = useState<string | null>(null);
  const [notes, setNotes] = useState('');
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const handleOpenChange = (open: boolean) => {
    if (!open) {
      // Start blank next time
      setReviewer(null);
      setNotes('');
      setError(null);
    }
    onOpenChange(open);
  };

  const handleSubmit = async () => {
    setSubmitting(true);
    setError(null);
    const body: SubmitReviewRequest = { reviewer_email: reviewer || null, notes: notes.trim() || null };
    const res = await post<SubmitReviewResponse>(`/api/metadata-generation/runs/${runId}/review`, body);
    setSubmitting(false);
    if (res.error || !res.data) {
      setError(res.error || t('review.submitFailed'));
      return;
    }
    handleOpenChange(false);
    onSubmitted(res.data);
  };

  return (
    <Dialog open={isOpen} onOpenChange={handleOpenChange}>
      <DialogContent className="sm:max-w-lg">
        <DialogHeader>
          <DialogTitle>{t('review.submitTitle')}</DialogTitle>
          <DialogDescription>{t('review.submitDescription', { count })}</DialogDescription>
        </DialogHeader>
        <div className="space-y-4">
          <div className="space-y-1">
            <Label htmlFor="metagen-reviewer">{t('review.reviewer')}</Label>
            <PrincipalPicker
              id="metagen-reviewer"
              accepts={['user']}
              value={reviewer}
              onChange={setReviewer}
              placeholder={t('review.reviewerPlaceholder')}
              aria-label={t('review.reviewer')}
            />
            <p className="text-xs text-muted-foreground">{t('review.reviewerHint')}</p>
          </div>
          <div className="space-y-1">
            <Label htmlFor="metagen-review-notes">{t('review.notes')}</Label>
            <Textarea
              id="metagen-review-notes"
              value={notes}
              onChange={(e) => setNotes(e.target.value)}
              placeholder={t('review.notesPlaceholder')}
              className="min-h-[70px]"
            />
          </div>
          {error && (
            <Alert variant="destructive">
              <AlertCircle className="h-4 w-4" />
              <AlertDescription className="break-words">{error}</AlertDescription>
            </Alert>
          )}
        </div>
        <DialogFooter className="pt-2">
          <DialogClose asChild>
            <Button type="button" variant="outline" disabled={submitting}>
              {t('common:actions.cancel')}
            </Button>
          </DialogClose>
          <Button onClick={() => void handleSubmit()} disabled={submitting}>
            {submitting && <Loader2 className="mr-2 h-4 w-4 animate-spin" />}
            {t('review.submit')}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
