import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogFooter } from '@/components/ui/dialog';
import { Button } from '@/components/ui/button';
import { Textarea } from '@/components/ui/textarea';
import { Label } from '@/components/ui/label';
import { useToast } from '@/hooks/use-toast';
import { useApi } from '@/hooks/use-api';
import { FileText } from 'lucide-react';

type Props = {
  isOpen: boolean;
  onOpenChange: (open: boolean) => void;
  contractId: string;
  contractName?: string;
  requesterEmail: string;
  onDecisionMade: () => void;
};

export default function HandleStewardReviewDialog({
  isOpen,
  onOpenChange,
  contractId,
  contractName,
  requesterEmail,
  onDecisionMade
}: Props) {
  const { t } = useTranslation(['data-contracts', 'common']);
  const { post } = useApi();
  const { toast } = useToast();
  const [message, setMessage] = useState('');
  const [submitting, setSubmitting] = useState(false);

  const submitDecision = async (decision: 'approve' | 'reject' | 'clarify') => {
    setSubmitting(true);
    try {
      const body = {
        decision,
        message: message || undefined,
      };
      const res = await post(`/api/data-contracts/${contractId}/handle-review`, body);
      if (res.error) throw new Error(res.error);

      const decisionLabels = {
        approve: t('data-contracts:stewardReview.decision.approved', 'approved'),
        reject: t('data-contracts:stewardReview.decision.rejected', 'rejected'),
        clarify: t('data-contracts:stewardReview.decision.clarify', 'clarification requested')
      };

      toast({
        title: t('data-contracts:stewardReview.toast.submittedTitle', 'Review Decision Submitted'),
        description: t('data-contracts:stewardReview.toast.submittedDescription', 'Contract review {{decision}}.', { decision: decisionLabels[decision] })
      });
      onDecisionMade();
      onOpenChange(false);
    } catch (e: any) {
      toast({
        title: t('data-contracts:stewardReview.toast.failedTitle', 'Failed'),
        description: e.message || t('data-contracts:stewardReview.toast.couldNotSubmit', 'Could not submit decision'),
        variant: 'destructive'
      });
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <Dialog open={isOpen} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-[500px]">
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2">
            <FileText className="h-5 w-5" />
            {t('data-contracts:stewardReview.title', 'Handle Contract Review')}
          </DialogTitle>
        </DialogHeader>
        <div className="space-y-4">
          <div className="p-3 bg-muted/50 rounded-lg border space-y-2">
            <div className="text-sm text-muted-foreground">
              <span className="font-medium">{t('data-contracts:stewardReview.requesterLabel', 'Requester:')}</span> {requesterEmail}
            </div>
            <div className="text-sm text-muted-foreground">
              <span className="font-medium">{t('data-contracts:stewardReview.contractIdLabel', 'Contract ID:')}</span> <span className="font-mono">{contractId}</span>
            </div>
            {contractName && (
              <div className="text-sm font-medium">{contractName}</div>
            )}
          </div>

          <div className="space-y-2">
            <Label htmlFor="review-message">{t('data-contracts:stewardReview.feedbackLabel', 'Feedback Message (optional)')}</Label>
            <Textarea
              id="review-message"
              value={message}
              onChange={(e) => setMessage(e.target.value)}
              placeholder={t('data-contracts:stewardReview.feedbackPlaceholder', 'Provide feedback for the requester...')}
              className="min-h-[100px]"
            />
            <p className="text-xs text-muted-foreground">
              {t('data-contracts:stewardReview.messageHint', 'This message will be sent to the requester along with your decision.')}
            </p>
          </div>
        </div>
        <DialogFooter className="gap-2">
          <Button variant="outline" onClick={() => onOpenChange(false)} disabled={submitting}>
            {t('common:actions.cancel', 'Cancel')}
          </Button>
          <Button variant="secondary" onClick={() => submitDecision('clarify')} disabled={submitting}>
            {t('data-contracts:stewardReview.requestClarification', 'Request Clarification')}
          </Button>
          <Button variant="destructive" onClick={() => submitDecision('reject')} disabled={submitting}>
            {t('common:actions.reject', 'Reject')}
          </Button>
          <Button onClick={() => submitDecision('approve')} disabled={submitting}>
            {t('common:actions.approve', 'Approve')}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
