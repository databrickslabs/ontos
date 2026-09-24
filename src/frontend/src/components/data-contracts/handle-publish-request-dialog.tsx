import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogFooter } from '@/components/ui/dialog';
import { Button } from '@/components/ui/button';
import { Textarea } from '@/components/ui/textarea';
import { Label } from '@/components/ui/label';
import { useToast } from '@/hooks/use-toast';
import { useApi } from '@/hooks/use-api';
import { Rocket } from 'lucide-react';

type Props = {
  isOpen: boolean;
  onOpenChange: (open: boolean) => void;
  contractId: string;
  contractName?: string;
  requesterEmail: string;
  onDecisionMade: () => void;
};

export default function HandlePublishRequestDialog({
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

  const submitDecision = async (decision: 'approve' | 'deny') => {
    setSubmitting(true);
    try {
      const body = {
        decision,
        message: message || undefined,
      };
      const res = await post(`/api/data-contracts/${contractId}/handle-publish`, body);
      if (res.error) throw new Error(res.error);

      toast({
        title: decision === 'approve'
          ? t('data-contracts:publishRequest.toast.approvedTitle', 'Publish Approved')
          : t('data-contracts:publishRequest.toast.deniedTitle', 'Publish Denied'),
        description: decision === 'approve'
          ? t('data-contracts:publishRequest.toast.approvedDescription', 'Marketplace publish request has been approved.')
          : t('data-contracts:publishRequest.toast.deniedDescription', 'Marketplace publish request has been denied.')
      });
      onDecisionMade();
      onOpenChange(false);
    } catch (e: any) {
      toast({
        title: t('data-contracts:publishRequest.toast.failedTitle', 'Failed'),
        description: e.message || t('data-contracts:publishRequest.toast.couldNotSubmit', 'Could not submit decision'),
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
            <Rocket className="h-5 w-5" />
            {t('data-contracts:publishRequest.title', 'Handle Marketplace Publish Request')}
          </DialogTitle>
        </DialogHeader>
        <div className="space-y-4">
          <div className="p-3 bg-muted/50 rounded-lg border space-y-2">
            <div className="text-sm text-muted-foreground">
              <span className="font-medium">{t('data-contracts:publishRequest.requesterLabel', 'Requester:')}</span> {requesterEmail}
            </div>
            <div className="text-sm text-muted-foreground">
              <span className="font-medium">{t('data-contracts:publishRequest.contractIdLabel', 'Contract ID:')}</span> <span className="font-mono">{contractId}</span>
            </div>
            {contractName && (
              <div className="text-sm font-medium">{contractName}</div>
            )}
          </div>

          <div className="space-y-2">
            <Label htmlFor="publish-message">{t('data-contracts:publishRequest.responseMessageLabel', 'Response Message (optional)')}</Label>
            <Textarea
              id="publish-message"
              value={message}
              onChange={(e) => setMessage(e.target.value)}
              placeholder={t('data-contracts:publishRequest.responseMessagePlaceholder', 'Add notes about your decision...')}
              className="min-h-[100px]"
            />
            <p className="text-xs text-muted-foreground">
              {t('data-contracts:publishRequest.messageHint', 'This message will be sent to the requester along with your decision.')}
            </p>
          </div>

          <div className="p-3 bg-blue-50 dark:bg-blue-950/20 rounded-lg border border-blue-200 dark:border-blue-800">
            <p className="text-sm text-blue-900 dark:text-blue-100">
              <strong>{t('data-contracts:publishRequest.noteLabel', 'Note:')}</strong> {t('data-contracts:publishRequest.noteText', 'Approving this request will publish the contract to the organization-wide marketplace, making it visible to all users.')}
            </p>
          </div>
        </div>
        <DialogFooter className="gap-2">
          <Button variant="outline" onClick={() => onOpenChange(false)} disabled={submitting}>
            {t('common:actions.cancel', 'Cancel')}
          </Button>
          <Button variant="destructive" onClick={() => submitDecision('deny')} disabled={submitting}>
            {t('data-contracts:publishRequest.deny', 'Deny')}
          </Button>
          <Button onClick={() => submitDecision('approve')} disabled={submitting}>
            {t('data-contracts:publishRequest.approveAndPublish', 'Approve & Publish')}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
