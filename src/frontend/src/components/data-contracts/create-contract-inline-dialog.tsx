import { useEffect, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogDescription, DialogFooter } from '@/components/ui/dialog';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import { useToast } from '@/hooks/use-toast';
import DomainMultiSelector from '@/components/ui/domain-multi-selector';
import { Loader2 } from 'lucide-react';

type PrefillData = {
  domain?: string;
  domainId?: string;
  domainIds?: string[];
  primaryDomainId?: string | null;
  tenant?: string;
  owner_team_id?: string;
};

type CreateContractInlineDialogProps = {
  isOpen: boolean;
  onOpenChange: (open: boolean) => void;
  onSuccess: (contractId: string) => void;
  prefillData?: PrefillData;
};

export default function CreateContractInlineDialog({
  isOpen,
  onOpenChange,
  onSuccess,
  prefillData
}: CreateContractInlineDialogProps) {
  const { t } = useTranslation(['data-contracts', 'common']);
  const { toast } = useToast();
  const [isSubmitting, setIsSubmitting] = useState(false);

  const [name, setName] = useState('');
  const [version, setVersion] = useState('1.0.0');
  const [status, setStatus] = useState('draft');
  const [ownerTeamId, setOwnerTeamId] = useState('');
  const [domainIds, setDomainIds] = useState<string[]>([]);
  const [primaryDomainId, setPrimaryDomainId] = useState<string | null>(null);
  const [tenant, setTenant] = useState('');

  useEffect(() => {
    if (isOpen) {
      // Reset or prefill fields when dialog opens
      setName('');
      setVersion('1.0.0');
      setStatus('draft');
      setOwnerTeamId(prefillData?.owner_team_id || '');
      setDomainIds(prefillData?.domainIds || (prefillData?.domainId ? [prefillData.domainId] : []));
      setPrimaryDomainId(prefillData?.primaryDomainId ?? prefillData?.domainId ?? null);
      setTenant(prefillData?.tenant || '');
    }
  }, [isOpen, prefillData]);

  const handleSubmit = async () => {
    if (!name.trim()) {
      toast({
        title: t('data-contracts:form.validationErrorTitle', 'Validation Error'),
        description: t('data-contracts:form.nameRequired', 'Contract name is required'),
        variant: 'destructive'
      });
      return;
    }

    if (!version.trim()) {
      toast({
        title: t('data-contracts:form.validationErrorTitle', 'Validation Error'),
        description: t('data-contracts:form.versionRequired', 'Version is required'),
        variant: 'destructive'
      });
      return;
    }

    setIsSubmitting(true);
    try {
      const payload: any = {
        name: name.trim(),
        version: version.trim(),
        status: status,
        kind: 'DataContract',
        apiVersion: '3.0.2'
      };

      // Add optional fields if provided
      if (ownerTeamId.trim()) payload.owner_team_id = ownerTeamId.trim();
      if (domainIds.length > 0) {
        payload.domainIds = domainIds;
        payload.primaryDomainId = primaryDomainId;
      }
      if (tenant.trim()) payload.tenant = tenant.trim();

      const response = await fetch('/api/data-contracts', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload)
      });

      if (!response.ok) {
        const errorText = await response.text();
        throw new Error(errorText || t('data-contracts:createInline.createError', 'Failed to create contract'));
      }

      const createdContract = await response.json();
      
      toast({
        title: t('data-contracts:createInline.createdTitle', 'Contract Created'),
        description: t('data-contracts:createInline.createdSuccess', 'Contract "{{name}}" (v{{version}}) created successfully', { name, version })
      });

      onSuccess(createdContract.id);
      onOpenChange(false);
    } catch (error: any) {
      toast({
        title: t('data-contracts:messages.error', 'Error'),
        description: error?.message || t('data-contracts:createInline.createError', 'Failed to create contract'),
        variant: 'destructive'
      });
    } finally {
      setIsSubmitting(false);
    }
  };

  return (
    <Dialog open={isOpen} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-2xl">
        <DialogHeader>
          <DialogTitle>{t('data-contracts:createInline.title', 'Create New Contract')}</DialogTitle>
          <DialogDescription>
            {t('data-contracts:createInline.description', 'Create a minimal data contract. You can add schemas and quality rules later.')}
          </DialogDescription>
        </DialogHeader>

        <div className="space-y-4 py-4">
          <div className="space-y-2">
            <Label htmlFor="name">
              {t('data-contracts:createInline.nameLabel', 'Contract Name')} <span className="text-destructive">*</span>
            </Label>
            <Input
              id="name"
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder={t('data-contracts:createInline.namePlaceholder', 'e.g., Customer Analytics Contract')}
              autoFocus
            />
          </div>

          <div className="space-y-2">
            <Label htmlFor="version">
              {t('data-contracts:form.version', 'Version')} <span className="text-destructive">*</span>
            </Label>
            <Input
              id="version"
              value={version}
              onChange={(e) => setVersion(e.target.value)}
              placeholder="1.0.0"
            />
          </div>

          <div className="space-y-2">
            <Label htmlFor="status">{t('data-contracts:form.status', 'Status')}</Label>
            <Select value={status} onValueChange={setStatus}>
              <SelectTrigger id="status">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="draft">{t('data-contracts:status.draft', 'Draft')}</SelectItem>
                <SelectItem value="proposed">{t('data-contracts:status.proposed', 'Proposed')}</SelectItem>
                <SelectItem value="under_review">{t('data-contracts:status.under_review', 'Under Review')}</SelectItem>
                <SelectItem value="active">{t('data-contracts:status.active', 'Active')}</SelectItem>
                <SelectItem value="approved">{t('data-contracts:status.approved', 'Approved')}</SelectItem>
                <SelectItem value="certified">{t('data-contracts:status.certified', 'Certified')}</SelectItem>
              </SelectContent>
            </Select>
          </div>

          <div className="space-y-2">
            <Label htmlFor="domain">{t('data-contracts:form.domains', 'Domains')}</Label>
            <DomainMultiSelector
              value={domainIds}
              primaryDomainId={primaryDomainId}
              onChange={(nextIds, nextPrimary) => {
                setDomainIds(nextIds);
                setPrimaryDomainId(nextPrimary);
              }}
              placeholder={t('data-contracts:form.selectDomainsOptional', 'Select domains (optional)')}
            />
          </div>

          <div className="space-y-2">
            <Label htmlFor="tenant">{t('data-contracts:form.tenant', 'Tenant')}</Label>
            <Input
              id="tenant"
              value={tenant}
              onChange={(e) => setTenant(e.target.value)}
              placeholder={t('data-contracts:createInline.tenantPlaceholder', 'e.g., production')}
            />
          </div>

          <div className="space-y-2">
            <Label htmlFor="ownerTeamId">{t('data-contracts:createInline.ownerTeamIdLabel', 'Owner Team ID')}</Label>
            <Input
              id="ownerTeamId"
              value={ownerTeamId}
              onChange={(e) => setOwnerTeamId(e.target.value)}
              placeholder={t('data-contracts:createInline.ownerTeamIdPlaceholder', 'UUID of owning team')}
            />
            <p className="text-xs text-muted-foreground">
              {t('data-contracts:createInline.ownerTeamIdHint', 'Optional: Inherited from product if available')}
            </p>
          </div>
        </div>

        <DialogFooter>
          <Button 
            variant="outline" 
            onClick={() => onOpenChange(false)} 
            disabled={isSubmitting}
          >
            {t('common:actions.cancel', 'Cancel')}
          </Button>
          <Button onClick={handleSubmit} disabled={isSubmitting}>
            {isSubmitting ? (
              <>
                <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                {t('data-contracts:createInline.creating', 'Creating...')}
              </>
            ) : (
              t('data-contracts:form.createContract', 'Create Contract')
            )}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

