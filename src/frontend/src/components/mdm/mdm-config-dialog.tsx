import { useState, useEffect } from 'react';
import { useForm } from 'react-hook-form';
import { zodResolver } from '@hookform/resolvers/zod';
import * as z from 'zod';

import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Textarea } from '@/components/ui/textarea';
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select';
import { Loader2, Info } from 'lucide-react';
import { Alert, AlertDescription } from '@/components/ui/alert';

import { useApi } from '@/hooks/use-api';
import { useToast } from '@/hooks/use-toast';
import { MdmEntityType, MdmConfigCreate, MatchingRule, SurvivorshipRule, MatchRuleType, SurvivorshipStrategy } from '@/types/mdm';

interface DataContract {
  id: string;
  name: string;
  status: string;
  customProperties?: Record<string, any>;
}

const formSchema = z.object({
  name: z.string().min(1, 'Name is required'),
  description: z.string().optional(),
  entity_type: z.nativeEnum(MdmEntityType),
  master_contract_id: z.string().min(1, 'Master contract is required'),
});

type FormValues = z.infer<typeof formSchema>;

interface MdmConfigDialogProps {
  isOpen: boolean;
  onClose: () => void;
  onSuccess: () => void;
}

// Helper to parse rules from contract customProperties
function parseContractMdmRules(customProps: Record<string, any> | undefined): {
  matchingRules: MatchingRule[];
  survivorshipRules: SurvivorshipRule[];
} {
  if (!customProps) return { matchingRules: [], survivorshipRules: [] };

  let matchingRules: MatchingRule[] = [];
  let survivorshipRules: SurvivorshipRule[] = [];

  // Parse mdmMatchingRules
  let rawMatchingRules = customProps.mdmMatchingRules;
  if (typeof rawMatchingRules === 'string') {
    try { rawMatchingRules = JSON.parse(rawMatchingRules); } catch { rawMatchingRules = []; }
  }
  if (Array.isArray(rawMatchingRules)) {
    matchingRules = rawMatchingRules.map((r: any) => ({
      name: r.name || 'unnamed_rule',
      type: r.type === 'exact' ? 'deterministic' : r.type === 'fuzzy' ? 'probabilistic' : r.type,
      fields: r.fields || [],
      weight: r.weight || 1.0,
      threshold: r.threshold || 0.7,
      algorithm: r.algorithm,
    }));
  }

  // Parse mdmSurvivorshipRules
  let rawSurvivorshipRules = customProps.mdmSurvivorshipRules;
  if (typeof rawSurvivorshipRules === 'string') {
    try { rawSurvivorshipRules = JSON.parse(rawSurvivorshipRules); } catch { rawSurvivorshipRules = []; }
  }
  if (Array.isArray(rawSurvivorshipRules)) {
    survivorshipRules = rawSurvivorshipRules.map((r: any) => ({
      field: r.field || '',
      strategy: r.strategy || 'most_recent',
      priority: r.priority,
    }));
  }

  return { matchingRules, survivorshipRules };
}

