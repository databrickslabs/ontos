import React, { useState, useEffect } from 'react';
import { Trans, useTranslation } from 'react-i18next';
import { Button } from '@/components/ui/button';
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogDescription,
  DialogFooter,
  DialogClose,
} from '@/components/ui/dialog';
import { Label } from '@/components/ui/label';
import { Textarea } from '@/components/ui/textarea';
import { useApi } from '@/hooks/use-api';
import { useToast } from '@/hooks/use-toast';
import { Loader2 } from 'lucide-react';

interface ConfirmRoleRequestDialogProps {
  isOpen: boolean;
  onOpenChange: (open: boolean) => void;
  requesterEmail: string;
  roleId: string;
  roleName: string;
  requesterMessage?: string; // Optional message from the requester
  onDecisionMade: () => void; // Callback after decision is submitted
}

const ConfirmRoleRequestDialog: React.FC<ConfirmRoleRequestDialogProps> = ({
  isOpen,
  onOpenChange,
  requesterEmail,
  roleId,
  roleName,
  requesterMessage,
  onDecisionMade,
}) => {
  const { t } = useTranslation(['settings', 'common']);
  const [decisionMessage, setDecisionMessage] = useState('');
  const [isSubmitting, setIsSubmitting] = useState(false);
  const { post } = useApi();
  const { toast } = useToast();

  // Reset the decision message when dialog opens
  useEffect(() => {
    if (isOpen) {
      setDecisionMessage('');
    }
  }, [isOpen]);

  const handleSubmit = async (approved: boolean) => {
    setIsSubmitting(true);
    try {
        const payload = {
            requester_email: requesterEmail,
            role_id: roleId,
            approved: approved,
            message: decisionMessage,
        };

        // Send the request directly (backend expects HandleRoleRequest model)
        const response = await post('/api/settings/roles/handle-request', payload);
        if (response.error) {
             throw new Error(response.error);
        }

        toast({
            title: approved
              ? t('settings:roles.confirmRequest.approvedTitle')
              : t('settings:roles.confirmRequest.deniedTitle'),
            description: t('settings:roles.confirmRequest.decisionSubmitted', { email: requesterEmail, role: roleName }),
        });
        onDecisionMade(); // Notify parent component
        onOpenChange(false); // Close the dialog
    } catch (err: any) {
        toast({
            title: t('settings:roles.confirmRequest.submissionFailed'),
            description: err.message || t('settings:roles.confirmRequest.submissionFailedDescription'),
            variant: 'destructive',
        });
    } finally {
        setIsSubmitting(false);
    }
  };

  return (
    <Dialog open={isOpen} onOpenChange={onOpenChange}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>{t('settings:roles.confirmRequest.title')}</DialogTitle>
          <DialogDescription>
            <Trans
              i18nKey="settings:roles.confirmRequest.reviewPrompt"
              values={{ email: requesterEmail, role: roleName }}
              components={{ strong: <strong /> }}
            />
          </DialogDescription>
        </DialogHeader>

        <div className="space-y-4 py-4">
          {/* Display requester's message if available */}
          {requesterMessage && (
            <div className="space-y-2">
              <Label className="text-sm font-medium">{t('settings:roles.confirmRequest.requesterReasonLabel')}</Label>
              <div className="p-3 bg-muted/50 rounded-lg border text-sm">
                {requesterMessage}
              </div>
            </div>
          )}

          {/* Admin's response message */}
          <div className="space-y-2">
            <Label htmlFor="decision-message">{t('settings:roles.confirmRequest.messageLabel')}</Label>
            <Textarea
                id="decision-message"
                value={decisionMessage}
                onChange={(e) => setDecisionMessage(e.target.value)}
                placeholder={t('settings:roles.confirmRequest.messagePlaceholder')}
                className="resize-none"
                disabled={isSubmitting}
            />
          </div>
        </div>
        <DialogFooter className="gap-2 sm:justify-between">
            <Button
                variant="destructive"
                onClick={() => handleSubmit(false)}
                disabled={isSubmitting}
            >
                {isSubmitting ? <Loader2 className="mr-2 h-4 w-4 animate-spin" /> : null}
                {t('settings:roles.confirmRequest.deny')}
            </Button>
           <div className="flex gap-2">
             <DialogClose asChild>
                <Button variant="outline" disabled={isSubmitting}>{t('common:actions.cancel')}</Button>
            </DialogClose>
            <Button
                onClick={() => handleSubmit(true)}
                disabled={isSubmitting}
            >
                {isSubmitting ? <Loader2 className="mr-2 h-4 w-4 animate-spin" /> : null}
                {t('settings:roles.confirmRequest.approve')}
            </Button>
           </div>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
};

export default ConfirmRoleRequestDialog; 