import { useState, useEffect } from 'react';
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogFooter, DialogDescription } from '@/components/ui/dialog';
import { Button } from '@/components/ui/button';
import { Textarea } from '@/components/ui/textarea';
import { Label } from '@/components/ui/label';
import { Alert, AlertDescription } from '@/components/ui/alert';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import { useToast } from '@/hooks/use-toast';
import { useApi } from '@/hooks/use-api';
import { useNotificationsStore } from '@/stores/notifications-store';
import { Loader2, FileText, Package, AlertCircle, Clock, Database, Table2 } from 'lucide-react';

type EntityType = 'data_product' | 'data_contract' | 'table' | 'schema' | 'catalog';
type PermissionLevel = 'READ' | 'WRITE' | 'MANAGE';

interface DurationConfig {
  allowed_durations: number[] | { min: number; max: number };
  default_duration: number;
  duration_options: number[];
}

export interface RequestAccessWithDurationDialogProps {
  isOpen: boolean;
  onOpenChange: (open: boolean) => void;
  entityType: EntityType;
  entityId: string;
  entityName?: string;
  onSuccess?: () => void;
}

const ENTITY_TYPE_LABELS: Record<EntityType, string> = {
  data_product: 'Data Product',
  data_contract: 'Data Contract',
  table: 'Table',
  schema: 'Schema',
  catalog: 'Catalog',
};

const ENTITY_TYPE_ICONS: Record<EntityType, React.ReactNode> = {
  data_product: <Package className="h-5 w-5 text-primary" />,
  data_contract: <FileText className="h-5 w-5 text-primary" />,
  table: <Table2 className="h-5 w-5 text-primary" />,
  schema: <Database className="h-5 w-5 text-primary" />,
  catalog: <Database className="h-5 w-5 text-primary" />,
};

const PERMISSION_LABELS: Record<PermissionLevel, string> = {
  READ: 'Read Only',
  WRITE: 'Read & Write',
  MANAGE: 'Full Access (Manage)',
};

const DEFAULT_DURATION_OPTIONS = [30, 60, 90];

