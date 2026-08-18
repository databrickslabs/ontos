import { useEffect, useState } from 'react';
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
        title: 'Validation Error', 
        description: 'Contract name is required', 
        variant: 'destructive' 
      });
      return;
    }

    if (!version.trim()) {
      toast({ 
        title: 'Validation Error', 
        description: 'Version is required', 
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
        throw new Error(errorText || 'Failed to create contract');
      }

      const createdContract = await response.json();
      
      toast({
        title: 'Contract Created',
        description: `Contract "${name}" (v${version}) created successfully`
      });

      onSuccess(createdContract.id);
      onOpenChange(false);
    } catch (error: any) {
      toast({
        title: 'Error',
        description: error?.message || 'Failed to create contract',
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
          <DialogTitle>Create New Contract</DialogTitle>
          <DialogDescription>
            Create a minimal data contract. You can add schemas and quality rules later.
          </DialogDescription>
        </DialogHeader>

        <div className="space-y-4 py-4">
          <div className="space-y-2">
            <Label htmlFor="name">
              Contract Name <span className="text-destructive">*</span>
            </Label>
            <Input
              id="name"
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder="e.g., Customer Analytics Contract"
              autoFocus
            />
          </div>

          <div className="space-y-2">
            <Label htmlFor="version">
              Version <span className="text-destructive">*</span>
            </Label>
            <Input
              id="version"
              value={version}
              onChange={(e) => setVersion(e.target.value)}
              placeholder="1.0.0"
            />
          </div>

          <div className="space-y-2">
            <Label htmlFor="status">Status</Label>
            <Select value={status} onValueChange={setStatus}>
              <SelectTrigger id="status">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="draft">Draft</SelectItem>
                <SelectItem value="proposed">Proposed</SelectItem>
                <SelectItem value="under_review">Under Review</SelectItem>
                <SelectItem value="active">Active</SelectItem>
                <SelectItem value="approved">Approved</SelectItem>
                <SelectItem value="certified">Certified</SelectItem>
              </SelectContent>
            </Select>
          </div>

          <div className="space-y-2">
            <Label htmlFor="domain">Domains</Label>
            <DomainMultiSelector
              value={domainIds}
              primaryDomainId={primaryDomainId}
              onChange={(nextIds, nextPrimary) => {
                setDomainIds(nextIds);
                setPrimaryDomainId(nextPrimary);
              }}
              placeholder="Select domains (optional)"
            />
          </div>

          <div className="space-y-2">
            <Label htmlFor="tenant">Tenant</Label>
            <Input
              id="tenant"
              value={tenant}
              onChange={(e) => setTenant(e.target.value)}
              placeholder="e.g., production"
            />
          </div>

          <div className="space-y-2">
            <Label htmlFor="ownerTeamId">Owner Team ID</Label>
            <Input
              id="ownerTeamId"
              value={ownerTeamId}
              onChange={(e) => setOwnerTeamId(e.target.value)}
              placeholder="UUID of owning team"
            />
            <p className="text-xs text-muted-foreground">
              Optional: Inherited from product if available
            </p>
          </div>
        </div>

        <DialogFooter>
          <Button 
            variant="outline" 
            onClick={() => onOpenChange(false)} 
            disabled={isSubmitting}
          >
            Cancel
          </Button>
          <Button onClick={handleSubmit} disabled={isSubmitting}>
            {isSubmitting ? (
              <>
                <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                Creating...
              </>
            ) : (
              'Create Contract'
            )}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

