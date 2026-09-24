import { useState, useEffect } from 'react';
import { useTranslation } from 'react-i18next';
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogFooter, DialogDescription } from '@/components/ui/dialog';
import { Button } from '@/components/ui/button';
import { Textarea } from '@/components/ui/textarea';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Alert, AlertDescription } from '@/components/ui/alert';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import { useToast } from '@/hooks/use-toast';
import { useApi } from '@/hooks/use-api';
import { useNotificationsStore } from '@/stores/notifications-store';
import { Loader2, AlertCircle, FileText, Eye, Database, ShieldCheck, Info, RefreshCw, Rocket } from 'lucide-react';
import type { DeploymentPolicy } from '@/types/deployment-policy';
import AccessRequestFields from '@/components/access/access-request-fields';
import {
  getAllowedTransitions,
  getStatusConfig,
  getRecommendedAction,
} from '@/lib/odcs-lifecycle';

type RequestType = 'access' | 'review' | 'deploy' | 'publish' | 'certify' | 'status_change';

interface CertificationLevelOption {
  id: string;
  level_order: number;
  name: string;
  color: string | null;
}

interface RequestContractActionDialogProps {
  isOpen: boolean;
  onOpenChange: (open: boolean) => void;
  contractId: string;
  contractName?: string;
  contractStatus?: string;
  onSuccess?: () => void;
  /** If true, status changes are applied directly without approval workflow */
  canDirectStatusChange?: boolean;
}

