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
import { Loader2, AlertCircle, FileText, Eye, Rocket, RefreshCw, ShieldCheck } from 'lucide-react';
import AccessRequestFields from '@/components/access/access-request-fields';

type RequestType = 'access' | 'review' | 'publish' | 'certify' | 'status_change';

interface CertificationLevelOption {
  id: string;
  level_order: number;
  name: string;
  color: string | null;
}

interface RequestProductActionDialogProps {
  isOpen: boolean;
  onOpenChange: (open: boolean) => void;
  productId: string;
  productName?: string;
  productStatus?: string;
  onSuccess?: () => void;
  /** If true, status changes are applied directly without approval workflow */
  canDirectStatusChange?: boolean;
  /** Initial request type to select when the dialog opens. Defaults to 'access',
   * since access requests are the most common entry point. Call sites that open
   * the dialog from a status-change-specific affordance should pass 'status_change'. */
  defaultRequestType?: RequestType;
}

// ODPS lifecycle transitions
const ALLOWED_TRANSITIONS: Record<string, { target: string; label: string }[]> = {
  'draft': [
    { target: 'sandbox', label: 'Move to Sandbox' },
    { target: 'proposed', label: 'Submit for Review' },
  ],
  'sandbox': [
    { target: 'draft', label: 'Return to Draft' },
    { target: 'proposed', label: 'Submit for Review' },
  ],
  'proposed': [
    { target: 'draft', label: 'Return to Draft' },
    { target: 'under_review', label: 'Start Review' },
  ],
  'under_review': [
    { target: 'approved', label: 'Approve' },
    { target: 'draft', label: 'Reject (Return to Draft)' },
  ],
  'approved': [
    { target: 'active', label: 'Publish/Activate' },
    { target: 'draft', label: 'Return to Draft' },
  ],
  'active': [
    { target: 'deprecated', label: 'Deprecate' },
  ],
  'deprecated': [
    { target: 'retired', label: 'Retire' },
    { target: 'active', label: 'Reactivate' },
  ],
  'retired': [],
};

function getAllowedTransitions(status: string): { target: string; label: string }[] {
  return ALLOWED_TRANSITIONS[status.toLowerCase()] || [];
}