export default function MdmConfigDialog({ isOpen, onClose, onSuccess }: MdmConfigDialogProps) {
  const [contracts, setContracts] = useState<DataContract[]>([]);
  const [loading, setLoading] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [loadingContract, setLoadingContract] = useState(false);
  const [matchingRules, setMatchingRules] = useState<MatchingRule[]>([]);
  const [survivorshipRules, setSurvivorshipRules] = useState<SurvivorshipRule[]>([]);
  const [rulesSource, setRulesSource] = useState<'contract' | 'default' | 'empty'>('empty');

  const { get, post } = useApi();
  const { toast } = useToast();

  const form = useForm<FormValues>({
    resolver: zodResolver(formSchema),
    defaultValues: {
      name: '',
      description: '',
      entity_type: MdmEntityType.CUSTOMER,
      master_contract_id: '',
    },
  });

  const selectedContractId = form.watch('master_contract_id');

  useEffect(() => {
    if (isOpen) {
      fetchContracts();
      form.reset();
      setMatchingRules([]);
      setSurvivorshipRules([]);
      setRulesSource('empty');
    }
  }, [isOpen]);

  // When contract is selected, fetch its customProperties for MDM rules
  useEffect(() => {
    if (selectedContractId) {
      fetchContractRules(selectedContractId);
    }
  }, [selectedContractId]);

  const fetchContracts = async () => {
    setLoading(true);
    try {
      const response = await get<DataContract[]>('/api/data-contracts');
      if (response.data) {
        // Filter to only active contracts
        const activeContracts = response.data.filter(c => c.status === 'active');
        setContracts(activeContracts);
      }
    } catch (err) {
      console.error('Error fetching contracts:', err);
    } finally {
      setLoading(false);
    }
  };

  const fetchContractRules = async (contractId: string) => {
    setLoadingContract(true);
    try {
      const response = await get<DataContract>(`/api/data-contracts/${contractId}`);
      if (response.data) {
        const { matchingRules: mr, survivorshipRules: sr } = parseContractMdmRules(response.data.customProperties);
        
        if (mr.length > 0 || sr.length > 0) {
          setMatchingRules(mr);
          setSurvivorshipRules(sr);
          setRulesSource('contract');
          toast({
            title: 'Rules Loaded',
            description: `Loaded ${mr.length} matching and ${sr.length} survivorship rules from contract.`,
          });
        } else {
          // Use sensible defaults if contract has no MDM rules
          setMatchingRules([
            { name: 'email_match', type: MatchRuleType.DETERMINISTIC, fields: ['email'], weight: 1.0, threshold: 1.0 },
            { name: 'name_fuzzy', type: MatchRuleType.PROBABILISTIC, fields: ['customer_name'], weight: 0.8, threshold: 0.8, algorithm: 'jaro_winkler' },
          ]);
          setSurvivorshipRules([
            { field: 'email', strategy: SurvivorshipStrategy.MOST_TRUSTED },
            { field: 'customer_name', strategy: SurvivorshipStrategy.MOST_RECENT },
          ]);
          setRulesSource('default');
        }
      }
    } catch (err) {
      console.error('Error fetching contract:', err);
    } finally {
      setLoadingContract(false);
    }
  };

  const onSubmit = async (values: FormValues) => {
    setSubmitting(true);
    try {
      const data: MdmConfigCreate = {
        name: values.name,
        description: values.description || undefined,
        entity_type: values.entity_type,
        master_contract_id: values.master_contract_id,
        matching_rules: matchingRules,
        survivorship_rules: survivorshipRules,
      };

      const response = await post('/api/mdm/configs', data);
      if (response.error) {
        console.error('[MDM Config] Creation failed:', response.error);
        toast({
          title: 'Error',
          description: response.error,
          variant: 'destructive',
        });
        return;
      }
      if (response.data) {
        console.log('[MDM Config] Created successfully:', response.data);
        const configData = response.data as { name?: string };
        toast({ title: 'Success', description: `MDM configuration "${configData.name}" created successfully` });
        onSuccess();
      } else {
        console.warn('[MDM Config] No data in response:', response);
        toast({
          title: 'Warning',
          description: 'Configuration may not have been created. Please refresh.',
          variant: 'destructive',
        });
      }
    } catch (err: any) {
      console.error('[MDM Config] Exception creating config:', err);
      toast({
        title: 'Error',
        description: err.message || 'Failed to create configuration',
        variant: 'destructive',
      });
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <Dialog open={isOpen} onOpenChange={onClose}>
      <DialogContent className="max-w-lg">
        <DialogHeader>
          <DialogTitle>New MDM Configuration</DialogTitle>
          <DialogDescription>
            Create a master data management configuration tied to a data contract.
          </DialogDescription>
        </DialogHeader>

        <form onSubmit={form.handleSubmit(onSubmit)} className="space-y-4">
          <div className="space-y-2">
            <Label htmlFor="name">Configuration Name</Label>
            <Input
              id="name"
              placeholder="e.g., Customer Master"
              {...form.register('name')}
            />
            {form.formState.errors.name && (
              <p className="text-sm text-destructive">{form.formState.errors.name.message}</p>
            )}
          </div>

          <div className="space-y-2">
            <Label htmlFor="description">Description</Label>
            <Textarea
              id="description"
              placeholder="Describe the purpose of this MDM configuration..."
              rows={3}
              {...form.register('description')}
            />
          </div>

          <div className="space-y-2">
            <Label htmlFor="entity_type">Entity Type</Label>
            <Select
              value={form.watch('entity_type')}
              onValueChange={(value) => form.setValue('entity_type', value as MdmEntityType)}
            >
              <SelectTrigger>
                <SelectValue placeholder="Select entity type" />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value={MdmEntityType.CUSTOMER}>Customer</SelectItem>
                <SelectItem value={MdmEntityType.PRODUCT}>Product</SelectItem>
                <SelectItem value={MdmEntityType.SUPPLIER}>Supplier</SelectItem>
                <SelectItem value={MdmEntityType.LOCATION}>Location</SelectItem>
                <SelectItem value={MdmEntityType.OTHER}>Other</SelectItem>
              </SelectContent>
            </Select>
          </div>

          <div className="space-y-2">
            <Label htmlFor="master_contract">Master Data Contract</Label>
            <Select
              value={form.watch('master_contract_id')}
              onValueChange={(value) => form.setValue('master_contract_id', value)}
              disabled={loading}
            >
              <SelectTrigger>
                {loading ? (
                  <span className="flex items-center gap-2">
                    <Loader2 className="h-4 w-4 animate-spin" />
                    Loading...
                  </span>
                ) : (
                  <SelectValue placeholder="Select master contract" />
                )}
              </SelectTrigger>
              <SelectContent>
                {contracts.map((contract) => (
                  <SelectItem key={contract.id} value={contract.id}>
                    {contract.name}
                  </SelectItem>
                ))}
                {contracts.length === 0 && !loading && (
                  <SelectItem value="_none" disabled>
                    No active contracts available
                  </SelectItem>
                )}
              </SelectContent>
            </Select>
            {form.formState.errors.master_contract_id && (
              <p className="text-sm text-destructive">
                {form.formState.errors.master_contract_id.message}
              </p>
            )}
          </div>

          {/* Rules Preview */}
          {selectedContractId && (
            <div className="space-y-2 pt-2 border-t">
              {loadingContract ? (
                <div className="flex items-center gap-2 text-sm text-muted-foreground">
                  <Loader2 className="h-4 w-4 animate-spin" />
                  Loading rules from contract...
                </div>
              ) : (
                <>
                  <Alert>
                    <Info className="h-4 w-4" />
                    <AlertDescription>
                      {rulesSource === 'contract' ? (
                        <>Loaded {matchingRules.length} matching rules and {survivorshipRules.length} survivorship rules from contract's customProperties.</>
                      ) : rulesSource === 'default' ? (
                        <>Contract has no MDM rules defined. Using sensible defaults. You can edit them after creation.</>
                      ) : null}
                    </AlertDescription>
                  </Alert>
                  
                  {matchingRules.length > 0 && (
                    <div className="text-sm space-y-1">
                      <p className="font-medium">Matching Rules:</p>
                      <ul className="list-disc list-inside text-muted-foreground pl-2">
                        {matchingRules.slice(0, 3).map((rule, i) => (
                          <li key={i}>
                            {rule.name}: {rule.fields.join(', ')} ({rule.type})
                          </li>
                        ))}
                        {matchingRules.length > 3 && (
                          <li className="text-xs">...and {matchingRules.length - 3} more</li>
                        )}
                      </ul>
                    </div>
                  )}
                </>
              )}
            </div>
          )}

          <DialogFooter>
            <Button type="button" variant="outline" onClick={onClose} disabled={submitting}>
              Cancel
            </Button>
            <Button type="submit" disabled={submitting}>
              {submitting && <Loader2 className="h-4 w-4 mr-2 animate-spin" />}
              Create Configuration
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}