export default function RequestContractActionDialog({
  isOpen,
  onOpenChange,
  contractId,
  contractName,
  contractStatus,
  onSuccess,
  canDirectStatusChange = false
}: RequestContractActionDialogProps) {
  const { t } = useTranslation(['data-contracts', 'common']);
  const { post, get } = useApi();
  const { toast } = useToast();
  const refreshNotifications = useNotificationsStore((state) => state.refreshNotifications);
  
  const [requestType, setRequestType] = useState<RequestType>('deploy');
  const [message, setMessage] = useState('');
  const [justification, setJustification] = useState('');
  const [catalog, setCatalog] = useState('');
  const [schema, setSchema] = useState('');
  const [targetStatus, setTargetStatus] = useState('');
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [selectedDuration, setSelectedDuration] = useState<number>(30);
  
  // Deployment policy state
  const [deploymentPolicy, setDeploymentPolicy] = useState<DeploymentPolicy | null>(null);
  const [loadingPolicy, setLoadingPolicy] = useState(false);
  const [policyError, setPolicyError] = useState<string | null>(null);
  const [certificationLevel, setCertificationLevel] = useState<number | null>(null);
  const [certificationLevels, setCertificationLevels] = useState<CertificationLevelOption[]>([]);
  const [publicationScope, setPublicationScope] = useState('organization');

  useEffect(() => {
    get<CertificationLevelOption[]>('/api/certification-levels').then(({ data }) => {
      if (Array.isArray(data)) setCertificationLevels(data);
    });
  }, [get]);

  useEffect(() => {
    if (isOpen) {
      setCertificationLevel(null);
      setPublicationScope('organization');
    }
  }, [isOpen]);

  const getRequestTypeConfig = (type: RequestType) => {
    switch (type) {
      case 'access':
        return {
          icon: <Eye className="h-5 w-5" />,
          title: t('data-contracts:requests.access.title', 'Request Access to Contract'),
          description: t('data-contracts:requests.access.description', 'Request permission to view and use this data contract.'),
          enabled: true,
          endpoint: '/api/access-grants/request',
        };
      case 'review':
        return {
          icon: <FileText className="h-5 w-5" />,
          title: t('data-contracts:requests.review.title', 'Request Data Steward Review'),
          description: t('data-contracts:requests.review.description', 'Submit this contract for review by a data steward (transitions to PROPOSED status).'),
          enabled: contractStatus?.toLowerCase() === 'draft',
          endpoint: `/api/data-contracts/${contractId}/request-review`,
        };
      case 'deploy':
        return {
          icon: <Database className="h-5 w-5" />,
          title: t('data-contracts:requests.deploy.title', 'Request Deploy to Unity Catalog'),
          description: t('data-contracts:requests.deploy.description', 'Request approval to deploy this contract to Unity Catalog.'),
          enabled: true,
          endpoint: `/api/data-contracts/${contractId}/request-deploy`,
        };
      case 'publish':
        return {
          icon: <Rocket className="h-5 w-5" />,
          title: t('data-contracts:requests.publish.title', 'Request Publish'),
          description: t('data-contracts:requests.publish.description', 'Request to publish this contract with a defined visibility scope.'),
          enabled:
            contractStatus?.toLowerCase() === 'approved' ||
            contractStatus?.toLowerCase() === 'active',
          endpoint: `/api/data-contracts/${contractId}/request-publish`,
        };
      case 'certify':
        return {
          icon: <ShieldCheck className="h-5 w-5" />,
          title: t('data-contracts:requests.certify.title', 'Request Certification'),
          description: t('data-contracts:requests.certify.description', 'Request that this contract be certified at a specific level.'),
          enabled: true,
          endpoint: `/api/data-contracts/${contractId}/request-certify`,
        };
      case 'status_change':
        const allowedTransitions = contractStatus ? getAllowedTransitions(contractStatus) : [];
        return {
          icon: <RefreshCw className="h-5 w-5" />,
          title: canDirectStatusChange
            ? t('data-contracts:requests.statusChange.changeTitle', 'Change Status')
            : t('data-contracts:requests.statusChange.requestTitle', 'Request Status Change'),
          description: canDirectStatusChange
            ? t('data-contracts:requests.statusChange.changeDescription', 'Directly change the lifecycle status of this contract.')
            : t('data-contracts:requests.statusChange.requestDescription', 'Request approval to change the lifecycle status of this contract.'),
          enabled: allowedTransitions.length > 0,
          endpoint: canDirectStatusChange 
            ? `/api/data-contracts/${contractId}/change-status`
            : `/api/data-contracts/${contractId}/request-status-change`,
        };
    }
  };

  const validateForm = (): boolean => {
    setError(null);
    
    if (requestType === 'access') {
      if (!message.trim()) {
        setError(t('data-contracts:requests.validation.accessReasonRequired', 'Please provide a reason for requesting access'));
        return false;
      }
      if (message.trim().length < 10) {
        setError(t('data-contracts:requests.validation.accessReasonTooShort', 'Please provide a more detailed reason (at least 10 characters)'));
        return false;
      }
    }
    
    if (requestType === 'review') {
      // Message is optional for review
    }
    
    if (requestType === 'deploy') {
      // Catalog and schema are optional
    }
    
    if (requestType === 'status_change') {
      if (!targetStatus) {
        setError(t('data-contracts:requests.validation.targetStatusRequired', 'Please select a target status'));
        return false;
      }
      // Justification is only required for approval requests, not direct changes
      if (!canDirectStatusChange) {
        if (!justification.trim()) {
          setError(t('data-contracts:requests.validation.justificationRequired', 'Please provide a justification for the status change'));
          return false;
        }
        if (justification.trim().length < 20) {
          setError(t('data-contracts:requests.validation.justificationTooShort', 'Please provide a more detailed justification (at least 20 characters)'));
          return false;
        }
      }
    }

    if (requestType === 'certify') {
      if (!certificationLevel) {
        setError(t('data-contracts:requests.validation.certLevelRequired', 'Please select a certification level'));
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
      setError(t('data-contracts:requests.cannotRequest', "Cannot request {{type}} for a contract with status '{{status}}'", { type: requestType, status: contractStatus }));
      return;
    }

    setError(null);
    setSubmitting(true);

    try {
      let payload: any;
      
      if (requestType === 'access') {
        // Use access grants endpoint
        payload = {
          entity_type: 'data_contract',
          entity_id: contractId,
          reason: message.trim(),
          requested_permission_level: 'READ',
          requested_duration_days: selectedDuration,
        };
      } else if (requestType === 'review') {
        payload = {
          message: message.trim() || undefined,
        };
      } else if (requestType === 'deploy') {
        payload = {
          catalog: catalog.trim() || undefined,
          schema: schema.trim() || undefined,
          message: message.trim() || undefined,
        };
      } else if (requestType === 'publish') {
        payload = {
          scope: publicationScope,
          justification: justification.trim() || undefined,
        };
      } else if (requestType === 'certify') {
        if (!certificationLevel) {
          setError(t('data-contracts:requests.validation.certLevelRequired', 'Please select a certification level'));
          setSubmitting(false);
          return;
        }
        payload = {
          certification_level: certificationLevel,
          message: message.trim() || undefined,
        };
      } else if (requestType === 'status_change') {
        if (canDirectStatusChange) {
          // Direct status change - different payload format
          payload = {
            new_status: targetStatus,
          };
        } else {
          // Request for approval
          payload = {
            target_status: targetStatus,
            justification: justification.trim(),
            current_status: contractStatus,
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
          title: t('data-contracts:requests.toast.statusChangedTitle', 'Status Changed'),
          description: t('data-contracts:requests.toast.statusChangedDescription', 'Contract status changed from "{{from}}" to "{{to}}".', { from: contractStatus, to: targetStatus })
        });
      } else {
        toast({
          title: t('data-contracts:requests.toast.submittedTitle', 'Request Submitted'),
          description: t('data-contracts:requests.toast.submittedDescription', 'Your {{type}} request has been submitted and you will be notified of the decision.', { type: requestType })
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
      setCatalog('');
      setSchema('');
      setTargetStatus('');
      setCertificationLevel(null);
      setPublicationScope('organization');
      onOpenChange(false);

    } catch (e: any) {
      setError(e.message || t('data-contracts:requests.errors.submitFailed', 'Failed to submit request'));
      toast({
        title: t('common:toast.error', 'Error'),
        description: e.message || t('data-contracts:requests.errors.submitFailed', 'Failed to submit request'),
        variant: 'destructive'
      });
    } finally {
      setSubmitting(false);
    }
  };

  const handleCancel = () => {
    setMessage('');
    setJustification('');
    setCatalog('');
    setSchema('');
    setTargetStatus('');
    setError(null);
    onOpenChange(false);
  };

  // Fetch deployment policy when deploy option is selected
  useEffect(() => {
    const fetchDeploymentPolicy = async () => {
      if (requestType === 'deploy' && isOpen) {
        setLoadingPolicy(true);
        setPolicyError(null);
        
        try {
          const response = await get('/api/user/deployment-policy');
          
          if (response.error) {
            throw new Error(response.error);
          }
          
          const policy = response.data as DeploymentPolicy;
          setDeploymentPolicy(policy);
          
          // Pre-populate with default catalog/schema if available and fields are empty
          if (policy.default_catalog && !catalog) {
            setCatalog(policy.default_catalog);
          }
          if (policy.default_schema && !schema) {
            setSchema(policy.default_schema);
          }
        } catch (e: any) {
          setPolicyError(e.message || t('data-contracts:requests.errors.loadPolicyFailed', 'Failed to load deployment policy'));
          console.error('Error fetching deployment policy:', e);
        } finally {
          setLoadingPolicy(false);
        }
      }
    };
    
    fetchDeploymentPolicy();
  }, [requestType, isOpen, get]);
  
  const currentConfig = getRequestTypeConfig(requestType);

  return (
    <Dialog open={isOpen} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-[600px]">
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2">
            {t('data-contracts:requests.dialogTitle', 'Request Action')}
          </DialogTitle>
          <DialogDescription>
            {t('data-contracts:requests.dialogDescription', 'Select the type of request you want to submit for this data contract.')}
          </DialogDescription>
        </DialogHeader>

        <div className="space-y-4">
          {/* Contract Information */}
          <div className="p-3 bg-muted/50 rounded-lg border">
            <div className="flex items-center gap-2 text-sm text-muted-foreground">
              <span className="font-medium">{t('data-contracts:requests.contractLabel', 'Contract:')}</span>
              <span className="font-mono">{contractId}</span>
            </div>
            {contractName && (
              <div className="text-sm font-medium mt-1">{contractName}</div>
            )}
            {contractStatus && (
              <div className="text-xs text-muted-foreground mt-1">
                {t('data-contracts:requests.statusLabel', 'Status:')} <span className="uppercase">{contractStatus}</span>
              </div>
            )}
          </div>

          {/* Request Type Selection */}
          <div className="space-y-3">
            <Label className="text-sm font-medium">{t('data-contracts:requests.requestTypeLabel', 'Request Type *')}</Label>
            <Select value={requestType} onValueChange={(value) => setRequestType(value as RequestType)}>
              <SelectTrigger>
                <SelectValue>
                  <div className="flex items-center gap-2">
                    {currentConfig.icon}
                    <span>{currentConfig.title}</span>
                  </div>
                </SelectValue>
              </SelectTrigger>
              <SelectContent>
                {(
                  [
                    'status_change',
                    'deploy',
                    'review',
                    'publish',
                    'certify',
                    'access',
                  ] as RequestType[]
                ).map((type) => {
                  const config = getRequestTypeConfig(type);
                  return (
                    <SelectItem key={type} value={type} disabled={!config.enabled}>
                      <div className="flex items-center gap-2">
                        {config.icon}
                        <span>{config.title}</span>
                      </div>
                    </SelectItem>
                  );
                })}
              </SelectContent>
            </Select>
            <div className="p-3 bg-muted/50 rounded-lg border text-sm">
              <p className="text-muted-foreground">{currentConfig.description}</p>
              {!currentConfig.enabled && (
                <p className="text-destructive mt-2 text-xs">
                  {t('data-contracts:requests.notAvailableForStatus', "Not available for status '{{status}}'", { status: contractStatus })}
                </p>
              )}
            </div>
          </div>

          {/* Dynamic Form Fields - Access Request using shared component */}
          {requestType === 'access' && (
            <AccessRequestFields
              entityType="data_contract"
              message={message}
              onMessageChange={setMessage}
              selectedDuration={selectedDuration}
              onDurationChange={setSelectedDuration}
              disabled={submitting}
            />
          )}

          {requestType === 'review' && (
            <div className="space-y-2">
              <Label htmlFor="review-message" className="text-sm font-medium">
                {t('data-contracts:requests.messageOptionalLabel', 'Message (Optional)')}
              </Label>
              <Textarea
                id="review-message"
                value={message}
                onChange={(e) => setMessage(e.target.value)}
                placeholder={t('data-contracts:requests.review.messagePlaceholder', 'Add any notes for the data steward reviewing this contract...')}
                className="min-h-[80px] resize-none"
                disabled={submitting}
              />
            </div>
          )}

          {requestType === 'publish' && (
            <div className="space-y-4">
              <div className="space-y-2">
                <Label htmlFor="contract-pub-scope" className="text-sm font-medium">
                  {t('data-contracts:requests.publish.scopeLabel', 'Publication Scope *')}
                </Label>
                <Select value={publicationScope} onValueChange={setPublicationScope} disabled={submitting}>
                  <SelectTrigger id="contract-pub-scope">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="domain">{t('data-contracts:requests.publish.scopeDomain', 'Domain')}</SelectItem>
                    <SelectItem value="organization">{t('data-contracts:requests.publish.scopeOrganization', 'Organization')}</SelectItem>
                    <SelectItem value="external">{t('data-contracts:requests.publish.scopeExternal', 'External')}</SelectItem>
                  </SelectContent>
                </Select>
              </div>
              <div className="space-y-2">
                <Label htmlFor="contract-publish-justification" className="text-sm font-medium">
                  {t('data-contracts:requests.publish.justificationLabel', 'Justification (optional)')}
                </Label>
                <Textarea
                  id="contract-publish-justification"
                  value={justification}
                  onChange={(e) => setJustification(e.target.value)}
                  placeholder={t('data-contracts:requests.publish.justificationPlaceholder', 'Why should this contract be published?')}
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
                <Label htmlFor="contract-cert-level" className="text-sm font-medium">
                  {t('data-contracts:requests.certify.levelLabel', 'Certification Level *')}
                </Label>
                <Select
                  value={certificationLevel !== null ? certificationLevel.toString() : ''}
                  onValueChange={(v) => setCertificationLevel(parseInt(v, 10))}
                  disabled={submitting}
                >
                  <SelectTrigger id="contract-cert-level">
                    <SelectValue placeholder={t('data-contracts:requests.certify.levelPlaceholder', 'Select certification level')} />
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
                <Label htmlFor="contract-cert-message" className="text-sm font-medium">
                  {t('data-contracts:requests.certify.messageLabel', 'Message (optional)')}
                </Label>
                <Textarea
                  id="contract-cert-message"
                  value={message}
                  onChange={(e) => setMessage(e.target.value)}
                  placeholder={t('data-contracts:requests.certify.messagePlaceholder', 'Why should this contract be certified?')}
                  className="min-h-[80px] resize-none"
                  rows={3}
                  disabled={submitting}
                />
              </div>
            </div>
          )}

          {requestType === 'deploy' && (
            <div className="space-y-3">
              {/* Loading Policy Indicator */}
              {loadingPolicy && (
                <Alert>
                  <Loader2 className="h-4 w-4 animate-spin" />
                  <AlertDescription>{t('data-contracts:requests.deploy.loadingPolicy', 'Loading deployment policy...')}</AlertDescription>
                </Alert>
              )}
              
              {/* Policy Error */}
              {policyError && (
                <Alert variant="destructive">
                  <AlertCircle className="h-4 w-4" />
                  <AlertDescription>{policyError}</AlertDescription>
                </Alert>
              )}
              
              {/* Policy Info Banner */}
              {deploymentPolicy && !loadingPolicy && (
                <Alert className="bg-blue-50 border-blue-200 dark:bg-blue-950 dark:border-blue-800">
                  <ShieldCheck className="h-4 w-4 text-blue-600 dark:text-blue-400" />
                  <AlertDescription className="text-sm text-blue-800 dark:text-blue-200">
                    <strong>{t('data-contracts:requests.deploy.policyLabel', 'Deployment Policy:')}</strong> {t('data-contracts:requests.deploy.youCanDeployTo', 'You can deploy to')}{' '}
                    {deploymentPolicy.allowed_catalogs.length === 0
                      ? t('data-contracts:requests.deploy.noCatalogsContactAdmin', 'no catalogs (contact admin)')
                      : deploymentPolicy.allowed_catalogs.length === 1
                      ? `${deploymentPolicy.allowed_catalogs[0]}`
                      : t('data-contracts:requests.deploy.allowedCatalogsCount', '{{count}} allowed catalogs', { count: deploymentPolicy.allowed_catalogs.length })}
                    {deploymentPolicy.require_approval && t('data-contracts:requests.deploy.requiresApprovalSuffix', ' (requires approval)')}
                  </AlertDescription>
                </Alert>
              )}
              
              <div className="grid grid-cols-2 gap-3">
                {/* Catalog Dropdown or Input */}
                <div className="space-y-2">
                  <Label htmlFor="deploy-catalog" className="text-sm font-medium">
                    {t('data-contracts:requests.deploy.targetCatalogLabel', 'Target Catalog (Optional)')}
                  </Label>
                  {deploymentPolicy && deploymentPolicy.allowed_catalogs.length > 0 && deploymentPolicy.allowed_catalogs.includes('*') ? (
                    // Wildcard - allow any catalog via text input
                    <Input
                      id="deploy-catalog"
                      value={catalog}
                      onChange={(e) => setCatalog(e.target.value)}
                      placeholder={deploymentPolicy.default_catalog || t('data-contracts:requests.deploy.enterCatalogPlaceholder', 'Enter catalog name...')}
                      disabled={submitting || loadingPolicy}
                    />
                  ) : deploymentPolicy && deploymentPolicy.allowed_catalogs.length > 0 ? (
                    // Specific catalogs - show dropdown
                    <Select
                      value={catalog}
                      onValueChange={setCatalog}
                      disabled={submitting || loadingPolicy}
                    >
                      <SelectTrigger id="deploy-catalog">
                        <SelectValue placeholder={t('data-contracts:requests.deploy.selectCatalogPlaceholder', 'Select catalog...')} />
                      </SelectTrigger>
                      <SelectContent>
                        {deploymentPolicy.allowed_catalogs.map((cat) => (
                          <SelectItem key={cat} value={cat}>
                            {cat}
                          </SelectItem>
                        ))}
                      </SelectContent>
                    </Select>
                  ) : (
                    // No catalogs available
                    <Select disabled>
                      <SelectTrigger>
                        <SelectValue placeholder={t('data-contracts:requests.deploy.noCatalogsAvailable', 'No catalogs available')} />
                      </SelectTrigger>
                    </Select>
                  )}
                  {deploymentPolicy?.default_catalog && catalog === deploymentPolicy.default_catalog && (
                    <div className="text-xs text-muted-foreground flex items-center gap-1">
                      <Info className="h-3 w-3" />
                      {t('data-contracts:requests.deploy.defaultCatalogForRole', 'Default catalog for your role')}
                    </div>
                  )}
                  {deploymentPolicy?.allowed_catalogs.includes('*') && (
                    <div className="text-xs text-muted-foreground flex items-center gap-1">
                      <Info className="h-3 w-3" />
                      {t('data-contracts:requests.deploy.anyCatalog', 'You can deploy to any catalog')}
                    </div>
                  )}
                </div>
                
                {/* Schema Dropdown or Input */}
                <div className="space-y-2">
                  <Label htmlFor="deploy-schema" className="text-sm font-medium">
                    {t('data-contracts:requests.deploy.targetSchemaLabel', 'Target Schema (Optional)')}
                  </Label>
                  {deploymentPolicy && deploymentPolicy.allowed_schemas.length > 0 && deploymentPolicy.allowed_schemas.includes('*') ? (
                    // Wildcard - allow any schema via text input
                    <Input
                      id="deploy-schema"
                      value={schema}
                      onChange={(e) => setSchema(e.target.value)}
                      placeholder={deploymentPolicy.default_schema || t('data-contracts:requests.deploy.enterSchemaPlaceholder', 'Enter schema name...')}
                      disabled={submitting || loadingPolicy}
                    />
                  ) : deploymentPolicy && deploymentPolicy.allowed_schemas.length > 0 ? (
                    // Specific schemas - show dropdown
                    <Select
                      value={schema}
                      onValueChange={setSchema}
                      disabled={submitting || loadingPolicy}
                    >
                      <SelectTrigger id="deploy-schema">
                        <SelectValue placeholder={t('data-contracts:requests.deploy.selectSchemaPlaceholder', 'Select schema...')} />
                      </SelectTrigger>
                      <SelectContent>
                        {deploymentPolicy.allowed_schemas.map((sch) => (
                          <SelectItem key={sch} value={sch}>
                            {sch}
                          </SelectItem>
                        ))}
                      </SelectContent>
                    </Select>
                  ) : (
                    // No specific schemas - allow text input for any schema
                    <Input
                      id="deploy-schema"
                      value={schema}
                      onChange={(e) => setSchema(e.target.value)}
                      placeholder={deploymentPolicy?.default_schema || t('data-contracts:requests.deploy.enterSchemaPlaceholder', 'Enter schema name...')}
                      disabled={submitting || loadingPolicy}
                    />
                  )}
                  {deploymentPolicy?.default_schema && schema === deploymentPolicy.default_schema && (
                    <div className="text-xs text-muted-foreground flex items-center gap-1">
                      <Info className="h-3 w-3" />
                      {t('data-contracts:requests.deploy.defaultSchemaForRole', 'Default schema for your role')}
                    </div>
                  )}
                  {deploymentPolicy && (deploymentPolicy.allowed_schemas.length === 0 || deploymentPolicy.allowed_schemas.includes('*')) && (
                    <div className="text-xs text-muted-foreground flex items-center gap-1">
                      <Info className="h-3 w-3" />
                      {t('data-contracts:requests.deploy.anySchema', 'You can deploy to any schema')}
                    </div>
                  )}
                </div>
              </div>
              
              <div className="space-y-2">
                <Label htmlFor="deploy-message" className="text-sm font-medium">
                  {t('data-contracts:requests.messageOptionalLabel', 'Message (Optional)')}
                </Label>
                <Textarea
                  id="deploy-message"
                  value={message}
                  onChange={(e) => setMessage(e.target.value)}
                  placeholder={t('data-contracts:requests.deploy.messagePlaceholder', 'Add any deployment notes or requirements...')}
                  className="min-h-[60px] resize-none"
                  disabled={submitting}
                />
              </div>
            </div>
          )}

          {requestType === 'status_change' && (
            <div className="space-y-4">
              {/* Current Status */}
              {contractStatus && (
                <div className="rounded-lg border bg-muted/50 p-3">
                  <div className="flex items-center gap-2 mb-1">
                    <Label className="text-sm font-semibold">{t('data-contracts:requests.statusChange.currentStatusLabel', 'Current Status:')}</Label>
                    <span className="text-lg">{getStatusConfig(contractStatus).icon}</span>
                    <span className="font-medium">{getStatusConfig(contractStatus).label}</span>
                  </div>
                  <p className="text-xs text-muted-foreground">{getStatusConfig(contractStatus).description}</p>
                </div>
              )}

              {/* Recommended Action */}
              {contractStatus && getRecommendedAction(contractStatus) && (
                <Alert>
                  <Info className="h-4 w-4" />
                  <AlertDescription className="text-sm">
                    <strong>{t('data-contracts:requests.statusChange.recommendedLabel', 'Recommended:')}</strong> {getRecommendedAction(contractStatus)}
                  </AlertDescription>
                </Alert>
              )}

              {/* Target Status Selection */}
              {contractStatus && getAllowedTransitions(contractStatus).length > 0 ? (
                <div className="space-y-2">
                  <Label className="text-sm font-medium">{t('data-contracts:requests.statusChange.selectTargetLabel', 'Select Target Status *')}</Label>
                  <Select value={targetStatus} onValueChange={setTargetStatus}>
                    <SelectTrigger>
                      <SelectValue placeholder={t('data-contracts:requests.statusChange.chooseTargetPlaceholder', 'Choose target status...')}>
                        {targetStatus && (
                          <div className="flex items-center gap-2">
                            <span className="text-lg">{getStatusConfig(targetStatus).icon}</span>
                            <span>{getStatusConfig(targetStatus).label}</span>
                          </div>
                        )}
                      </SelectValue>
                    </SelectTrigger>
                    <SelectContent>
                      {getAllowedTransitions(contractStatus).map((status) => {
                        const config = getStatusConfig(status);
                        return (
                          <SelectItem key={status} value={status}>
                            <div className="flex items-center gap-2">
                              <span className="text-lg">{config.icon}</span>
                              <span>{config.label}</span>
                            </div>
                          </SelectItem>
                        );
                      })}
                    </SelectContent>
                  </Select>
                  {targetStatus && (
                    <div className="p-3 bg-muted/50 rounded-lg border text-sm">
                      <p className="text-muted-foreground">{getStatusConfig(targetStatus).description}</p>
                    </div>
                  )}
                </div>
              ) : (
                <Alert variant="destructive">
                  <AlertCircle className="h-4 w-4" />
                  <AlertDescription>
                    <strong>{t('data-contracts:requests.statusChange.terminalStateLabel', 'Terminal State:')}</strong> {t('data-contracts:requests.statusChange.noTransitions', 'No transitions available from {{status}} status.', { status: contractStatus ? getStatusConfig(contractStatus).label : 'current' })}
                  </AlertDescription>
                </Alert>
              )}

              {/* Justification - required for approval requests, optional for direct changes */}
              {!canDirectStatusChange && (
                <div className="space-y-2">
                  <Label htmlFor="status-justification" className="text-sm font-medium">
                    {t('data-contracts:requests.statusChange.justificationLabel', 'Justification *')}
                  </Label>
                  <Textarea
                    id="status-justification"
                    value={justification}
                    onChange={(e) => setJustification(e.target.value)}
                    placeholder={t('data-contracts:requests.statusChange.justificationPlaceholder', 'Explain why this status change is needed and any relevant context...')}
                    className="min-h-[100px] resize-none"
                    disabled={submitting}
                  />
                  <div className="text-xs text-muted-foreground">
                    {t('data-contracts:requests.statusChange.justificationHint', 'Minimum 20 characters required. This will be reviewed by an admin.')}
                  </div>
                </div>
              )}

              {/* Lifecycle Diagram */}
              <div className="rounded-lg border p-3 bg-muted/20">
                <Label className="text-xs font-semibold mb-2 block">{t('data-contracts:requests.statusChange.lifecycleFlowLabel', 'ODCS Lifecycle Flow:')}</Label>
                <div className="flex items-center gap-1 text-xs font-mono flex-wrap">
                  <span className={contractStatus?.toLowerCase() === 'draft' ? 'font-bold text-primary' : ''}>draft</span>
                  <span>→</span>
                  <span className={contractStatus?.toLowerCase() === 'proposed' ? 'font-bold text-primary' : ''}>proposed</span>
                  <span>→</span>
                  <span className={contractStatus?.toLowerCase() === 'under_review' ? 'font-bold text-primary' : ''}>under_review</span>
                  <span>→</span>
                  <span className={contractStatus?.toLowerCase() === 'approved' ? 'font-bold text-primary' : ''}>approved</span>
                  <span>→</span>
                  <span className={contractStatus?.toLowerCase() === 'active' ? 'font-bold text-primary' : ''}>active</span>
                  <span>→</span>
                  <span className={contractStatus?.toLowerCase() === 'certified' ? 'font-bold text-primary' : ''}>certified</span>
                  <span>→</span>
                  <span className={contractStatus?.toLowerCase() === 'deprecated' ? 'font-bold text-primary' : ''}>deprecated</span>
                  <span>→</span>
                  <span className={contractStatus?.toLowerCase() === 'retired' ? 'font-bold text-primary' : ''}>retired</span>
                </div>
                <p className="text-xs text-muted-foreground mt-2">
                  {t('data-contracts:requests.statusChange.lifecycleNote', 'Current status is highlighted. Emergency deprecation allowed from any status.')}
                </p>
              </div>
            </div>
          )}

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
            {t('common:actions.cancel', 'Cancel')}
          </Button>
          <Button
            onClick={handleSubmit}
            disabled={submitting || !currentConfig.enabled}
          >
            {submitting && <Loader2 className="mr-2 h-4 w-4 animate-spin" />}
            {submitting
              ? (requestType === 'status_change' && canDirectStatusChange ? t('data-contracts:requests.changingStatus', 'Changing Status...') : t('data-contracts:requests.sendingRequest', 'Sending Request...'))
              : (requestType === 'status_change' && canDirectStatusChange ? t('data-contracts:requests.statusChange.changeTitle', 'Change Status') : t('data-contracts:requests.sendRequest', 'Send Request'))}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

