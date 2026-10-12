import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogFooter } from '@/components/ui/dialog';
import { Button } from '@/components/ui/button';
import { Textarea } from '@/components/ui/textarea';
import { Label } from '@/components/ui/label';
import { Checkbox } from '@/components/ui/checkbox';
import { useToast } from '@/hooks/use-toast';
import { useApi } from '@/hooks/use-api';
import { Database } from 'lucide-react';

type Props = {
  isOpen: boolean;
  onOpenChange: (open: boolean) => void;
  contractId: string;
  contractName?: string;
  requesterEmail: string;
  catalog?: string;
  schema?: string;
  onDecisionMade: () => void;
};

export default function HandleDeployRequestDialog({
  isOpen,
  onOpenChange,
  contractId,
  contractName,
  requesterEmail,
  catalog,
  schema,
  onDecisionMade
}: Props) {
  const { t } = useTranslation(['data-contracts', 'common']);
  const { post } = useApi();
  const { toast } = useToast();
  const [message, setMessage] = useState('');
  const [executeDeployment, setExecuteDeployment] = useState(false);
  const [submitting, setSubmitting] = useState(false);

  const submitDecision = async (decision: 'approve' | 'deny') => {
    setSubmitting(true);
    try {
      const body = {
        decision,
        message: message || undefined,
        execute_deployment: decision === 'approve' ? executeDeployment : false,
      };
      const res = await post(`/api/data-contracts/${contractId}/handle-deploy`, body);
      if (res.error) throw new Error(res.error);

      let description = decision === 'approve'
        ? t('data-contracts:deployRequest.toast.approvedDescription', 'Deployment request has been approved.')
        : t('data-contracts:deployRequest.toast.deniedDescription', 'Deployment request has been denied.');
      if (decision === 'approve' && executeDeployment) {
        description += ' ' + t('data-contracts:deployRequest.toast.deploymentInitiated', 'Deployment has been initiated.');
      }

      toast({
        title: decision === 'approve'
          ? t('data-contracts:deployRequest.toast.approvedTitle', 'Deploy Approved')
          : t('data-contracts:deployRequest.toast.deniedTitle', 'Deploy Denied'),
        description
      });
      onDecisionMade();
      onOpenChange(false);
    } catch (e: any) {
      toast({
        title: t('data-contracts:deployRequest.toast.failedTitle', 'Failed'),
        description: e.message || t('data-contracts:deployRequest.toast.couldNotSubmit', 'Could not submit decision'),
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
            <Database className="h-5 w-5" />
            {t('data-contracts:deployRequest.title', 'Handle Deployment Request')}
          </DialogTitle>
        </DialogHeader>
        <div className="space-y-4">
          <div className="p-3 bg-muted/50 rounded-lg border space-y-2">
            <div className="text-sm text-muted-foreground">
              <span className="font-medium">{t('data-contracts:deployRequest.requesterLabel', 'Requester:')}</span> {requesterEmail}
            </div>
            <div className="text-sm text-muted-foreground">
              <span className="font-medium">{t('data-contracts:deployRequest.contractIdLabel', 'Contract ID:')}</span> <span className="font-mono">{contractId}</span>
            </div>
            {contractName && (
              <div className="text-sm font-medium">{contractName}</div>
            )}
            {(catalog || schema) && (
              <div className="text-sm text-muted-foreground mt-2">
                <span className="font-medium">{t('data-contracts:deployRequest.targetLabel', 'Target:')}</span>{' '}
                {catalog && schema ? `${catalog}.${schema}` : catalog || schema || t('data-contracts:deployRequest.notSpecified', 'Not specified')}
              </div>
            )}
          </div>

          <div className="space-y-2">
            <Label htmlFor="deploy-message">{t('data-contracts:deployRequest.responseMessageLabel', 'Response Message (optional)')}</Label>
            <Textarea
              id="deploy-message"
              value={message}
              onChange={(e) => setMessage(e.target.value)}
              placeholder={t('data-contracts:deployRequest.responseMessagePlaceholder', 'Add notes about your decision...')}
              className="min-h-[100px]"
            />
            <p className="text-xs text-muted-foreground">
              {t('data-contracts:deployRequest.messageHint', 'This message will be sent to the requester along with your decision.')}
            </p>
          </div>

          <div className="flex items-start space-x-3 p-3 rounded-lg border bg-blue-50 dark:bg-blue-950/20 border-blue-200 dark:border-blue-800">
            <Checkbox
              id="execute-deploy"
              checked={executeDeployment}
              onCheckedChange={(checked) => setExecuteDeployment(checked as boolean)}
              disabled={submitting}
            />
            <div className="flex-1">
              <label htmlFor="execute-deploy" className="text-sm font-medium cursor-pointer">
                {t('data-contracts:deployRequest.executeLabel', 'Execute deployment immediately upon approval')}
              </label>
              <p className="text-xs text-muted-foreground mt-1">
                {t('data-contracts:deployRequest.executeHint', 'If checked, the deployment will be triggered automatically when you approve this request.')}
              </p>
            </div>
          </div>

          <div className="p-3 bg-amber-50 dark:bg-amber-950/20 rounded-lg border border-amber-200 dark:border-amber-800">
            <p className="text-sm text-amber-900 dark:text-amber-100">
              <strong>{t('data-contracts:deployRequest.warningLabel', 'Warning:')}</strong> {t('data-contracts:deployRequest.warningText', 'Deployment will create physical assets in Unity Catalog. Ensure you have reviewed the contract schema and configuration.')}
            </p>
          </div>
        </div>
        <DialogFooter className="gap-2">
          <Button variant="outline" onClick={() => onOpenChange(false)} disabled={submitting}>
            {t('common:actions.cancel', 'Cancel')}
          </Button>
          <Button variant="destructive" onClick={() => submitDecision('deny')} disabled={submitting}>
            {t('data-contracts:deployRequest.deny', 'Deny')}
          </Button>
          <Button onClick={() => submitDecision('approve')} disabled={submitting}>
            {executeDeployment ? t('data-contracts:deployRequest.approveAndDeploy', 'Approve & Deploy') : t('common:actions.approve', 'Approve')}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
