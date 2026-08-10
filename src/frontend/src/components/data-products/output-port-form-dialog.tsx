import { useEffect, useState } from 'react';
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogDescription, DialogFooter } from '@/components/ui/dialog';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Textarea } from '@/components/ui/textarea';
import { Switch } from '@/components/ui/switch';
import { RadioGroup, RadioGroupItem } from '@/components/ui/radio-group';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import { Badge } from '@/components/ui/badge';
import { useToast } from '@/hooks/use-toast';
import { Loader2, Plus, Info } from 'lucide-react';
import type { OutputPort, DataProduct } from '@/types/data-product';
import type { DataContractListItem } from '@/types/data-contract';
import type { DeliveryMethodRead } from '@/types/delivery-method';
import CreateContractInlineDialog from '@/components/data-contracts/create-contract-inline-dialog';

type OutputPortFormProps = {
  isOpen: boolean;
  onOpenChange: (open: boolean) => void;
  onSubmit: (port: OutputPort) => Promise<void>;
  initial?: OutputPort;
  product?: DataProduct;
};

export default function OutputPortFormDialog({ isOpen, onOpenChange, onSubmit, initial, product }: OutputPortFormProps) {
  const { toast } = useToast();
  const [isSubmitting, setIsSubmitting] = useState(false);

  const [name, setName] = useState('');
  const [version, setVersion] = useState('1.0.0');
  const [description, setDescription] = useState('');
  const [type, setType] = useState('');
  const [contractId, setContractId] = useState('');
  const [deliveryMethodId, setDeliveryMethodId] = useState('');
  const [status, setStatus] = useState('');
  const [containsPii, setContainsPii] = useState(false);
  const [autoApprove, setAutoApprove] = useState(false);
  
  // Delivery methods
  const [deliveryMethods, setDeliveryMethods] = useState<DeliveryMethodRead[]>([]);
  const [isLoadingDeliveryMethods, setIsLoadingDeliveryMethods] = useState(false);

  // Contract selection states
  const [contractSelectionMode, setContractSelectionMode] = useState<'none' | 'existing' | 'create'>('none');
  const [contracts, setContracts] = useState<DataContractListItem[]>([]);
  const [isLoadingContracts, setIsLoadingContracts] = useState(false);
  const [isCreateContractOpen, setIsCreateContractOpen] = useState(false);

  const activeStatuses = ['active', 'approved', 'certified'];

  useEffect(() => {
    if (isOpen) {
      fetchDeliveryMethods();
    }
  }, [isOpen]);

  useEffect(() => {
    if (isOpen && initial) {
      setName(initial.name || '');
      setVersion(initial.version || '1.0.0');
      setDescription(initial.description || '');
      setType(initial.type || '');
      setContractId(initial.contractId || '');
      setDeliveryMethodId(initial.deliveryMethodId || '');
      setStatus(initial.status || '');
      setContainsPii(initial.containsPii || false);
      setAutoApprove(initial.autoApprove || false);
      setContractSelectionMode(initial.contractId ? 'existing' : 'none');
    } else if (isOpen && !initial) {
      setName('');
      setVersion('1.0.0');
      setDescription('');
      setType('');
      setContractId('');
      setDeliveryMethodId('');
      setStatus('');
      setContainsPii(false);
      setAutoApprove(false);
      setContractSelectionMode('none');
    }
  }, [isOpen, initial]);

  useEffect(() => {
    if (isOpen && contractSelectionMode === 'existing' && contracts.length === 0) {
      fetchContracts();
    }
  }, [isOpen, contractSelectionMode]);

  const fetchDeliveryMethods = async () => {
    setIsLoadingDeliveryMethods(true);
    try {
      const response = await fetch('/api/delivery-methods?status=active');
      if (!response.ok) throw new Error('Failed to fetch delivery methods');
      const data: DeliveryMethodRead[] = await response.json();
      setDeliveryMethods(data);
    } catch (error: any) {
      toast({
        title: 'Warning',
        description: 'Could not load delivery methods',
        variant: 'destructive'
      });
    } finally {
      setIsLoadingDeliveryMethods(false);
    }
  };

  const fetchContracts = async () => {
    setIsLoadingContracts(true);
    try {
      const response = await fetch('/api/data-contracts');
      if (!response.ok) throw new Error('Failed to fetch contracts');
      const data: DataContractListItem[] = await response.json();
      const filteredContracts = data.filter(c => 
        activeStatuses.includes(c.status?.toLowerCase() || '')
      );
      setContracts(filteredContracts);
    } catch (error: any) {
      toast({
        title: 'Error',
        description: error?.message || 'Failed to load contracts',
        variant: 'destructive'
      });
    } finally {
      setIsLoadingContracts(false);
    }
  };

  const handleContractCreated = (newContractId: string) => {
    setContractId(newContractId);
    setIsCreateContractOpen(false);
    fetchContracts();
  };

  const handleSubmit = async () => {
    if (!name.trim()) {
      toast({ title: 'Validation Error', description: 'Name is required', variant: 'destructive' });
      return;
    }

    if (!version.trim()) {
      toast({ title: 'Validation Error', description: 'Version is required', variant: 'destructive' });
      return;
    }

    setIsSubmitting(true);
    try {
      const port: OutputPort = {
        id: initial?.id,
        name: name.trim(),
        version: version.trim(),
        description: description.trim() || undefined,
        type: type.trim() || undefined,
        contractId: contractId.trim() || undefined,
        deliveryMethodId: deliveryMethodId || undefined,
        status: status.trim() || undefined,
        containsPii,
        autoApprove,
      };

      await onSubmit(port);
      onOpenChange(false);
      toast({
        title: 'Success',
        description: initial ? 'Deliverable updated' : 'Deliverable added',
      });
    } catch (error: any) {
      toast({
        title: 'Error',
        description: error?.message || 'Failed to save deliverable',
        variant: 'destructive',
      });
    } finally {
      setIsSubmitting(false);
    }
  };

  return (
    <>
    <Dialog open={isOpen} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-3xl max-h-[90vh] overflow-y-auto">
        <DialogHeader>
          <DialogTitle>{initial ? 'Edit Deliverable' : 'Add Deliverable'}</DialogTitle>
          <DialogDescription>
            Define a deliverable for this data product. Assets can be linked after creation.
          </DialogDescription>
        </DialogHeader>

        <div className="space-y-4 py-4">
          {/* Required Fields */}
          <div className="space-y-4">
            <div className="space-y-2">
              <Label htmlFor="name">
                Name <span className="text-destructive">*</span>
              </Label>
              <Input
                id="name"
                value={name}
                onChange={(e) => setName(e.target.value)}
                placeholder="e.g., Daily Churn Rate"
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
          </div>

          {/* Delivery Method */}
          <div className="border-t pt-4">
            <div className="space-y-2">
              <Label htmlFor="deliveryMethod">Delivery Method</Label>
              {isLoadingDeliveryMethods ? (
                <div className="flex items-center gap-2 p-2">
                  <Loader2 className="h-4 w-4 animate-spin" />
                  <span className="text-sm text-muted-foreground">Loading...</span>
                </div>
              ) : (
                <Select value={deliveryMethodId} onValueChange={setDeliveryMethodId}>
                  <SelectTrigger>
                    <SelectValue placeholder="Select delivery method..." />
                  </SelectTrigger>
                  <SelectContent>
                    {deliveryMethods.map((dm) => (
                      <SelectItem key={dm.id} value={dm.id}>
                        <div className="flex items-center gap-2">
                          <span>{dm.name}</span>
                          {dm.category && (
                            <Badge variant="outline" className="text-xs">{dm.category}</Badge>
                          )}
                        </div>
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              )}
              <p className="text-xs text-muted-foreground">
                How this deliverable serves data to consumers (e.g., Table Access, Serving Endpoint)
              </p>
            </div>
          </div>

          {/* Optional Fields */}
          <div className="border-t pt-4">
            <h4 className="text-sm font-medium mb-3">Details</h4>

            <div className="space-y-4">
              <div className="space-y-2">
                <Label htmlFor="description">Description</Label>
                <Textarea
                  id="description"
                  value={description}
                  onChange={(e) => setDescription(e.target.value)}
                  placeholder="Describe what this deliverable provides"
                  rows={2}
                />
              </div>

              <div className="space-y-2">
                <Label htmlFor="type">Type</Label>
                <Input
                  id="type"
                  value={type}
                  onChange={(e) => setType(e.target.value)}
                  placeholder="e.g., table, api, stream"
                />
              </div>

              <div className="space-y-2">
                <Label htmlFor="status">Status</Label>
                <Input
                  id="status"
                  value={status}
                  onChange={(e) => setStatus(e.target.value)}
                  placeholder="e.g., active, draft"
                />
              </div>

              <div className="space-y-3">
                <Label>Contract Assignment</Label>
                <RadioGroup value={contractSelectionMode} onValueChange={(value: 'none' | 'existing' | 'create') => {
                  setContractSelectionMode(value);
                  if (value === 'none') setContractId('');
                }}>
                  <div className="flex items-center space-x-2">
                    <RadioGroupItem value="none" id="no-contract" />
                    <Label htmlFor="no-contract">No Contract</Label>
                  </div>
                  <div className="flex items-center space-x-2">
                    <RadioGroupItem value="existing" id="existing-contract" />
                    <Label htmlFor="existing-contract">Select Existing Contract</Label>
                  </div>
                  <div className="flex items-center space-x-2">
                    <RadioGroupItem value="create" id="create-contract" />
                    <Label htmlFor="create-contract">Create New Contract</Label>
                  </div>
                </RadioGroup>

                {contractSelectionMode === 'existing' && (
                  <div className="ml-6 space-y-2">
                    {isLoadingContracts ? (
                      <div className="flex items-center justify-center p-4">
                        <Loader2 className="h-4 w-4 animate-spin" />
                      </div>
                    ) : (
                      <>
                        <Select value={contractId} onValueChange={setContractId}>
                          <SelectTrigger>
                            <SelectValue placeholder="Choose a contract..." />
                          </SelectTrigger>
                          <SelectContent>
                            {contracts.length === 0 ? (
                              <div className="p-2 text-sm text-muted-foreground text-center">
                                No active/approved contracts available
                              </div>
                            ) : (
                              contracts.map((contract) => (
                                <SelectItem key={contract.id} value={contract.id}>
                                  <div className="flex items-center gap-2">
                                    <span>{contract.name}</span>
                                    <Badge variant="secondary" className="text-xs">v{contract.version}</Badge>
                                  </div>
                                </SelectItem>
                              ))
                            )}
                          </SelectContent>
                        </Select>
                        <p className="text-xs text-muted-foreground">
                          Only showing active/approved/certified contracts
                        </p>
                      </>
                    )}
                  </div>
                )}

                {contractSelectionMode === 'create' && (
                  <div className="ml-6">
                    <Button
                      type="button"
                      variant="outline"
                      onClick={() => setIsCreateContractOpen(true)}
                      className="w-full"
                    >
                      <Plus className="mr-2 h-4 w-4" />
                      Create New Contract
                    </Button>
                    {contractId && (
                      <div className="mt-2 p-2 bg-muted rounded text-sm">
                        Contract created: <span className="font-mono text-xs">{contractId}</span>
                      </div>
                    )}
                  </div>
                )}
              </div>
            </div>
          </div>

          {/* Flags */}
          <div className="border-t pt-4">
            <h4 className="text-sm font-medium mb-3">Access & Privacy</h4>

            <div className="space-y-4">
              <div className="flex items-center justify-between space-y-0 rounded-lg border p-4">
                <div className="space-y-0.5">
                  <Label htmlFor="containsPii" className="text-base">
                    Contains PII
                  </Label>
                  <p className="text-sm text-muted-foreground">
                    Does this deliverable contain personally identifiable information?
                  </p>
                </div>
                <Switch
                  id="containsPii"
                  checked={containsPii}
                  onCheckedChange={setContainsPii}
                />
              </div>

              <div className="flex items-center justify-between space-y-0 rounded-lg border p-4">
                <div className="space-y-0.5">
                  <Label htmlFor="autoApprove" className="text-base">
                    Auto Approve
                  </Label>
                  <p className="text-sm text-muted-foreground">
                    Automatically approve access requests for this deliverable?
                  </p>
                </div>
                <Switch
                  id="autoApprove"
                  checked={autoApprove}
                  onCheckedChange={setAutoApprove}
                />
              </div>
            </div>
          </div>

          {/* Info note */}
          <div className="rounded-lg bg-muted/50 p-4 flex gap-2">
            <Info className="h-4 w-4 mt-0.5 text-muted-foreground shrink-0" />
            <p className="text-sm text-muted-foreground">
              After creating this deliverable, you can link assets (tables, views, datasets, etc.) to it from the detail page.
            </p>
          </div>
        </div>

        <DialogFooter>
          <Button variant="outline" onClick={() => onOpenChange(false)} disabled={isSubmitting}>
            Cancel
          </Button>
          <Button onClick={handleSubmit} disabled={isSubmitting}>
            {isSubmitting ? 'Saving...' : initial ? 'Save Changes' : 'Add Deliverable'}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>

    <CreateContractInlineDialog
      isOpen={isCreateContractOpen}
      onOpenChange={setIsCreateContractOpen}
      onSuccess={handleContractCreated}
      prefillData={{
        domainIds: product?.domain_ids,
        primaryDomainId: product?.primary_domain_id,
        tenant: product?.tenant,
        owner_team_id: product?.owner_team_id
      }}
    />
  </>
  );
}
