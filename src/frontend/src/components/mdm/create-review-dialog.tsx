import { useState } from 'react';
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

const formSchema = z.object({
  reviewer_email: z.string().email('Valid email is required'),
  notes: z.string().optional(),
});

type FormValues = z.infer<typeof formSchema>;

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

  const { post } = useApi();
  const { toast } = useToast();

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
          title: 'Error',
          description: response.error,
          variant: 'destructive',
        });
        return;
      }

      // Verify we have a valid review_id before navigating
      if (response.data && response.data.review_id) {
        toast({
          title: 'Success',
          description: `Review request created with ${response.data.candidate_count} candidates`,
        });
        onSuccess(response.data.review_id);
      } else {
        toast({
          title: 'Error',
          description: 'Failed to create review request - no review ID returned',
          variant: 'destructive',
        });
      }
    } catch (err: any) {
      toast({
        title: 'Error',
        description: err.message || 'Failed to create review request',
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
            Create Match Review
          </DialogTitle>
          <DialogDescription>
            Create a data asset review request for stewards to approve or reject match candidates.
          </DialogDescription>
        </DialogHeader>

        <form onSubmit={form.handleSubmit(onSubmit)} className="space-y-4">
          <div className="p-4 bg-muted rounded-lg">
            <p className="text-sm text-muted-foreground">
              This will create a review request for{' '}
              <span className="font-medium text-foreground">{candidateCount}</span> pending match
              candidates.
            </p>
          </div>

          <div className="space-y-2">
            <Label htmlFor="reviewer_email">Reviewer</Label>
            <Controller
              name="reviewer_email"
              control={form.control}
              render={({ field }) => (
                <PrincipalPicker
                  id="reviewer_email"
                  accepts={['user']}
                  value={field.value || null}
                  onChange={(next) => field.onChange(next ?? '')}
                  placeholder="data-steward@company.com"
                  aria-label="Reviewer"
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
            <Label htmlFor="notes">Notes for Reviewer</Label>
            <Textarea
              id="notes"
              placeholder="Any additional context or instructions for the reviewer..."
              rows={3}
              {...form.register('notes')}
            />
          </div>

          <DialogFooter>
            <Button type="button" variant="outline" onClick={onClose} disabled={submitting}>
              Cancel
            </Button>
            <Button type="submit" disabled={submitting}>
              {submitting && <Loader2 className="h-4 w-4 mr-2 animate-spin" />}
              Create Review Request
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}

