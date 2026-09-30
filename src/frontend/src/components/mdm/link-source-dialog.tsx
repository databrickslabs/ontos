import { useState, useEffect, useMemo } from 'react';
import { useTranslation } from 'react-i18next';
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
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select';
import { Loader2, Plus, X, AlertCircle, Wand2, Info } from 'lucide-react';
import { Badge } from '@/components/ui/badge';
import { Alert, AlertDescription } from '@/components/ui/alert';
import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from "@/components/ui/tooltip";

import { useApi } from '@/hooks/use-api';
import { useToast } from '@/hooks/use-toast';
import { MdmSourceLinkCreate } from '@/types/mdm';

// Simple Levenshtein distance for fuzzy column matching
function levenshteinDistance(a: string, b: string): number {
  const matrix: number[][] = [];
  for (let i = 0; i <= b.length; i++) matrix[i] = [i];
  for (let j = 0; j <= a.length; j++) matrix[0][j] = j;
  for (let i = 1; i <= b.length; i++) {
    for (let j = 1; j <= a.length; j++) {
      matrix[i][j] = b.charAt(i - 1) === a.charAt(j - 1)
        ? matrix[i - 1][j - 1]
        : Math.min(matrix[i - 1][j - 1] + 1, matrix[i][j - 1] + 1, matrix[i - 1][j] + 1);
    }
  }
  return matrix[b.length][a.length];
}

// Calculate similarity score (0-1)
function columnSimilarity(source: string, target: string): number {
  const s = source.toLowerCase().replace(/[_-]/g, '');
  const t = target.toLowerCase().replace(/[_-]/g, '');
  const maxLen = Math.max(s.length, t.length);
  if (maxLen === 0) return 1;
  const distance = levenshteinDistance(s, t);
  return 1 - distance / maxLen;
}

// Find best matching target column for a source column
function findBestMatch(source: string, targets: string[], threshold = 0.6): string | null {
  let bestMatch: string | null = null;
  let bestScore = threshold;
  
  for (const target of targets) {
    const score = columnSimilarity(source, target);
    if (score > bestScore) {
      bestScore = score;
      bestMatch = target;
    }
  }
  return bestMatch;
}

interface SchemaProperty {
  name: string;
  logicalType?: string;
  logical_type?: string;
  description?: string;
}

interface SchemaObject {
  name: string;
  properties?: SchemaProperty[];
}

interface DataContract {
  id: string;
  name: string;
  status: string;
  schema?: SchemaObject[];
  customProperties?: Record<string, any>;
}

type FormValues = {
  source_contract_id: string;
  key_column: string;
  priority: number;
};

interface LinkSourceDialogProps {
  isOpen: boolean;
  configId: string;
  masterContractId?: string; // To fetch master schema for column mapping
  onClose: () => void;
  onSuccess: () => void;
}

