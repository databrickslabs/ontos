import { useState } from 'react';
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogFooter, DialogDescription } from '@/components/ui/dialog';
import { Button } from '@/components/ui/button';
import { Textarea } from '@/components/ui/textarea';
import { Label } from '@/components/ui/label';
import { Alert, AlertDescription } from '@/components/ui/alert';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import { useToast } from '@/hooks/use-toast';
import { useApi } from '@/hooks/use-api';
import { useNotificationsStore } from '@/stores/notifications-store';
import { Loader2, AlertCircle, ClipboardCheck, RefreshCw } from 'lucide-react';

type RequestType = 'review' | 'status_change';

const AR_STATUSES = ['draft', 'active', 'needs_review', 'retired'] as const;

interface Props {
  isOpen: boolean;
  onOpenChange: (open: boolean) => void;
  relationId: string;
  relationName?: string;
  relationStatus?: string;
  onSuccess?: () => void;
}

/**
 * Request-action dialog for an Authority Relation, mirroring the Data Contract /
 * Data Product "Request..." dialog. v1 offers:
 *  - Review: start the N-functional review process (creates a per-reviewer Asset
 *    Review and fires the review workflow);
 *  - Change Status: move the AR through its lifecycle (activation is gated by the
 *    DNA-Coefficient ceiling + affirmations — the backend returns a 409 if not met).
 */
export default function RequestAuthorityActionDialog({
  isOpen, onOpenChange, relationId, relationName, relationStatus, onSuccess,
}: Props) {
  const { post } = useApi();
  const { toast } = useToast();
  const refreshNotifications = useNotificationsStore((s) => s.refreshNotifications);

  const [requestType, setRequestType] = useState<RequestType>('review');
  const [message, setMessage] = useState('');
  const [targetStatus, setTargetStatus] = useState('');
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const config = (type: RequestType) => {
    switch (type) {
      case 'review':
        return {
          icon: <ClipboardCheck className="h-5 w-5" />,
          title: 'Request Review',
          description: 'Start the N-functional review: each assigned reviewer gets an Asset Review to confirm the relation reflects reality, and the review workflow is fired.',
        };
      case 'status_change':
        return {
          icon: <RefreshCw className="h-5 w-5" />,
          title: 'Change Status',
          description: 'Move this Authority Relation through its lifecycle. Activation requires the DNA-Coefficient to be measured within its ceiling and every required affirmation completed.',
        };
    }
  };

  const reset = () => { setMessage(''); setTargetStatus(''); setError(null); };
  const handleCancel = () => { reset(); onOpenChange(false); };

  const handleSubmit = async () => {
    setError(null);
    if (requestType === 'status_change' && !targetStatus) {
      setError('Please select a target status.');
      return;
    }
    setSubmitting(true);
    try {
      let res;
      if (requestType === 'review') {
        res = await post(`/api/authority/relations/${relationId}/start-review`, { message: message.trim() || undefined });
      } else {
        res = await post(`/api/authority/relations/${relationId}/status`, { status: targetStatus });
      }
      if (res.error) throw new Error(res.error);

      if (requestType === 'review') {
        const notified = (res.data as any)?.reviewers_notified ?? 0;
        toast({ title: 'Review requested', description: `${notified} reviewer(s) notified.` });
      } else {
        toast({ title: 'Status changed', description: `Status set to "${targetStatus}".` });
      }
      refreshNotifications();
      onSuccess?.();
      reset();
      onOpenChange(false);
    } catch (e: any) {
      setError(e.message || 'Failed to submit request');
      toast({ title: 'Error', description: e.message || 'Failed to submit request', variant: 'destructive' });
    } finally {
      setSubmitting(false);
    }
  };

  const current = config(requestType);

  return (
    <Dialog open={isOpen} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-[600px]">
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2">Request Action</DialogTitle>
          <DialogDescription>Select the type of request you want to submit for this Authority Relation.</DialogDescription>
        </DialogHeader>

        <div className="space-y-4">
          <div className="p-3 bg-muted/50 rounded-lg border">
            <div className="flex items-center gap-2 text-sm text-muted-foreground">
              <span className="font-medium">Authority Relation:</span>
              <span className="font-mono">{relationId}</span>
            </div>
            {relationName && <div className="text-sm font-medium mt-1">{relationName}</div>}
            {relationStatus && (
              <div className="text-xs text-muted-foreground mt-1">Status: <span className="uppercase">{relationStatus}</span></div>
            )}
          </div>

          <div className="space-y-3">
            <Label className="text-sm font-medium">Request Type *</Label>
            <Select value={requestType} onValueChange={(v) => setRequestType(v as RequestType)}>
              <SelectTrigger>
                <SelectValue>
                  <div className="flex items-center gap-2">{current.icon}<span>{current.title}</span></div>
                </SelectValue>
              </SelectTrigger>
              <SelectContent>
                {(['review', 'status_change'] as RequestType[]).map((type) => {
                  const c = config(type);
                  return (
                    <SelectItem key={type} value={type}>
                      <div className="flex items-center gap-2">{c.icon}<span>{c.title}</span></div>
                    </SelectItem>
                  );
                })}
              </SelectContent>
            </Select>
            <div className="p-3 bg-muted/50 rounded-lg border text-sm">
              <p className="text-muted-foreground">{current.description}</p>
            </div>
          </div>

          {requestType === 'review' && (
            <div className="space-y-2">
              <Label htmlFor="ar-review-message" className="text-sm font-medium">Message (optional)</Label>
              <Textarea
                id="ar-review-message"
                value={message}
                onChange={(e) => setMessage(e.target.value)}
                placeholder="Add any notes for the reviewers…"
                className="min-h-[80px] resize-none"
                disabled={submitting}
              />
            </div>
          )}

          {requestType === 'status_change' && (
            <div className="space-y-2">
              <Label className="text-sm font-medium">Target Status *</Label>
              <Select value={targetStatus} onValueChange={setTargetStatus} disabled={submitting}>
                <SelectTrigger><SelectValue placeholder="Choose target status…" /></SelectTrigger>
                <SelectContent>
                  {AR_STATUSES.filter((s) => s !== (relationStatus || '').toLowerCase()).map((s) => (
                    <SelectItem key={s} value={s}>{s}</SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
          )}

          {error && (
            <Alert variant="destructive"><AlertCircle className="h-4 w-4" /><AlertDescription>{error}</AlertDescription></Alert>
          )}
        </div>

        <DialogFooter className="gap-2 sm:gap-0">
          <Button variant="outline" onClick={handleCancel} disabled={submitting}>Cancel</Button>
          <Button onClick={handleSubmit} disabled={submitting}>
            {submitting && <Loader2 className="mr-2 h-4 w-4 animate-spin" />}
            {submitting ? 'Submitting…' : (requestType === 'status_change' ? 'Change Status' : 'Send Request')}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