export default function RequestProductActionDialog({
  isOpen,
  onOpenChange,
  productId,
  productName,
  productStatus,
  onSuccess,
  canDirectStatusChange = false,
  defaultRequestType = 'access'
}: RequestProductActionDialogProps) {
  const { post, get } = useApi();
  const { toast } = useToast();
  const refreshNotifications = useNotificationsStore((state) => state.refreshNotifications);

  const [requestType, setRequestType] = useState<RequestType>(defaultRequestType);
  const [message, setMessage] = useState('');
  const [justification, setJustification] = useState('');
  const [targetStatus, setTargetStatus] = useState('');
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [selectedDuration, setSelectedDuration] = useState<number>(30);
  const [certificationLevel, setCertificationLevel] = useState<number | null>(null);
  const [certificationLevels, setCertificationLevels] = useState<CertificationLevelOption[]>([]);
  const [publicationScope, setPublicationScope] = useState('organization');

  useEffect(() => {
    get<CertificationLevelOption[]>('/api/certification-levels').then(({ data }) => {
      if (Array.isArray(data)) setCertificationLevels(data);
    });
  }, [get]);

  // Reset form when dialog opens/closes
  useEffect(() => {
    if (isOpen) {
      setRequestType(defaultRequestType);
      setMessage('');
      setJustification('');
      setTargetStatus('');
      setError(null);
      setSelectedDuration(30);
      setCertificationLevel(null);
      setPublicationScope('organization');
    }
  }, [isOpen, defaultRequestType]);

  const getRequestTypeConfig = (type: RequestType) => {
    switch (type) {
      case 'access':
        return {
          icon: <Eye className="h-5 w-5" />,
          title: 'Request Access to Product',
          description: 'Request permission to view and use this data product.',
          enabled: true,
          endpoint: '/api/access-grants/request',
        };
      case 'review':
        return {
          icon: <FileText className="h-5 w-5" />,
          title: 'Request Data Steward Review',
          description: 'Submit this product for review by a data steward (transitions to PROPOSED status).',
          enabled: productStatus?.toLowerCase() === 'draft' || productStatus?.toLowerCase() === 'sandbox',
          endpoint: `/api/data-products/${productId}/request-review`,
        };
      case 'publish':
        return {
          icon: <Rocket className="h-5 w-5" />,
          title: 'Request Publish to Marketplace',
          description: 'Request to publish this approved product to the organization-wide marketplace.',
          enabled: productStatus?.toLowerCase() === 'approved' || productStatus?.toLowerCase() === 'active',
          endpoint: `/api/data-products/${productId}/request-publish`,
        };
      case 'certify':
        return {
          icon: <ShieldCheck className="h-5 w-5" />,
          title: 'Request Certification',
          description: 'Request that this product be certified at a specific level.',
          enabled: true,
          endpoint: `/api/data-products/${productId}/request-certify`,
        };
      case 'status_change':
        const allowedTransitions = productStatus ? getAllowedTransitions(productStatus) : [];
        return {
          icon: <RefreshCw className="h-5 w-5" />,
          title: canDirectStatusChange ? 'Change Status' : 'Request Status Change',
          description: canDirectStatusChange 
            ? 'Directly change the lifecycle status of this product.'
            : 'Request approval to change the lifecycle status of this product.',
          enabled: allowedTransitions.length > 0,
          endpoint: canDirectStatusChange 
            ? `/api/data-products/${productId}/change-status`
            : `/api/data-products/${productId}/request-status-change`,
        };
    }
  };

  const validateForm = (): boolean => {
    setError(null);
    
    if (requestType === 'access') {
      if (!message.trim()) {
        setError('Please provide a reason for requesting access');
        return false;
      }
      if (message.trim().length < 10) {
        setError('Please provide a more detailed reason (at least 10 characters)');
        return false;
      }
    }
    
    if (requestType === 'status_change') {
      if (!targetStatus) {
        setError('Please select a target status');
        return false;
      }
      // Justification is only required for approval requests, not direct changes
      if (!canDirectStatusChange) {
        if (!justification.trim()) {
          setError('Please provide a justification for the status change');
          return false;
        }
        if (justification.trim().length < 20) {
          setError('Please provide a more detailed justification (at least 20 characters)');
          return false;
        }
      }
    }

    if (requestType === 'certify') {
      if (!certificationLevel) {
        setError('Please select a certification level');
        return false;
      }
    }
    
    return true;
  };

  const handleSubmit = async () => {
    if (!validateForm()) {
      return;
    }

    const config = getRequestTypeConfig(requestType);
    if (!config.enabled) {
      setError(`Cannot request ${requestType} for a product with status '${productStatus}'`);
      return;
    }

    setError(null);
    setSubmitting(true);

    try {
      let payload: any;
      
      if (requestType === 'access') {
        payload = {
          entity_type: 'data_product',
          entity_id: productId,
          reason: message.trim(),
          requested_permission_level: 'READ',
          requested_duration_days: selectedDuration,
        };
      } else if (requestType === 'review') {
        payload = {
          message: message.trim() || undefined,
        };
      } else if (requestType === 'publish') {
        payload = {
          scope: publicationScope,
          justification: justification.trim() || undefined,
        };
      } else if (requestType === 'certify') {
        if (!certificationLevel) {
          setError('Please select a certification level');
          setSubmitting(false);
          return;
        }
        payload = {
          certification_level: certificationLevel,
          message: message.trim() || undefined,
        };
      } else if (requestType === 'status_change') {
        if (canDirectStatusChange) {
          payload = {
            new_status: targetStatus,
          };
        } else {
          payload = {
            target_status: targetStatus,
            justification: justification.trim(),
            current_status: productStatus,
          };
        }
      }

      const response = await post(config.endpoint, payload);

      if (response.error) {
        throw new Error(response.error);
      }

      // Different success messages for direct changes vs requests
      if (requestType === 'status_change' && canDirectStatusChange) {
        toast({
          title: 'Status Changed',
          description: `Product status changed from "${productStatus}" to "${targetStatus}".`
        });
      } else {
        toast({
          title: 'Request Submitted',
          description: `Your ${requestType} request has been submitted and you will be notified of the decision.`
        });
      }

      // Refresh notifications
      refreshNotifications();

      // Call success callback
      if (onSuccess) {
        onSuccess();
      }

      // Reset form and close dialog
      setMessage('');
      setJustification('');
      setTargetStatus('');
      setCertificationLevel(null);
      setPublicationScope('organization');
      onOpenChange(false);

    } catch (e: any) {
      setError(e.message || 'Failed to submit request');
      toast({
        title: 'Error',
        description: e.message || 'Failed to submit request',
        variant: 'destructive'
      });
    } finally {
      setSubmitting(false);
    }
  };

  const allowedTransitions = productStatus ? getAllowedTransitions(productStatus) : [];
  const config = getRequestTypeConfig(requestType);

  return (
    <Dialog open={isOpen} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-lg">
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2">
            {config.icon}
            {config.title}
          </DialogTitle>
          <DialogDescription>
            {productName && <span className="font-medium">{productName}</span>}
            {productStatus && <span className="text-muted-foreground ml-2">({productStatus})</span>}
          </DialogDescription>
        </DialogHeader>

        <div className="space-y-4 py-4">
          {/* Request Type Selector */}
          <div className="space-y-2">
            <Label htmlFor="request-type">Request Type</Label>
            <Select value={requestType} onValueChange={(value) => setRequestType(value as RequestType)}>
              <SelectTrigger id="request-type">
                <SelectValue placeholder="Select request type" />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="status_change">
                  <div className="flex items-center gap-2">
                    <RefreshCw className="h-4 w-4" />
                    {canDirectStatusChange ? 'Change Status' : 'Request Status Change'}
                  </div>
                </SelectItem>
                <SelectItem value="review" disabled={!getRequestTypeConfig('review').enabled}>
                  <div className="flex items-center gap-2">
                    <FileText className="h-4 w-4" />
                    Request Review
                  </div>
                </SelectItem>
                <SelectItem value="publish" disabled={!getRequestTypeConfig('publish').enabled}>
                  <div className="flex items-center gap-2">
                    <Rocket className="h-4 w-4" />
                    Request Publish
                  </div>
                </SelectItem>
                <SelectItem value="certify" disabled={!getRequestTypeConfig('certify').enabled}>
                  <div className="flex items-center gap-2">
                    <ShieldCheck className="h-4 w-4" />
                    Request Certification
                  </div>
                </SelectItem>
                <SelectItem value="access">
                  <div className="flex items-center gap-2">
                    <Eye className="h-4 w-4" />
                    Request Access
                  </div>
                </SelectItem>
              </SelectContent>
            </Select>
            <p className="text-xs text-muted-foreground">{config.description}</p>
          </div>

          {/* Status Change Fields */}
          {requestType === 'status_change' && (
            <div className="space-y-4">
              <div className="space-y-2">
                <Label htmlFor="target-status">Target Status *</Label>
                <Select value={targetStatus} onValueChange={setTargetStatus} disabled={submitting}>
                  <SelectTrigger id="target-status">
                    <SelectValue placeholder="Select target status" />
                  </SelectTrigger>
                  <SelectContent>
                    {allowedTransitions.map((transition) => (
                      <SelectItem key={transition.target} value={transition.target}>
                        {transition.label}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
                {allowedTransitions.length === 0 && (
                  <p className="text-xs text-muted-foreground">
                    No status transitions available from current status.
                  </p>
                )}
              </div>

              {/* Justification - only for approval requests */}
              {!canDirectStatusChange && (
                <div className="space-y-2">
                  <Label htmlFor="status-justification">Justification *</Label>
                  <Textarea
                    id="status-justification"
                    value={justification}
                    onChange={(e) => setJustification(e.target.value)}
                    placeholder="Explain why this status change is needed and any relevant context..."
                    className="min-h-[100px] resize-none"
                    disabled={submitting}
                  />
                  <div className="text-xs text-muted-foreground">
                    Minimum 20 characters required. This will be reviewed by an admin.
                  </div>
                </div>
              )}
            </div>
          )}

          {/* Access Request Fields - using shared component */}
          {requestType === 'access' && (
            <AccessRequestFields
              entityType="data_product"
              message={message}
              onMessageChange={setMessage}
              selectedDuration={selectedDuration}
              onDurationChange={setSelectedDuration}
              disabled={submitting}
            />
          )}

          {/* Review Request Message */}
          {requestType === 'review' && (
            <div className="space-y-2">
              <Label htmlFor="review-message">Message (optional)</Label>
              <Textarea
                id="review-message"
                value={message}
                onChange={(e) => setMessage(e.target.value)}
                placeholder="Add any notes for the reviewer..."
                className="min-h-[80px] resize-none"
                disabled={submitting}
              />
            </div>
          )}

          {/* Publish Request — scope + justification */}
          {requestType === 'publish' && (
            <div className="space-y-4">
              <div className="space-y-2">
                <Label htmlFor="pub-scope">Publication Scope *</Label>
                <Select value={publicationScope} onValueChange={setPublicationScope} disabled={submitting}>
                  <SelectTrigger id="pub-scope">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="domain">Domain</SelectItem>
                    <SelectItem value="organization">Organization</SelectItem>
                    <SelectItem value="external">External</SelectItem>
                  </SelectContent>
                </Select>
              </div>
              <div className="space-y-2">
                <Label htmlFor="publish-justification">Justification (optional)</Label>
                <Textarea
                  id="publish-justification"
                  value={justification}
                  onChange={(e) => setJustification(e.target.value)}
                  placeholder="Why should this product be published?"
                  className="min-h-[80px] resize-none"
                  rows={3}
                  disabled={submitting}
                />
              </div>
            </div>
          )}

          {requestType === 'certify' && (
            <div className="space-y-4">
              <div className="space-y-2">
                <Label htmlFor="cert-level">Certification Level *</Label>
                <Select
                  value={certificationLevel !== null ? certificationLevel.toString() : ''}
                  onValueChange={(v) => setCertificationLevel(parseInt(v, 10))}
                  disabled={submitting}
                >
                  <SelectTrigger id="cert-level">
                    <SelectValue placeholder="Select certification level" />
                  </SelectTrigger>
                  <SelectContent>
                    {certificationLevels.map((l) => (
                      <SelectItem key={l.id} value={l.level_order.toString()}>
                        {l.name}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>
              <div className="space-y-2">
                <Label htmlFor="cert-message">Message (optional)</Label>
                <Textarea
                  id="cert-message"
                  value={message}
                  onChange={(e) => setMessage(e.target.value)}
                  placeholder="Why should this product be certified?"
                  rows={3}
                  className="min-h-[80px] resize-none"
                  disabled={submitting}
                />
              </div>
            </div>
          )}

          {/* Error Display */}
          {error && (
            <Alert variant="destructive">
              <AlertCircle className="h-4 w-4" />
              <AlertDescription>{error}</AlertDescription>
            </Alert>
          )}
        </div>

        <DialogFooter>
          <Button variant="outline" onClick={() => onOpenChange(false)} disabled={submitting}>
            Cancel
          </Button>
          <Button onClick={handleSubmit} disabled={submitting || !config.enabled}>
            {submitting ? (
              <>
                <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                {requestType === 'status_change' && canDirectStatusChange ? 'Changing Status...' : 'Sending Request...'}
              </>
            ) : (
              requestType === 'status_change' && canDirectStatusChange ? 'Change Status' : 'Send Request'
            )}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
