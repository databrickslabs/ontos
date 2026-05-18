import { useState, useEffect } from 'react';
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogFooter, DialogDescription } from '@/components/ui/dialog';
import { Button } from '@/components/ui/button';
import { Textarea } from '@/components/ui/textarea';
import { Label } from '@/components/ui/label';
import { Alert, AlertDescription } from '@/components/ui/alert';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import { useToast } from '@/hooks/use-toast';
import { useApi } from '@/hooks/use-api';
import { useApprovalWizardTrigger, type AppActionTriggerType } from '@/hooks/use-approval-wizard-trigger';
import { useNotificationsStore } from '@/stores/notifications-store';
import { Loader2, AlertCircle, FileText, Eye, Rocket, RefreshCw, ShieldCheck, Info } from 'lucide-react';
import AccessRequestFields from '@/components/access/access-request-fields';
import ApprovalWizardDialog from '@/components/workflows/approval-wizard-dialog';

type RequestType = 'access' | 'review' | 'publish' | 'certify' | 'status_change';

/**
 * Map request type → app-action trigger type for approval-wizard lookup.
 *
 * Closes the wiring gap from PR #318: Subscribe was the only path that invoked
 * the wizard, even though all six ``for_request_*`` triggers existed in the
 * backend. Each request type below opens the same ApprovalWizardDialog when a
 * workflow is configured, falling through to today's direct-submit otherwise.
 */
