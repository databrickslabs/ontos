import { useState } from 'react';
import { useTranslation } from 'react-i18next';
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
  const { t } = useTranslation(['authority-resolution', 'common']);
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
          title: t('request.types.review.title'),
          description: t('request.types.review.description'),
        };
      case 'status_change':
        return {
          icon: <RefreshCw className="h-5 w-5" />,
          title: t('request.types.statusChange.title'),
          description: t('request.types.statusChange.description'),
        };
    }
  };

  const reset = () => { setMessage(''); setTargetStatus(''); setError(null); };
  const handleCancel = () => { reset(); onOpenChange(false); };

  const handleSubmit = async () => {
    setError(null);
    if (requestType === 'status_change' && !targetStatus) {
      setError(t('request.errors.selectStatus'));
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
        toast({ title: t('request.toasts.reviewRequested'), description: t('request.toasts.reviewersNotified', { count: notified }) });
      } else {
        toast({ title: t('request.toasts.statusChanged'), description: t('request.toasts.statusSetTo', { status: targetStatus }) });
      }
      refreshNotifications();
      onSuccess?.();
      reset();
      onOpenChange(false);
    } catch (e: any) {
      setError(e.message || t('request.errors.submitFailed'));
      toast({ title: t('common:status.error'), description: e.message || t('request.errors.submitFailed'), variant: 'destructive' });
    } finally {
      setSubmitting(false);
    }
  };

  const current = config(requestType);

  return (
    <Dialog open={isOpen} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-[600px]">
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2">{t('request.dialog.title')}</DialogTitle>
          <DialogDescription>{t('request.dialog.description')}</DialogDescription>
        </DialogHeader>

        <div className="space-y-4">
          <div className="p-3 bg-muted/50 rounded-lg border">
            <div className="flex items-center gap-2 text-sm text-muted-foreground">
              <span className="font-medium">{t('request.relationInfo.label')}:</span>
              <span className="font-mono">{relationId}</span>
            </div>
            {relationName && <div className="text-sm font-medium mt-1">{relationName}</div>}
            {relationStatus && (
              <div className="text-xs text-muted-foreground mt-1">{t('request.relationInfo.status')}: <span className="uppercase">{relationStatus}</span></div>
            )}
          </div>

          <div className="space-y-3">
            <Label className="text-sm font-medium">{t('request.form.requestType')}</Label>
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
              <Label htmlFor="ar-review-message" className="text-sm font-medium">{t('request.form.message')}</Label>
              <Textarea
                id="ar-review-message"
                value={message}
                onChange={(e) => setMessage(e.target.value)}
                placeholder={t('request.form.messagePlaceholder')}
                className="min-h-[80px] resize-none"
                disabled={submitting}
              />
            </div>
          )}

          {requestType === 'status_change' && (
            <div className="space-y-2">
              <Label className="text-sm font-medium">{t('request.form.targetStatus')}</Label>
              <Select value={targetStatus} onValueChange={setTargetStatus} disabled={submitting}>
                <SelectTrigger><SelectValue placeholder={t('request.form.statusPlaceholder')} /></SelectTrigger>
                <SelectContent>
                  {AR_STATUSES.filter((s) => s !== (relationStatus || '').toLowerCase()).map((s) => (
                    <SelectItem key={s} value={s}>{t(`status.${s}`, { defaultValue: s })}</SelectItem>
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
          <Button variant="outline" onClick={handleCancel} disabled={submitting}>{t('common:actions.cancel')}</Button>
          <Button onClick={handleSubmit} disabled={submitting}>
            {submitting && <Loader2 className="mr-2 h-4 w-4 animate-spin" />}
            {submitting ? t('request.actions.submitting') : (requestType === 'status_change' ? t('request.actions.changeStatus') : t('request.actions.sendRequest'))}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
