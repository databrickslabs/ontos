import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogFooter, DialogDescription } from '@/components/ui/dialog';
import { Button } from '@/components/ui/button';
import { Textarea } from '@/components/ui/textarea';
import { Label } from '@/components/ui/label';
import { Alert, AlertDescription } from '@/components/ui/alert';
import { useToast } from '@/hooks/use-toast';
import { useApi } from '@/hooks/use-api';
import { useNotificationsStore } from '@/stores/notifications-store';
import { Loader2, Shield, AlertCircle } from 'lucide-react';

interface RequestRoleAccessDialogProps {
  isOpen: boolean;
  onOpenChange: (open: boolean) => void;
  roleId: string;
  roleName: string;
  roleDescription?: string;
}

export default function RequestRoleAccessDialog({
  isOpen,
  onOpenChange,
  roleId,
  roleName,
  roleDescription
}: RequestRoleAccessDialogProps) {
  const { t } = useTranslation(['settings', 'common']);
  const { post } = useApi();
  const { toast } = useToast();
  const refreshNotifications = useNotificationsStore((state) => state.refreshNotifications);
  const [reason, setReason] = useState('');
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const handleSubmit = async () => {
    // Validate reason
    if (!reason.trim()) {
      setError(t('settings:roles.requestAccess.reasonRequired'));
      return;
    }

    if (reason.trim().length < 10) {
      setError(t('settings:roles.requestAccess.reasonTooShort'));
      return;
    }

    setError(null);
    setSubmitting(true);

    try {
      const response = await post(`/api/user/request-role/${roleId}`, {
        message: reason.trim(),
      });

      if (response.error) {
        throw new Error(response.error);
      }

      toast({
        title: t('settings:roles.requestAccess.submittedTitle'),
        description: t('settings:roles.requestAccess.submittedDescription', { role: roleName })
      });

      // Refresh notifications to show any new ones
      refreshNotifications();

      // Reset form and close dialog
      setReason('');
      onOpenChange(false);

    } catch (e: any) {
      setError(e.message || t('settings:roles.requestAccess.submitFailed'));
      toast({
        title: t('common:status.error'),
        description: e.message || t('settings:roles.requestAccess.submitFailed'),
        variant: 'destructive'
      });
    } finally {
      setSubmitting(false);
    }
  };

  const handleCancel = () => {
    setReason('');
    setError(null);
    onOpenChange(false);
  };

  return (
    <Dialog open={isOpen} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-[500px]">
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2">
            <Shield className="h-5 w-5 text-primary" />
            {t('settings:roles.requestAccess.title')}
          </DialogTitle>
          <DialogDescription>
            {t('settings:roles.requestAccess.description')}
          </DialogDescription>
        </DialogHeader>

        <div className="space-y-4">
          {/* Role Information */}
          <div className="p-3 bg-muted/50 rounded-lg border">
            <div className="flex items-center gap-2 text-sm text-muted-foreground">
              <span className="font-medium">{t('settings:roles.requestAccess.roleLabel')}</span>
              <span className="font-semibold text-foreground">{roleName}</span>
            </div>
            {roleDescription && (
              <div className="text-sm text-muted-foreground mt-1">{roleDescription}</div>
            )}
          </div>

          {/* Reason Field */}
          <div className="space-y-2">
            <Label htmlFor="role-access-reason" className="text-sm font-medium">
              {t('settings:roles.requestAccess.reasonLabel')}
            </Label>
            <Textarea
              id="role-access-reason"
              value={reason}
              onChange={(e) => setReason(e.target.value)}
              placeholder={t('settings:roles.requestAccess.reasonPlaceholder')}
              className="min-h-[100px] resize-none"
              disabled={submitting}
            />
            <div className="text-xs text-muted-foreground">
              {t('settings:roles.requestAccess.reasonHelp')}
            </div>
          </div>

          {/* Error Alert */}
          {error && (
            <Alert variant="destructive">
              <AlertCircle className="h-4 w-4" />
              <AlertDescription>{error}</AlertDescription>
            </Alert>
          )}
        </div>

        <DialogFooter className="gap-2 sm:gap-0">
          <Button
            variant="outline"
            onClick={handleCancel}
            disabled={submitting}
          >
            {t('common:actions.cancel')}
          </Button>
          <Button
            onClick={handleSubmit}
            disabled={submitting || !reason.trim()}
          >
            {submitting && <Loader2 className="mr-2 h-4 w-4 animate-spin" />}
            {submitting ? t('settings:roles.requestAccess.sending') : t('settings:roles.requestAccess.send')}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