const REQUEST_TYPE_TO_TRIGGER: Record<RequestType, AppActionTriggerType> = {
  access: 'for_request_access',
  review: 'for_request_review',
  publish: 'for_request_publish',
  certify: 'for_request_certify',
  status_change: 'for_request_status_change',
};

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
  const { lookupWorkflowId } = useApprovalWizardTrigger();
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

  // Approval wizard launch state.
  // When a `for_request_*` workflow is configured, we open the wizard before
  // the original direct-submit fires; on wizard completion the collected
  // wizard fields are merged into the submit body. When no workflow is
  // configured, this dialog falls through to today's direct-submit flow.
  const [wizardOpen, setWizardOpen] = useState(false);
  const [wizardWorkflowId, setWizardWorkflowId] = useState<string | null>(null);
  // Stashed submit context — captured at the moment Submit is clicked so the
  // wizard's onComplete can replay the API call with merged fields.
  const [pendingSubmit, setPendingSubmit] = useState<{
    endpoint: string;
    payload: Record<string, unknown>;
    requestType: RequestType;
  } | null>(null);

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
      setWizardWorkflowId(null);
    }
  }, [isOpen, defaultRequestType]);

  /**
   * Resolve the configured approval workflow for the current request type at
   * dialog-open time (and on request-type changes). When a wizard is
   * configured, the dialog hides its own form fields so the user isn't asked
   * for the same input twice (e.g. typing a reason in both the dialog and the
   * wizard's user_action step). When none is configured — or lookup fails —
   * we leave wizardWorkflowId=null and the legacy direct-submit form renders.
   *
   * Direct status changes (admin path) skip the lookup entirely: that flow
   * always bypasses the wizard regardless of configuration.
   */
  useEffect(() => {
    if (!isOpen) return;
    if (requestType === 'status_change' && canDirectStatusChange) {
      setWizardWorkflowId(null);
      return;
    }
    let cancelled = false;
    const triggerType = REQUEST_TYPE_TO_TRIGGER[requestType];
    (async () => {
      try {
        const id = await lookupWorkflowId(triggerType);
        if (!cancelled) setWizardWorkflowId(id);
      } catch {
        if (!cancelled) setWizardWorkflowId(null);
      }
    })();
    return () => { cancelled = true; };
  }, [isOpen, requestType, canDirectStatusChange, lookupWorkflowId]);

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

  /**
   * Build the request body for the chosen request type.
   * Returns ``null`` when validation fails (callers have already surfaced an error).
   */
  const buildPayload = (type: RequestType): Record<string, unknown> | null => {
    if (type === 'access') {
      return {
        entity_type: 'data_product',
        entity_id: productId,
        reason: message.trim(),
        requested_permission_level: 'READ',
        requested_duration_days: selectedDuration,
      };
    } else if (type === 'review') {
      return {
        message: message.trim() || undefined,
      };
    } else if (type === 'publish') {
      return {
        scope: publicationScope,
        justification: justification.trim() || undefined,
      };
    } else if (type === 'certify') {
      if (!certificationLevel) {
        setError('Please select a certification level');
        return null;
      }
      return {
        certification_level: certificationLevel,
        message: message.trim() || undefined,
      };
    } else if (type === 'status_change') {
      if (canDirectStatusChange) {
        return { new_status: targetStatus };
      }
      return {
        target_status: targetStatus,
        justification: justification.trim(),
        current_status: productStatus,
      };
    }
    return null;
  };

  /**
   * Execute the actual API submit. Called either directly from handleSubmit
   * (when no wizard is configured) or from the wizard's onComplete (with
   * merged wizard fields).
   */
  const executeSubmit = async (
    endpoint: string,
    payload: Record<string, unknown>,
    type: RequestType,
  ) => {
    setError(null);
    setSubmitting(true);
    try {
      const response = await post(endpoint, payload);
      if (response.error) {
        throw new Error(response.error);
      }
      // Different success messages for direct changes vs requests
      if (type === 'status_change' && canDirectStatusChange) {
        toast({
          title: 'Status Changed',
          description: `Product status changed from "${productStatus}" to "${targetStatus}".`,
        });
      } else {
        toast({
          title: 'Request Submitted',
          description: `Your ${type} request has been submitted and you will be notified of the decision.`,
        });
      }
      refreshNotifications();
      if (onSuccess) onSuccess();
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
        variant: 'destructive',
      });
    } finally {
      setSubmitting(false);
    }
  };

  const handleSubmit = async () => {
    const config = getRequestTypeConfig(requestType);
    if (!config.enabled) {
      setError(`Cannot request ${requestType} for a product with status '${productStatus}'`);
      return;
    }

    // When a wizard is configured for this request type, the wizard owns all
    // user input — skip dialog-side field validation so the dialog doesn't
    // reject empty fields it isn't going to collect anyway. The base payload
    // built here is merged with wizard-collected fields on completion.
    const wizardActive = !!wizardWorkflowId
      && !(requestType === 'status_change' && canDirectStatusChange);
    if (!wizardActive && !validateForm()) {
      return;
    }

    const payload = buildPayload(requestType);
    if (!payload) return;

    // Direct-status-change skips the wizard (it's an admin operation, not a request).
    if (requestType === 'status_change' && canDirectStatusChange) {
      await executeSubmit(config.endpoint, payload, requestType);
      return;
    }

    if (wizardActive) {
      // Stash the submit context so onComplete can replay it with merged fields.
      setPendingSubmit({ endpoint: config.endpoint, payload, requestType });
      setWizardOpen(true);
    } else {
      await executeSubmit(config.endpoint, payload, requestType);
    }
  };

  /**
   * Map of wizard-field-id → top-level payload key, per request type.
   *
   * When the wizard's ``user_action`` step collects a field whose id matches a
   * known top-level field on the backend's request model, hoist it onto the
   * payload root before submit. Without this, empty top-level fields fail
   * Pydantic validation (e.g. ``AccessGrantRequestCreate.reason`` has
   * ``min_length=10`` and the dialog form is hidden when a wizard is
   * configured, so its top-level ``reason`` ships as ``''``).
   *
   * The hoist only fires when the top-level field is currently empty/falsy —
   * we never overwrite a value the dialog already collected. Wizard fields
   * still live in ``wizard_data`` so Process workflows can reference them via
   * ``${entity.<field_id>}``; the hoist is purely additive.
   */
  const WIZARD_FIELD_HOIST: Record<RequestType, Record<string, string>> = {
    access: {
      reason: 'reason',
      // Wizard authors commonly name the duration field one of these; map
      // both onto the canonical ``requested_duration_days`` integer field.
      expiry_days: 'requested_duration_days',
      requested_duration_days: 'requested_duration_days',
    },
    review: { message: 'message' },
    publish: {
      justification: 'justification',
      scope: 'scope',
    },
    certify: {
      message: 'message',
      certification_level: 'certification_level',
    },
    status_change: {
      justification: 'justification',
      target_status: 'target_status',
    },
  };

  /** Numeric fields on the BE request body that need string→int coercion. */
  const NUMERIC_TOP_LEVEL_FIELDS = new Set<string>([
    'requested_duration_days',
    'certification_level',
  ]);

  /**
   * Hoist wizard-collected fields onto the top-level payload when the field id
   * matches a known top-level field for the request type. Returns a new object;
   * never mutates inputs. Empty strings on the wizard side are skipped so they
   * don't clobber a non-empty dialog-side value.
   */
  const hoistWizardFieldsToPayload = (
    payload: Record<string, unknown>,
    wizardFields: Record<string, unknown>,
    type: RequestType,
  ): Record<string, unknown> => {
    const map = WIZARD_FIELD_HOIST[type] ?? {};
    const out: Record<string, unknown> = { ...payload };
    for (const [wizardKey, topLevelKey] of Object.entries(map)) {
      const wizardValue = wizardFields[wizardKey];
      if (wizardValue === undefined || wizardValue === null) continue;
      if (typeof wizardValue === 'string' && wizardValue.trim() === '') continue;
      const existing = out[topLevelKey];
      const existingIsEmpty =
        existing === undefined ||
        existing === null ||
        (typeof existing === 'string' && existing.trim() === '');
      // For numeric duration we override only when default 30 wasn't user-typed
      // but rather the literal initial state — heuristic: hoist whenever wizard
      // gave a value AND existing is empty OR field is the default-only path.
      // Simpler rule: don't overwrite a non-empty existing value.
      if (!existingIsEmpty) continue;
      if (NUMERIC_TOP_LEVEL_FIELDS.has(topLevelKey) && typeof wizardValue === 'string') {
        const parsed = parseInt(wizardValue, 10);
        if (Number.isFinite(parsed)) {
          out[topLevelKey] = parsed;
        }
        // Non-numeric string for a numeric field — silently drop (BE would 422).
        continue;
      }
      out[topLevelKey] = wizardValue;
    }
    return out;
  };

  const handleWizardComplete = async (
    _agreementId: string | null,
    _pdfStoragePath: string | null,
    wizardFields?: Record<string, unknown>,
  ) => {
    if (!pendingSubmit) return;
    const fields = wizardFields ?? {};
    // Step 1: hoist matching wizard fields onto the top-level payload so BE
    // request-model validation (e.g. ``reason`` min_length on access requests)
    // doesn't reject submissions that route their input through the wizard.
    const hoisted = hoistWizardFieldsToPayload(
      pendingSubmit.payload,
      fields,
      pendingSubmit.requestType,
    );
    const merged = {
      ...hoisted,
      // Step 2: keep the full wizard map under ``wizard_data`` so the BE can
      // forward it into ``entity_data`` for downstream Process workflows
      // without colliding with first-class request fields (reason, duration).
      wizard_data: fields,
    };
    setWizardOpen(false);
    setWizardWorkflowId(null);
    setPendingSubmit(null);
    await executeSubmit(pendingSubmit.endpoint, merged, pendingSubmit.requestType);
  };

  const allowedTransitions = productStatus ? getAllowedTransitions(productStatus) : [];
  const config = getRequestTypeConfig(requestType);
  // Direct status changes always render their form (admin path bypasses the wizard).
  const isDirectStatusChange = requestType === 'status_change' && canDirectStatusChange;
  // When true, the wizard owns user input — hide per-request-type form fields
  // and skip dialog-side validation. See the lookup effect above.
  const wizardActive = !!wizardWorkflowId && !isDirectStatusChange;

  return (
    <>
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

          {/* Wizard-configured notice — replaces the per-request-type form
              when a `for_request_*` workflow is wired up, since the wizard
              collects all input itself (preventing the duplicate-prompt UX
              that surfaced during Path B testing). */}
          {wizardActive && (
            <Alert>
              <Info className="h-4 w-4" />
              <AlertDescription>
                A multi-step wizard is configured for this request. Click
                {' '}<strong>Continue</strong>{' '}to begin.
              </AlertDescription>
            </Alert>
          )}

          {/* Status Change Fields — shown for direct status change always, and
              for status-change requests only when no wizard is configured. */}
          {requestType === 'status_change' && (isDirectStatusChange || !wizardActive) && (
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
          {requestType === 'access' && !wizardActive && (
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
          {requestType === 'review' && !wizardActive && (
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
          {requestType === 'publish' && !wizardActive && (
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

          {requestType === 'certify' && !wizardActive && (
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
                {isDirectStatusChange ? 'Changing Status...' : (wizardActive ? 'Opening...' : 'Sending Request...')}
              </>
            ) : (
              isDirectStatusChange ? 'Change Status' : (wizardActive ? 'Continue' : 'Send Request')
            )}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
    {/* Approval wizard — opens when a `for_request_*` workflow is configured
        for the chosen request type. On completion, replays the submit with
        wizard-collected fields merged into the body. */}
    {wizardWorkflowId && (
      <ApprovalWizardDialog
        isOpen={wizardOpen}
        onOpenChange={(open) => {
          setWizardOpen(open);
          if (!open && pendingSubmit) {
            // User dismissed wizard mid-flow — drop the pending submit so the
            // dialog stays open for the user to retry/cancel. We keep
            // wizardWorkflowId so the "wizard configured" notice and Continue
            // button remain (the wizard config didn't change just because the
            // user dismissed the modal).
            setPendingSubmit(null);
          }
        }}
        entityType="data_product"
        entityId={productId}
        entityName={productName}
        preselectedWorkflowId={wizardWorkflowId}
        autoStartWithPreselected
        onComplete={handleWizardComplete}
      />
    )}
    </>
  );
}
