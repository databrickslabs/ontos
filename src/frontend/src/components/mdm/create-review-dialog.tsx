import { useState, useMemo } from 'react';
import { useTranslation } from 'react-i18next';
import { useForm } from 'react-hook-form';
import { zodResolver } from '@hookform/resolvers/zod';
import * as z from 'zod';

import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog';
import { Button } from '@/components/ui/button';
import { Label } from '@/components/ui/label';
import { Textarea } from '@/components/ui/textarea';
import { Loader2, FileCheck } from 'lucide-react';

import { useApi } from '@/hooks/use-api';
import { useToast } from '@/hooks/use-toast';
import { MdmCreateReviewRequest, MdmCreateReviewResponse } from '@/types/mdm';
import { PrincipalPicker } from '@/components/common/principal-picker';
import { Controller } from 'react-hook-form';

type FormValues = {
  reviewer_email: string;
  notes?: string;
};

interface CreateReviewDialogProps {
  isOpen: boolean;
  runId: string;
  candidateCount: number;
  onClose: () => void;
  onSuccess: (reviewId: string) => void;
}

export default function CreateReviewDialog({
  isOpen,
  runId,
  candidateCount,
  onClose,
  onSuccess,
}: CreateReviewDialogProps) {
  const [submitting, setSubmitting] = useState(false);

  const { t } = useTranslation(['mdm', 'common']);
  const { post } = useApi();
  const { toast } = useToast();

  const formSchema = useMemo(
    () =>
      z.object({
        reviewer_email: z.string().email(t('mdm:review.emailRequired')),
        notes: z.string().optional(),
      }),
    [t]
  );

  const form = useForm<FormValues>({
    resolver: zodResolver(formSchema),
    defaultValues: {
      reviewer_email: '',
      notes: '',
    },
  });

  const onSubmit = async (values: FormValues) => {
    setSubmitting(true);
    try {
      const data: MdmCreateReviewRequest = {
        reviewer_email: values.reviewer_email,
        notes: values.notes || undefined,
      };

      console.log('[CreateReviewDialog] Posting to:', `/api/mdm/runs/${runId}/create-review`, data);
      const response = await post<MdmCreateReviewResponse>(
        `/api/mdm/runs/${runId}/create-review`,
        data
      );
      console.log('[CreateReviewDialog] Response:', response);

      // Check for errors first (useApi returns empty object on error, not null)
      if (response.error) {
        toast({
          title: t('common:status.error'),
          description: response.error,
          variant: 'destructive',
        });
        return;
      }

      // Verify we have a valid review_id before navigating
      if (response.data && response.data.review_id) {
        toast({
          title: t('common:status.success'),
          description: t('mdm:review.createdWithCount', { count: response.data.candidate_count }),
        });
        onSuccess(response.data.review_id);
      } else {
        toast({
          title: t('common:status.error'),
          description: t('mdm:review.noReviewId'),
          variant: 'destructive',
        });
      }
    } catch (err: any) {
      toast({
        title: t('common:status.error'),
        description: err.message || t('mdm:review.createFailed'),
        variant: 'destructive',
      });
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <Dialog open={isOpen} onOpenChange={onClose}>
      <DialogContent className="max-w-md">
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2">
            <FileCheck className="h-5 w-5" />
            {t('mdm:review.dialogTitle')}
          </DialogTitle>
          <DialogDescription>
            {t('mdm:review.dialogDescription')}
          </DialogDescription>
        </DialogHeader>

        <form onSubmit={form.handleSubmit(onSubmit)} className="space-y-4">
          <div className="p-4 bg-muted rounded-lg">
            <p className="text-sm text-muted-foreground">
              {t('mdm:review.willCreatePrefix')}{' '}
              <span className="font-medium text-foreground">{candidateCount}</span>{' '}
              {t('mdm:review.willCreateSuffix')}
            </p>
          </div>

          <div className="space-y-2">
            <Label htmlFor="reviewer_email">{t('common:labels.reviewer')}</Label>
            <Controller
              name="reviewer_email"
              control={form.control}
              render={({ field }) => (
                <PrincipalPicker
                  id="reviewer_email"
                  accepts={['user']}
                  value={field.value || null}
                  onChange={(next) => field.onChange(next ?? '')}
                  placeholder={t('mdm:review.reviewerPlaceholder')}
                  aria-label={t('common:labels.reviewer')}
                />
              )}
            />
            {form.formState.errors.reviewer_email && (
              <p className="text-sm text-destructive">
                {form.formState.errors.reviewer_email.message}
              </p>
            )}
          </div>

          <div className="space-y-2">
            <Label htmlFor="notes">{t('mdm:review.notesLabel')}</Label>
            <Textarea
              id="notes"
              placeholder={t('mdm:review.notesPlaceholder')}
              rows={3}
              {...form.register('notes')}
            />
          </div>

          <DialogFooter>
            <Button type="button" variant="outline" onClick={onClose} disabled={submitting}>
              {t('common:actions.cancel')}
            </Button>
            <Button type="submit" disabled={submitting}>
              {submitting && <Loader2 className="h-4 w-4 mr-2 animate-spin" />}
              {t('mdm:candidates.createReview')}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}