export default function LinkSourceDialog({ isOpen, configId, masterContractId, onClose, onSuccess }: LinkSourceDialogProps) {
  const [contracts, setContracts] = useState<DataContract[]>([]);
  const [loading, setLoading] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [columnMapping, setColumnMapping] = useState<Record<string, string>>({});
  const [newMappingSource, setNewMappingSource] = useState('');
  const [newMappingTarget, setNewMappingTarget] = useState('');
  
  // Schema columns for dropdowns
  const [sourceColumns, setSourceColumns] = useState<string[]>([]);
  const [masterColumns, setMasterColumns] = useState<string[]>([]);
  const [loadingSchema, setLoadingSchema] = useState(false);

  const { t } = useTranslation(['mdm', 'common']);
  const { get, post } = useApi();
  const { toast } = useToast();

  const formSchema = useMemo(
    () =>
      z.object({
        source_contract_id: z.string().min(1, t('mdm:link.sourceContractRequired')),
        key_column: z.string().min(1, t('mdm:link.keyColumnRequired')),
        priority: z.coerce.number().min(0).max(100),
      }),
    [t]
  );

  const form = useForm<FormValues>({
    resolver: zodResolver(formSchema),
    defaultValues: {
      source_contract_id: '',
      key_column: '',
      priority: 1,
    },
  });

  const selectedSourceId = form.watch('source_contract_id');

  useEffect(() => {
    if (isOpen) {
      fetchContracts();
      form.reset({ source_contract_id: '', key_column: '', priority: 1 });
      setColumnMapping({});
      setSourceColumns([]);
      setNewMappingSource('');
      setNewMappingTarget('');
    }
  }, [isOpen]);

  // Fetch master contract schema when dialog opens
  useEffect(() => {
    if (isOpen && masterContractId) {
      fetchMasterSchema(masterContractId);
    }
  }, [isOpen, masterContractId]);

  // Fetch source contract schema when source is selected
  useEffect(() => {
    if (selectedSourceId) {
      fetchSourceSchema(selectedSourceId);
    } else {
      setSourceColumns([]);
    }
  }, [selectedSourceId]);

  const fetchContracts = async () => {
    setLoading(true);
    try {
      const response = await get<DataContract[]>('/api/data-contracts');
      if (response.data) {
        // Filter to only active contracts (exclude the master contract)
        const activeContracts = response.data.filter(
          c => c.status === 'active' && c.id !== masterContractId
        );
        setContracts(activeContracts);
      }
    } catch (err) {
      console.error('Error fetching contracts:', err);
    } finally {
      setLoading(false);
    }
  };

  const fetchMasterSchema = async (contractId: string) => {
    try {
      const response = await get<DataContract>(`/api/data-contracts/${contractId}`);
      if (response.data?.schema?.[0]?.properties) {
        const columns = response.data.schema[0].properties.map(p => p.name);
        setMasterColumns(columns);
      }
    } catch (err) {
      console.error('Error fetching master schema:', err);
    }
  };

  const fetchSourceSchema = async (contractId: string) => {
    setLoadingSchema(true);
    try {
      const response = await get<DataContract>(`/api/data-contracts/${contractId}`);
      if (response.data?.schema?.[0]?.properties) {
        const columns = response.data.schema[0].properties.map(p => p.name);
        setSourceColumns(columns);
        
        // Check for MDM config in customProperties
        const customProps = response.data.customProperties || {};
        
        // Auto-set key column from customProperties or detect it
        const mdmKeyColumn = customProps.mdmKeyColumn;
        if (mdmKeyColumn && columns.includes(mdmKeyColumn)) {
          form.setValue('key_column', mdmKeyColumn);
        } else {
          // Fallback: detect key column
          const keyCandidate = columns.find(c => 
            c.endsWith('_id') || c === 'id' || c.includes('key') || c.includes('uuid')
          );
          if (keyCandidate && !form.getValues('key_column')) {
            form.setValue('key_column', keyCandidate);
          }
        }
        
        // Auto-set priority from customProperties
        const mdmPriority = customProps.mdmSourcePriority;
        if (mdmPriority !== undefined && mdmPriority !== null) {
          const priorityNum = typeof mdmPriority === 'number' ? mdmPriority : parseInt(String(mdmPriority), 10);
          if (!isNaN(priorityNum)) {
            form.setValue('priority', priorityNum);
          }
        }
        
        // Auto-populate column mappings from customProperties
        let mdmMappings = customProps.mdmColumnMappings;
        if (mdmMappings) {
          // Parse if stored as JSON string
          if (typeof mdmMappings === 'string') {
            try {
              mdmMappings = JSON.parse(mdmMappings);
            } catch (e) {
              console.error('Failed to parse mdmColumnMappings:', e);
              mdmMappings = null;
            }
          }
          
          if (mdmMappings && typeof mdmMappings === 'object') {
            // mdmMappings is source → master format
            const newMappings: Record<string, string> = {};
            for (const [sourceCol, masterCol] of Object.entries(mdmMappings)) {
              if (typeof masterCol === 'string' && columns.includes(sourceCol)) {
                newMappings[sourceCol] = masterCol;
              }
            }
            if (Object.keys(newMappings).length > 0) {
              setColumnMapping(newMappings);
              toast({
                title: t('mdm:link.configLoadedTitle'),
                description: t('mdm:link.mappingsLoaded', { count: Object.keys(newMappings).length }),
              });
            }
          }
        }
      }
    } catch (err) {
      console.error('Error fetching source schema:', err);
    } finally {
      setLoadingSchema(false);
    }
  };

  // Suggest column mappings using fuzzy matching
  const suggestMappings = () => {
    if (sourceColumns.length === 0 || masterColumns.length === 0) return;
    
    const suggestions: Record<string, string> = {};
    const usedTargets = new Set<string>();
    
    // First pass: exact name matches (source column exists in master with same name)
    for (const sourceCol of sourceColumns) {
      if (columnMapping[sourceCol]) continue; // Already mapped
      if (masterColumns.includes(sourceCol)) {
        suggestions[sourceCol] = sourceCol;
        usedTargets.add(sourceCol);
      }
    }
    
    // Second pass: fuzzy matches for remaining columns
    for (const sourceCol of sourceColumns) {
      if (columnMapping[sourceCol] || suggestions[sourceCol]) continue;
      
      const bestMatch = findBestMatch(sourceCol, masterColumns.filter(c => !usedTargets.has(c)), 0.5);
      if (bestMatch) {
        suggestions[sourceCol] = bestMatch;
        usedTargets.add(bestMatch);
      }
    }
    
    if (Object.keys(suggestions).length > 0) {
      setColumnMapping(prev => ({ ...prev, ...suggestions }));
      toast({
        title: t('mdm:link.mappingsSuggestedTitle'),
        description: t('mdm:link.mappingsFound', { count: Object.keys(suggestions).length }),
      });
    } else {
      toast({
        title: t('mdm:link.noSuggestionsTitle'),
        description: t('mdm:link.noMatchingColumns'),
        variant: 'destructive',
      });
    }
  };

  const addColumnMapping = () => {
    if (newMappingSource && newMappingTarget) {
      setColumnMapping(prev => ({
        ...prev,
        [newMappingSource]: newMappingTarget,
      }));
      setNewMappingSource('');
      setNewMappingTarget('');
    }
  };

  const removeColumnMapping = (sourceCol: string) => {
    setColumnMapping(prev => {
      const updated = { ...prev };
      delete updated[sourceCol];
      return updated;
    });
  };

  const onSubmit = async (values: FormValues) => {
    setSubmitting(true);
    try {
      const data: MdmSourceLinkCreate = {
        source_contract_id: values.source_contract_id,
        key_column: values.key_column,
        column_mapping: columnMapping,
        priority: values.priority,
      };

      const response = await post(`/api/mdm/configs/${configId}/sources`, data);
      if (response.data) {
        toast({ title: t('common:status.success'), description: t('mdm:link.linkSuccess') });
        onSuccess();
      }
    } catch (err: any) {
      toast({
        title: t('common:status.error'),
        description: err.message || t('mdm:link.linkFailed'),
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
          <DialogTitle>{t('mdm:configDetails.linkSource')}</DialogTitle>
          <DialogDescription>
            {t('mdm:link.dialogDescription')}
          </DialogDescription>
        </DialogHeader>

        <form onSubmit={form.handleSubmit(onSubmit)} className="space-y-4">
          <div className="space-y-2">
            <Label htmlFor="source_contract">{t('mdm:link.sourceContractLabel')}</Label>
            <Select
              value={form.watch('source_contract_id')}
              onValueChange={(value) => form.setValue('source_contract_id', value)}
              disabled={loading}
            >
              <SelectTrigger>
                {loading ? (
                  <span className="flex items-center gap-2">
                    <Loader2 className="h-4 w-4 animate-spin" />
                    {t('common:states.loading')}
                  </span>
                ) : (
                  <SelectValue placeholder={t('mdm:link.selectSourceContract')} />
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
                    {t('mdm:messages.noActiveContracts')}
                  </SelectItem>
                )}
              </SelectContent>
            </Select>
            {form.formState.errors.source_contract_id && (
              <p className="text-sm text-destructive">
                {form.formState.errors.source_contract_id.message}
              </p>
            )}
          </div>

          <div className="grid grid-cols-2 gap-4">
            <div className="space-y-2">
              <Label htmlFor="key_column">{t('mdm:sourcesTab.keyColumn')}</Label>
              {sourceColumns.length > 0 ? (
                <Select
                  value={form.watch('key_column')}
                  onValueChange={(value) => form.setValue('key_column', value)}
                  disabled={loadingSchema}
                >
                  <SelectTrigger>
                    {loadingSchema ? (
                      <span className="flex items-center gap-2">
                        <Loader2 className="h-4 w-4 animate-spin" />
                        {t('common:states.loading')}
                      </span>
                    ) : (
                      <SelectValue placeholder={t('mdm:link.selectKeyColumn')} />
                    )}
                  </SelectTrigger>
                  <SelectContent>
                    {sourceColumns.map((col) => (
                      <SelectItem key={col} value={col}>
                        {col}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              ) : (
                <Input
                  id="key_column"
                  placeholder={t('mdm:link.selectSourceFirst')}
                  disabled={!selectedSourceId}
                  {...form.register('key_column')}
                />
              )}
              {form.formState.errors.key_column && (
                <p className="text-sm text-destructive">{form.formState.errors.key_column.message}</p>
              )}
            </div>

            <div className="space-y-2">
              <Label htmlFor="priority">{t('common:labels.priority')}</Label>
              <Input
                id="priority"
                type="number"
                min={0}
                max={100}
                {...form.register('priority')}
              />
              <p className="text-xs text-muted-foreground">
                {t('mdm:link.priorityHint')}
              </p>
            </div>
          </div>

          <div className="space-y-2">
            <div className="flex items-center justify-between">
              <div>
                <Label>{t('mdm:link.columnMappingLabel')}</Label>
                <p className="text-xs text-muted-foreground">
                  {t('mdm:link.columnMappingHint')}
                </p>
              </div>
              <TooltipProvider>
                <Tooltip>
                  <TooltipTrigger asChild>
                    <Button
                      type="button"
                      variant="outline"
                      size="sm"
                      onClick={suggestMappings}
                      disabled={sourceColumns.length === 0 || masterColumns.length === 0}
                    >
                      <Wand2 className="h-4 w-4 mr-1" />
                      {t('mdm:link.suggest')}
                    </Button>
                  </TooltipTrigger>
                  <TooltipContent>
                    <p>{t('mdm:link.suggestTooltip')}</p>
                  </TooltipContent>
                </Tooltip>
              </TooltipProvider>
            </div>
            
            {Object.keys(columnMapping).length > 0 && (
              <div className="flex flex-wrap gap-2 mb-2">
                {Object.entries(columnMapping).map(([source, target]) => (
                  <Badge key={source} variant="secondary" className="flex items-center gap-1">
                    {source} → {target}
                    <button
                      type="button"
                      onClick={() => removeColumnMapping(source)}
                      className="ml-1 hover:text-destructive"
                    >
                      <X className="h-3 w-3" />
                    </button>
                  </Badge>
                ))}
              </div>
            )}

            {sourceColumns.length > 0 && masterColumns.length > 0 ? (
              <div className="flex gap-2 items-center">
                <Select
                  value={newMappingSource}
                  onValueChange={setNewMappingSource}
                >
                  <SelectTrigger className="flex-1">
                    <SelectValue placeholder={t('mdm:link.sourceColumn')} />
                  </SelectTrigger>
                  <SelectContent>
                    {sourceColumns
                      .filter(col => !Object.keys(columnMapping).includes(col))
                      .map((col) => (
                        <SelectItem key={col} value={col}>
                          {col}
                        </SelectItem>
                      ))}
                  </SelectContent>
                </Select>
                <span className="text-muted-foreground">→</span>
                <Select
                  value={newMappingTarget}
                  onValueChange={setNewMappingTarget}
                >
                  <SelectTrigger className="flex-1">
                    <SelectValue placeholder={t('mdm:link.masterColumn')} />
                  </SelectTrigger>
                  <SelectContent>
                    {masterColumns.map((col) => (
                      <SelectItem key={col} value={col}>
                        {col}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
                <Button
                  type="button"
                  variant="outline"
                  size="icon"
                  onClick={addColumnMapping}
                  disabled={!newMappingSource || !newMappingTarget}
                >
                  <Plus className="h-4 w-4" />
                </Button>
              </div>
            ) : (
              <div className="flex gap-2">
                <Input
                  placeholder={t('mdm:link.sourceColumn')}
                  value={newMappingSource}
                  onChange={(e) => setNewMappingSource(e.target.value)}
                  className="flex-1"
                  disabled={!selectedSourceId}
                />
                <span className="flex items-center text-muted-foreground">→</span>
                <Input
                  placeholder={t('mdm:link.masterColumn')}
                  value={newMappingTarget}
                  onChange={(e) => setNewMappingTarget(e.target.value)}
                  className="flex-1"
                  disabled={!selectedSourceId}
                />
                <Button
                  type="button"
                  variant="outline"
                  size="icon"
                  onClick={addColumnMapping}
                  disabled={!newMappingSource || !newMappingTarget}
                >
                  <Plus className="h-4 w-4" />
                </Button>
              </div>
            )}

            {selectedSourceId && sourceColumns.length === 0 && !loadingSchema && (
              <Alert variant="destructive" className="mt-2">
                <AlertCircle className="h-4 w-4" />
                <AlertDescription>
                  {t('mdm:link.schemaLoadError')}
                </AlertDescription>
              </Alert>
            )}

            {Object.keys(columnMapping).length > 0 && (
              <Alert className="mt-2">
                <Info className="h-4 w-4" />
                <AlertDescription>
                  {t('mdm:link.mappingsConfigured', { count: Object.keys(columnMapping).length })}
                </AlertDescription>
              </Alert>
            )}
          </div>

          <DialogFooter>
            <Button type="button" variant="outline" onClick={onClose} disabled={submitting}>
              {t('common:actions.cancel')}
            </Button>
            <Button type="submit" disabled={submitting}>
              {submitting && <Loader2 className="h-4 w-4 mr-2 animate-spin" />}
              {t('mdm:link.submitButton')}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}

