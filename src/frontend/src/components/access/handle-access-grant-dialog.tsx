import { useState, useEffect } from 'react';
import { useTranslation } from 'react-i18next';
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogFooter, DialogDescription } from '@/components/ui/dialog';
import { Button } from '@/components/ui/button';
import { Textarea } from '@/components/ui/textarea';
import { Label } from '@/components/ui/label';
// Alert components removed - unused
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import { Badge } from '@/components/ui/badge';
import { useToast } from '@/hooks/use-toast';
import { useApi } from '@/hooks/use-api';
import { useNotificationsStore } from '@/stores/notifications-store';
import { 
  Loader2, 
  Clock, 
  User, 
  CheckCircle, 
  XCircle, 
  MessageSquare,
  Calendar,
  Shield
} from 'lucide-react';

type PermissionLevel = 'READ' | 'WRITE' | 'MANAGE';

interface AccessGrantRequest {
  id: string;
  requester_email: string;
  entity_type: string;
  entity_id: string;
  entity_name?: string;
  requested_duration_days: number;
  permission_level: string;
  reason?: string;
  status: string;
  created_at: string;
}

interface HandleAccessGrantDialogProps {
  isOpen: boolean;
  onOpenChange: (open: boolean) => void;
  request: AccessGrantRequest;
  onDecisionMade?: () => void;
}

const PERMISSION_LABELS: Record<PermissionLevel, string> = {
  READ: 'Read Only',
  WRITE: 'Read & Write',
  MANAGE: 'Full Access (Manage)',
};

const DEFAULT_DURATION_OPTIONS = [7, 14, 30, 60, 90, 180, 365];

