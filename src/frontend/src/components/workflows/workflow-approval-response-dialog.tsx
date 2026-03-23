import { useState, useEffect } from 'react';
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogFooter,
  DialogDescription,
} from '@/components/ui/dialog';
import { Button } from '@/components/ui/button';
import { Textarea } from '@/components/ui/textarea';
import { Label } from '@/components/ui/label';
import { Loader2, Check, XCircle } from 'lucide-react';
import { useApi } from '@/hooks/use-api';
import { useToast } from '@/hooks/use-toast';

/** Built from GET /api/workflows/for-trigger/for_approval_response (first step used for dialog). */
interface DefaultResponseWorkflowStep {
  workflow_id: string;
  workflow_name: string;
  step_id: string;
  step_name: string;
  step_type: string;
  config: {
    title?: string;
    description?: string;
    required_fields?: Array<{ id: string; label: string; type: string; required?: boolean }>;
  };
}

export interface WorkflowApprovalResponseDialogPayload {
  execution_id: string;
  entity_name?: string;
}

interface WorkflowApprovalResponseDialogProps {
  isOpen: boolean;
  onOpenChange: (open: boolean) => void;
  payload: WorkflowApprovalResponseDialogPayload | null;
  notificationId?: string;
  onDecisionMade?: () => void;
}

export default function WorkflowApprovalResponseDialog({
  isOpen,
  onOpenChange,
  payload,
  notificationId: _notificationId,
  onDecisionMade,
}: WorkflowApprovalResponseDialogProps) {
  const { get, post } = useApi();
  const { toast } = useToast();
  const [stepConfig, setStepConfig] = useState<DefaultResponseWorkflowStep | null>(null);
  const [loadingConfig, setLoadingConfig] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [reason, setReason] = useState('');

  useEffect(() => {
    if (!isOpen) {
      setStepConfig(null);
      setReason('');
      return;
    }
    let cancelled = false;
    setLoadingConfig(true);
    get<{ id: string; name: string; steps: Array<{ step_id: string; name: string | null; step_type: string; config: Record<string, unknown> }> }>(
      '/api/workflows/for-trigger/for_approval_response',
    )
      .then((res) => {
        if (cancelled) return;
        const w = res.data;
        if (w?.steps?.length) {
          const first = w.steps[0];
          setStepConfig({
            workflow_id: w.id,
            workflow_name: w.name,
            step_id: first.step_id,
            step_name: first.name ?? first.step_id,
            step_type: first.step_type,
            config: (first.config ?? {}) as DefaultResponseWorkflowStep['config'],
          });
        } else setStepConfig(null);
      })
      .catch(() => {
        if (!cancelled) setStepConfig(null);
      })
      .finally(() => {
        if (!cancelled) setLoadingConfig(false);
      });
    return () => {
      cancelled = true;
    };
  }, [isOpen, get]);

  const config = stepConfig?.config ?? {};
  const requiredFields = config.required_fields ?? [];
  const reasonField = requiredFields.find((f) => f.id === 'reason' || f.type === 'text');
  const isReasonRequired = reasonField?.required ?? false;

  const handleSubmit = async (approved: boolean) => {
    if (!payload?.execution_id) return;
    if (isReasonRequired && !reason.trim()) {
      toast({
        title: 'Reason required',
        description: 'Please enter a reason for your decision.',
        variant: 'destructive',
      });
      return;
    }
    setSubmitting(true);
    try {
      const response = await post('/api/workflows/handle-approval', {
        execution_id: payload.execution_id,
        approved,
        message: reason.trim() || (approved ? 'Approved' : 'Rejected'),
      });
      if (response.error) {
        toast({
          title: 'Error',
          description: response.error || 'Failed to process approval.',
          variant: 'destructive',
        });
        return;
      }
      toast({
        title: approved ? 'Approved' : 'Rejected',
        description: `${payload.entity_name || 'Request'} has been ${approved ? 'approved' : 'rejected'}.`,
        variant: approved ? 'default' : 'destructive',
      });
      onOpenChange(false);
      onDecisionMade?.();
    } catch (e) {
      console.error('Workflow approval failed:', e);
      toast({
        title: 'Error',
        description: 'Failed to process approval. Please try again.',
        variant: 'destructive',
      });
    } finally {
      setSubmitting(false);
    }
  };

  const title = config.title ?? stepConfig?.step_name ?? 'Approve or reject';
  const description =
    config.description ?? 'Provide a reason for your approval or rejection decision.';

  return (
    <Dialog open={isOpen} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-md">
        <DialogHeader>
          <DialogTitle>{title}</DialogTitle>
          <DialogDescription>{description}</DialogDescription>
        </DialogHeader>
        {loadingConfig ? (
          <div className="flex items-center justify-center py-8">
            <Loader2 className="h-8 w-8 animate-spin text-muted-foreground" />
          </div>
        ) : (
          <>
            <div className="space-y-2">
              <Label htmlFor="approval-reason">
                {reasonField?.label ?? 'Reason for approval or rejection'}
                {isReasonRequired && ' *'}
              </Label>
              <Textarea
                id="approval-reason"
                value={reason}
                onChange={(e) => setReason(e.target.value)}
                placeholder="Enter your reason..."
                rows={3}
                className="resize-none"
                disabled={submitting}
              />
            </div>
            <DialogFooter className="gap-2 sm:gap-0">
              <Button
                variant="destructive"
                disabled={submitting}
                onClick={() => handleSubmit(false)}
              >
                {submitting ? (
                  <Loader2 className="h-4 w-4 animate-spin" />
                ) : (
                  <XCircle className="h-4 w-4" />
                )}
                Reject
              </Button>
              <Button
                variant="default"
                className="bg-green-600 hover:bg-green-700"
                disabled={submitting}
                onClick={() => handleSubmit(true)}
              >
                {submitting ? (
                  <Loader2 className="h-4 w-4 animate-spin" />
                ) : (
                  <Check className="h-4 w-4" />
                )}
                Approve
              </Button>
            </DialogFooter>
          </>
        )}
      </DialogContent>
    </Dialog>
  );
}
