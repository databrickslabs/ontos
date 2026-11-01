import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import {
  Dialog, DialogContent, DialogHeader, DialogTitle, DialogFooter,
} from '@/components/ui/dialog';
import { Button } from '@/components/ui/button';
import { Textarea } from '@/components/ui/textarea';
import { Label } from '@/components/ui/label';
import { useToast } from '@/hooks/use-toast';
import { useApi } from '@/hooks/use-api';
import { contractActionErrorText } from '@/lib/contract-action-error';
import { ArrowRight, RefreshCw } from 'lucide-react';

type Props = {
  isOpen: boolean;
  onOpenChange: (open: boolean) => void;
  contractId: string;
  contractName?: string;
  requesterEmail: string;
  fromStatus?: string;
  targetStatus: string;
  justification?: string;
  onDecisionMade: () => void;
  /** The request was already decided ('approve' / 'deny', or true): shown without actions. */
  decided?: string | boolean;
};

/**
 * An admin's decision on a contract's status change request, opened from the
 * admins' notification. Approving applies the status with handle-status-change
 * (the way a certified contract is deprecated); denying notifies the requester.
 * A decided request opens read-only. An error the API sends without a code is
 * shown as the generic message, not as its English text.
 */
export default function HandleStatusChangeRequestDialog({
  isOpen,
  onOpenChange,
  contractId,
  contractName,
  requesterEmail,
  fromStatus,
  targetStatus,
  justification,
  onDecisionMade,
  decided,
}: Props) {
  const { t } = useTranslation(['data-contracts', 'common']);
  const { post } = useApi();
  const { toast } = useToast();
  const [message, setMessage] = useState('');
  const [submitting, setSubmitting] = useState(false);

  const label = (key: string) => t(`data-contracts:statusChangeRequest.${key}`);
  const statusLabel = (status?: string) =>
    status ? t(`data-contracts:status.${status}`, { defaultValue: status }) : '';

  const submitDecision = async (decision: 'approve' | 'deny') => {
    setSubmitting(true);
    try {
      const res = await post(`/api/data-contracts/${contractId}/handle-status-change`, {
        decision,
        target_status: targetStatus,
        requester_email: requesterEmail,
        message: message || undefined,
      });
      if (res.error) {
        const fallback = t('data-contracts:statusChangeRequest.toast.couldNotSubmit');
        throw new Error(res.errorCode ? contractActionErrorText(res, t, fallback) : fallback);
      }

      const toStatus = statusLabel(targetStatus);
      toast({
        title: decision === 'approve'
          ? t('data-contracts:statusChangeRequest.toast.approvedTitle')
          : t('data-contracts:statusChangeRequest.toast.deniedTitle'),
        description: decision === 'approve'
          ? t('data-contracts:statusChangeRequest.toast.approvedDescription', { toStatus })
          : t('data-contracts:statusChangeRequest.toast.deniedDescription', { toStatus }),
      });
      onDecisionMade();
      onOpenChange(false);
    } catch (e: any) {
      toast({
        title: t('data-contracts:statusChangeRequest.toast.failedTitle'),
        description: e.message || t('data-contracts:statusChangeRequest.toast.couldNotSubmit'),
        variant: 'destructive',
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
            <RefreshCw className="h-5 w-5" />
            {t('data-contracts:statusChangeRequest.title')}
          </DialogTitle>
        </DialogHeader>
        <div className="space-y-4">
          <div className="p-3 bg-muted/50 rounded-lg border space-y-2">
            <div className="text-sm text-muted-foreground">
              <span className="font-medium">{label('requesterLabel')}</span>{' '}
              {requesterEmail}
            </div>
            <div className="text-sm text-muted-foreground">
              <span className="font-medium">{label('contractIdLabel')}</span>{' '}
              <span className="font-mono">{contractId}</span>
            </div>
            {contractName && <div className="text-sm font-medium">{contractName}</div>}
            <div
              className="flex items-center gap-2 text-sm"
              data-testid="status-change-request-statuses"
            >
              <span className="font-medium">{label('statusLabel')}</span>
              {fromStatus && (
                <>
                  <span>{statusLabel(fromStatus)}</span>
                  <ArrowRight className="h-3.5 w-3.5" aria-hidden />
                </>
              )}
              <span className="font-semibold">{statusLabel(targetStatus)}</span>
            </div>
            {justification && (
              <div className="text-sm text-muted-foreground whitespace-pre-wrap">
                <span className="font-medium">{label('justificationLabel')}</span>{' '}
                {justification}
              </div>
            )}
          </div>

          {decided ? (
            <p
              className="text-sm text-muted-foreground"
              data-testid="status-change-request-decided"
            >
              {decided === 'approve'
                ? label('handled.approved')
                : decided === 'deny' ? label('handled.denied') : label('handled.handled')}
            </p>
          ) : (
          <div className="space-y-2">
            <Label htmlFor="status-change-message">
              {t('data-contracts:statusChangeRequest.responseMessageLabel')}
            </Label>
            <Textarea
              id="status-change-message"
              value={message}
              onChange={(e) => setMessage(e.target.value)}
              placeholder={t('data-contracts:statusChangeRequest.responseMessagePlaceholder')}
              className="min-h-[100px]"
            />
            <p className="text-xs text-muted-foreground">
              {t('data-contracts:statusChangeRequest.messageHint')}
            </p>
          </div>
          )}
        </div>
        <DialogFooter className="gap-2">
          {decided ? (
            <Button variant="outline" onClick={() => onOpenChange(false)}>
              {t('common:actions.close')}
            </Button>
          ) : (
          <>
          <Button variant="outline" onClick={() => onOpenChange(false)} disabled={submitting}>
            {t('common:actions.cancel', 'Cancel')}
          </Button>
          <Button
            variant="destructive"
            onClick={() => submitDecision('deny')}
            disabled={submitting}
          >
            {t('data-contracts:statusChangeRequest.deny')}
          </Button>
          <Button onClick={() => submitDecision('approve')} disabled={submitting}>
            {t('data-contracts:statusChangeRequest.approve')}
          </Button>
          </>
          )}
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