export default function HandleAccessGrantDialog({
  isOpen,
  onOpenChange,
  request,
  onDecisionMade,
}: HandleAccessGrantDialogProps) {
  const { get, post } = useApi();
  const { toast } = useToast();
  const { t } = useTranslation(['access-grants', 'common']);
  const refreshNotifications = useNotificationsStore((state) => state.refreshNotifications);

  const [message, setMessage] = useState('');
  const [grantedDuration, setGrantedDuration] = useState<number>(request.requested_duration_days);
  const [grantedPermission, setGrantedPermission] = useState<PermissionLevel>(
    (request.permission_level as PermissionLevel) || 'READ'
  );
  const [durationOptions, setDurationOptions] = useState<number[]>(DEFAULT_DURATION_OPTIONS);
  const [submitting, setSubmitting] = useState(false);
  const [loadingConfig, setLoadingConfig] = useState(false);

  // Fetch duration configuration when dialog opens
  useEffect(() => {
    if (isOpen) {
      fetchDurationConfig();
      // Reset to requested values when opening
      setGrantedDuration(request.requested_duration_days);
      setGrantedPermission((request.permission_level as PermissionLevel) || 'READ');
      setMessage('');
    }
  }, [isOpen, request]);

  const fetchDurationConfig = async () => {
    setLoadingConfig(true);
    try {
      const response = await get<{ duration_options: number[] }>(`/api/access-grants/config/${request.entity_type}`);
      if (response.data?.duration_options) {
        setDurationOptions(response.data.duration_options);
      }
    } catch (err) {
      console.warn('Failed to fetch duration config, using defaults:', err);
    } finally {
      setLoadingConfig(false);
    }
  };

  const handleDecision = async (approved: boolean) => {
    setSubmitting(true);

    try {
      const payload: any = {
        request_id: request.id,
        approved,
        message: message.trim() || undefined,
      };

      if (approved) {
        payload.granted_duration_days = grantedDuration;
        payload.permission_level = grantedPermission;
      }

      const response = await post('/api/access-grants/handle', payload);

      if (response.error) {
        throw new Error(response.error);
      }

      toast({
        title: approved
          ? t('access-grants:handle.approvedTitle', 'Request Approved')
          : t('access-grants:handle.deniedTitle', 'Request Denied'),
        description: approved
          ? t('access-grants:handle.approvedDescription', {
              duration: formatDuration(grantedDuration),
              defaultValue: 'Access granted for {{duration}}.',
            })
          : t('access-grants:handle.deniedDescription', 'The requester has been notified.'),
      });

      refreshNotifications();
      setMessage('');
      onOpenChange(false);
      
      if (onDecisionMade) {
        onDecisionMade();
      }

    } catch (e: any) {
      toast({
        title: t('common:toast.error', 'Error'),
        description: e.message || t('access-grants:handle.error', 'Failed to process decision'),
        variant: 'destructive'
      });
    } finally {
      setSubmitting(false);
    }
  };

  const formatDuration = (days: number): string => {
    if (days < 30) return t('access-grants:duration.days', { count: days });
    if (days === 30) return t('access-grants:duration.months', { count: 1 });
    if (days === 60) return t('access-grants:duration.months', { count: 2 });
    if (days === 90) return t('access-grants:duration.months', { count: 3 });
    if (days === 180) return t('access-grants:duration.months', { count: 6 });
    if (days === 365) return t('access-grants:duration.years', { count: 1 });
    return t('access-grants:duration.days', { count: days });
  };

  const formatDate = (dateString: string): string => {
    return new Date(dateString).toLocaleString();
  };

  return (
    <Dialog open={isOpen} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-[560px] flex flex-col max-h-[85vh] overflow-hidden">
        <DialogHeader className="shrink-0">
          <DialogTitle className="flex items-center gap-2">
            <Shield className="h-5 w-5 text-primary" />
            {t('access-grants:handle.title', 'Handle Access Request')}
          </DialogTitle>
          <DialogDescription>
            {t('access-grants:handle.description', 'Review this access request and approve or deny it.')}
          </DialogDescription>
        </DialogHeader>

        <div className="space-y-4 flex-1 overflow-y-auto px-1 -mx-1">
          {/* Request Details */}
          <div className="p-4 bg-muted/50 rounded-lg border space-y-3">
            <div className="flex items-center gap-2">
              <User className="h-4 w-4 text-muted-foreground" />
              <span className="text-sm font-medium">{t('access-grants:handle.fields.requester', 'Requester:')}</span>
              <span className="text-sm">{request.requester_email}</span>
            </div>

            <div className="flex items-center gap-2">
              <span className="text-sm font-medium">{t('access-grants:handle.fields.resource', 'Resource:')}</span>
              <Badge variant="outline">{request.entity_type}</Badge>
              <span className="text-sm font-mono">{request.entity_name || request.entity_id}</span>
            </div>

            <div className="flex items-center gap-2">
              <Clock className="h-4 w-4 text-muted-foreground" />
              <span className="text-sm font-medium">{t('access-grants:handle.fields.requestedDuration', 'Requested Duration:')}</span>
              <Badge variant="secondary">{formatDuration(request.requested_duration_days)}</Badge>
            </div>

            <div className="flex items-center gap-2">
              <Shield className="h-4 w-4 text-muted-foreground" />
              <span className="text-sm font-medium">{t('access-grants:handle.fields.requestedPermission', 'Requested Permission:')}</span>
              <Badge variant="secondary">
                {t(`access-grants:permissionOptions.${request.permission_level}`, PERMISSION_LABELS[request.permission_level as PermissionLevel] || request.permission_level)}
              </Badge>
            </div>

            <div className="flex items-center gap-2">
              <Calendar className="h-4 w-4 text-muted-foreground" />
              <span className="text-sm font-medium">{t('access-grants:handle.fields.submitted', 'Submitted:')}</span>
              <span className="text-sm text-muted-foreground">{formatDate(request.created_at)}</span>
            </div>

            {request.reason && (
              <div className="pt-2 border-t">
                <div className="flex items-start gap-2">
                  <MessageSquare className="h-4 w-4 text-muted-foreground mt-0.5" />
                  <div>
                    <span className="text-sm font-medium">{t('access-grants:handle.fields.reason', 'Reason:')}</span>
                    <p className="text-sm text-muted-foreground mt-1">{request.reason}</p>
                  </div>
                </div>
              </div>
            )}
          </div>

          {/* Grant Settings (only shown for approval) */}
          <div className="space-y-3 p-4 border rounded-lg bg-green-50 dark:bg-green-950/20">
            <div className="text-sm font-medium text-green-700 dark:text-green-300">
              {t('access-grants:handle.adjustNote', 'If approving, you can adjust the granted access:')}
            </div>

            {/* Duration to Grant */}
            <div className="space-y-1">
              <Label htmlFor="granted-duration" className="text-sm">
                {t('access-grants:handle.durationToGrant', 'Duration to Grant')}
              </Label>
              <Select
                value={grantedDuration.toString()}
                onValueChange={(value) => setGrantedDuration(parseInt(value, 10))}
                disabled={submitting || loadingConfig}
              >
                <SelectTrigger id="granted-duration">
                  <SelectValue placeholder={t('access-grants:request.duration.placeholder', 'Select duration')} />
                </SelectTrigger>
                <SelectContent>
                  {durationOptions.map((d) => (
                    <SelectItem key={d} value={d.toString()}>
                      {formatDuration(d)}
                      {d === request.requested_duration_days && t('access-grants:handle.requestedSuffix', ' (requested)')}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>

            {/* Permission Level to Grant */}
            <div className="space-y-1">
              <Label htmlFor="granted-permission" className="text-sm">
                {t('access-grants:handle.permissionToGrant', 'Permission Level to Grant')}
              </Label>
              <Select
                value={grantedPermission}
                onValueChange={(value) => setGrantedPermission(value as PermissionLevel)}
                disabled={submitting}
              >
                <SelectTrigger id="granted-permission">
                  <SelectValue placeholder={t('access-grants:permissionSelectPlaceholder', 'Select permission level')} />
                </SelectTrigger>
                <SelectContent>
                  {Object.entries(PERMISSION_LABELS).map(([level, label]) => (
                    <SelectItem key={level} value={level}>
                      {t(`access-grants:permissionOptions.${level}`, label)}
                      {level === request.permission_level && t('access-grants:handle.requestedSuffix', ' (requested)')}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
          </div>

          {/* Message to Requester */}
          <div className="space-y-2">
            <Label htmlFor="admin-message" className="text-sm font-medium">
              {t('access-grants:handle.messageLabel', 'Message to Requester (Optional)')}
            </Label>
            <Textarea
              id="admin-message"
              value={message}
              onChange={(e) => setMessage(e.target.value)}
              placeholder={t('access-grants:handle.messagePlaceholder', 'Add a message for the requester (e.g., approval conditions, denial reason)...')}
              className="min-h-[80px] resize-none"
              disabled={submitting}
            />
          </div>
        </div>

        <DialogFooter className="gap-2 sm:gap-2 flex-col sm:flex-row shrink-0">
          <Button
            variant="outline"
            onClick={() => onOpenChange(false)}
            disabled={submitting}
          >
            {t('common:actions.cancel', 'Cancel')}
          </Button>
          <Button
            variant="destructive"
            onClick={() => handleDecision(false)}
            disabled={submitting}
          >
            {submitting && <Loader2 className="mr-2 h-4 w-4 animate-spin" />}
            <XCircle className="mr-2 h-4 w-4" />
            {t('access-grants:handle.deny', 'Deny')}
          </Button>
          <Button
            variant="default"
            onClick={() => handleDecision(true)}
            disabled={submitting}
          >
            {submitting && <Loader2 className="mr-2 h-4 w-4 animate-spin" />}
            <CheckCircle className="mr-2 h-4 w-4" />
            {t('access-grants:handle.approveWithDuration', {
              duration: formatDuration(grantedDuration),
              defaultValue: 'Approve ({{duration}})',
            })}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