export default function RequestAccessWithDurationDialog({
  isOpen,
  onOpenChange,
  entityType,
  entityId,
  entityName,
  onSuccess,
}: RequestAccessWithDurationDialogProps) {
  const { get, post } = useApi();
  const { toast } = useToast();
  const refreshNotifications = useNotificationsStore((state) => state.refreshNotifications);
  
  const [reason, setReason] = useState('');
  const [duration, setDuration] = useState<number>(30);
  const [permissionLevel, setPermissionLevel] = useState<PermissionLevel>('READ');
  const [durationOptions, setDurationOptions] = useState<number[]>(DEFAULT_DURATION_OPTIONS);
  const [submitting, setSubmitting] = useState(false);
  const [loadingConfig, setLoadingConfig] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Fetch duration configuration when dialog opens
  useEffect(() => {
    if (isOpen) {
      fetchDurationConfig();
    }
  }, [isOpen, entityType]);

  const fetchDurationConfig = async () => {
    setLoadingConfig(true);
    try {
      const response = await get<DurationConfig>(`/api/access-grants/config/${entityType}`);
      if (response.data) {
        const options = response.data.duration_options || DEFAULT_DURATION_OPTIONS;
        setDurationOptions(options);
        setDuration(response.data.default_duration || options[0] || 30);
      }
    } catch (err) {
      console.warn('Failed to fetch duration config, using defaults:', err);
      setDurationOptions(DEFAULT_DURATION_OPTIONS);
      setDuration(30);
    } finally {
      setLoadingConfig(false);
    }
  };

  const handleSubmit = async () => {
    // Validate reason
    if (!reason.trim()) {
      setError('Please provide a reason for requesting access');
      return;
    }

    if (reason.trim().length < 10) {
      setError('Please provide a more detailed reason (at least 10 characters)');
      return;
    }

    setError(null);
    setSubmitting(true);

    try {
      const response = await post('/api/access-grants/request', {
        entity_type: entityType,
        entity_id: entityId,
        entity_name: entityName,
        requested_duration_days: duration,
        permission_level: permissionLevel,
        reason: reason.trim(),
      });

      if (response.error) {
        throw new Error(response.error);
      }

      toast({
        title: 'Request Submitted',
        description: `Your access request for ${duration} days has been submitted. You will be notified of the decision.`
      });

      // Refresh notifications to show any new ones
      refreshNotifications();

      // Reset form and close dialog
      setReason('');
      setDuration(durationOptions[0] || 30);
      setPermissionLevel('READ');
      onOpenChange(false);
      
      if (onSuccess) {
        onSuccess();
      }

    } catch (e: any) {
      const errorMessage = e.message || 'Failed to submit access request';
      setError(errorMessage);
      toast({
        title: 'Error',
        description: errorMessage,
        variant: 'destructive'
      });
    } finally {
      setSubmitting(false);
    }
  };

  const handleCancel = () => {
    setReason('');
    setError(null);
    setDuration(durationOptions[0] || 30);
    setPermissionLevel('READ');
    onOpenChange(false);
  };

  const formatDuration = (days: number): string => {
    if (days < 30) return `${days} day${days !== 1 ? 's' : ''}`;
    if (days === 30) return '1 month';
    if (days === 60) return '2 months';
    if (days === 90) return '3 months';
    if (days === 180) return '6 months';
    if (days === 365) return '1 year';
    return `${days} days`;
  };

  return (
    <Dialog open={isOpen} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-[520px]">
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2">
            {ENTITY_TYPE_ICONS[entityType] || <Package className="h-5 w-5 text-primary" />}
            Request Time-Limited Access
          </DialogTitle>
          <DialogDescription>
            Submit a request for temporary access to this {ENTITY_TYPE_LABELS[entityType]?.toLowerCase() || 'resource'}.
            Select how long you need access and provide a reason.
          </DialogDescription>
        </DialogHeader>

        <div className="space-y-4">
          {/* Entity Information */}
          <div className="p-3 bg-muted/50 rounded-lg border">
            <div className="flex items-center gap-2 text-sm text-muted-foreground">
              <span className="font-medium">{ENTITY_TYPE_LABELS[entityType] || 'Resource'}:</span>
            </div>
            <div className="text-sm font-medium mt-1">
              {entityName || entityId}
            </div>
            {entityName && entityId !== entityName && (
              <div className="text-xs text-muted-foreground mt-0.5 font-mono">{entityId}</div>
            )}
          </div>

          {/* Duration Selection */}
          <div className="space-y-2">
            <Label htmlFor="access-duration" className="text-sm font-medium flex items-center gap-2">
              <Clock className="h-4 w-4" />
              Access Duration *
            </Label>
            <Select
              value={duration.toString()}
              onValueChange={(value) => setDuration(parseInt(value, 10))}
              disabled={submitting || loadingConfig}
            >
              <SelectTrigger id="access-duration">
                <SelectValue placeholder="Select duration" />
              </SelectTrigger>
              <SelectContent>
                {durationOptions.map((d) => (
                  <SelectItem key={d} value={d.toString()}>
                    {formatDuration(d)}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
            <div className="text-xs text-muted-foreground">
              Your access will automatically expire after this period.
            </div>
          </div>

          {/* Permission Level Selection */}
          <div className="space-y-2">
            <Label htmlFor="permission-level" className="text-sm font-medium">
              Permission Level *
            </Label>
            <Select
              value={permissionLevel}
              onValueChange={(value) => setPermissionLevel(value as PermissionLevel)}
              disabled={submitting}
            >
              <SelectTrigger id="permission-level">
                <SelectValue placeholder="Select permission level" />
              </SelectTrigger>
              <SelectContent>
                {Object.entries(PERMISSION_LABELS).map(([level, label]) => (
                  <SelectItem key={level} value={level}>
                    {label}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>

          {/* Reason Field */}
          <div className="space-y-2">
            <Label htmlFor="access-reason" className="text-sm font-medium">
              Reason for Access Request *
            </Label>
            <Textarea
              id="access-reason"
              value={reason}
              onChange={(e) => setReason(e.target.value)}
              placeholder="Please explain why you need access to this resource. Include details about your intended use case, project requirements, or business justification..."
              className="min-h-[100px] resize-none"
              disabled={submitting}
            />
            <div className="text-xs text-muted-foreground">
              Minimum 10 characters required. This information will be reviewed by administrators.
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
            Cancel
          </Button>
          <Button
            onClick={handleSubmit}
            disabled={submitting || !reason.trim() || loadingConfig}
          >
            {submitting && <Loader2 className="mr-2 h-4 w-4 animate-spin" />}
            {submitting ? 'Sending Request...' : `Request ${formatDuration(duration)} Access`}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

