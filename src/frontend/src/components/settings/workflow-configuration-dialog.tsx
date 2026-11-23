import { useState, useEffect } from 'react';
import { useTranslation } from 'react-i18next';
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from '@/components/ui/dialog';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Switch } from '@/components/ui/switch';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import { useToast } from '@/hooks/use-toast';
import { useApi } from '@/hooks/use-api';

import { ContentSkeleton } from '@/components/common/content-skeleton';
import EntityPatternsField from './entity-patterns-field';
import TagSyncConfigsField from './tag-sync-configs-field';
import { WorkflowParameterDefinition, EntityPatternConfig, TagSyncConfig } from '@/types/workflow-configurations';
import { ActionSpinner } from '@/components/ui/action-spinner';

// Stands in for the parameters while they load (see ContentSkeleton)
const SAMPLE_PARAMETER_DEFS: WorkflowParameterDefinition[] = [
  { name: 'catalog', type: 'string', description: 'Catalog to scan' },
  { name: 'max_rows', type: 'integer', min_value: 1, max_value: 1000 },
  { name: 'enabled', type: 'boolean' },
];

interface WorkflowConfigurationDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  workflowId: string;
  workflowName: string;
}

export default function WorkflowConfigurationDialog({
  open,
  onOpenChange,
  workflowId,
  workflowName
}: WorkflowConfigurationDialogProps) {
  const { t } = useTranslation(['settings', 'common']);
  const { toast } = useToast();
  const { get, put } = useApi();

  const [parameterDefs, setParameterDefs] = useState<WorkflowParameterDefinition[]>([]);
  const [configuration, setConfiguration] = useState<Record<string, any>>({});
  // Starts loading: the first open shows the skeleton, not "no parameters"
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    if (open && workflowId) {
      loadConfiguration();
    }
  }, [open, workflowId]);

  const loadConfiguration = async () => {
    setLoading(true);
    try {
      // Load parameter definitions
      const defsResponse = await get<WorkflowParameterDefinition[]>(
        `/api/jobs/workflows/${encodeURIComponent(workflowId)}/parameter-definitions`
      );
      
      if (defsResponse.data) {
        setParameterDefs(defsResponse.data);
        
        // Initialize configuration with defaults
        const defaults: Record<string, any> = {};
        defsResponse.data.forEach(def => {
          if (def.default !== undefined) {
            defaults[def.name] = def.default;
          }
        });
        
        // Load saved configuration
        const configResponse = await get<{ workflow_id: string; configuration: Record<string, any> }>(
          `/api/jobs/workflows/${encodeURIComponent(workflowId)}/configuration`
        );
        
        if (configResponse.data?.configuration) {
          // Merge saved configuration with defaults
          setConfiguration({ ...defaults, ...configResponse.data.configuration });
        } else {
          setConfiguration(defaults);
        }
      }
    } catch (error: any) {
      toast({
        title: t('common:status.error'),
        description: error.message || t('settings:workflowConfig.loadError'),
        variant: 'destructive'
      });
    } finally {
      setLoading(false);
    }
  };

  const handleSave = async () => {
    setSaving(true);
    try {
      await put(
        `/api/jobs/workflows/${encodeURIComponent(workflowId)}/configuration`,
        { configuration }
      );
      
      toast({
        title: t('common:status.success'),
        description: t('settings:workflowConfig.saveSuccess')
      });
      
      onOpenChange(false);
    } catch (error: any) {
      toast({
        title: t('common:status.error'),
        description: error.message || t('settings:workflowConfig.saveError'),
        variant: 'destructive'
      });
    } finally {
      setSaving(false);
    }
  };

  const renderField = (paramDef: WorkflowParameterDefinition) => {
    const value = configuration[paramDef.name];
    
    switch (paramDef.type) {
      case 'string':
        return (
          <div key={paramDef.name} className="space-y-2">
            <Label htmlFor={paramDef.name}>
              {paramDef.name}
              {paramDef.required && <span className="text-red-500 ml-1">*</span>}
            </Label>
            {paramDef.description && (
              <p className="text-sm text-muted-foreground">{paramDef.description}</p>
            )}
            <Input
              id={paramDef.name}
              value={value || ''}
              onChange={(e) => setConfiguration({ ...configuration, [paramDef.name]: e.target.value })}
              placeholder={paramDef.default?.toString() || ''}
              required={paramDef.required}
            />
          </div>
        );
      
      case 'integer':
        return (
          <div key={paramDef.name} className="space-y-2">
            <Label htmlFor={paramDef.name}>
              {paramDef.name}
              {paramDef.required && <span className="text-red-500 ml-1">*</span>}
            </Label>
            {paramDef.description && (
              <p className="text-sm text-muted-foreground">{paramDef.description}</p>
            )}
            <Input
              id={paramDef.name}
              type="number"
              value={value !== undefined ? value : ''}
              onChange={(e) => setConfiguration({ ...configuration, [paramDef.name]: parseInt(e.target.value) || 0 })}
              min={paramDef.min_value}
              max={paramDef.max_value}
              required={paramDef.required}
            />
          </div>
        );
      
      case 'boolean':
        return (
          <div key={paramDef.name} className="flex items-center space-x-2 py-2">
            <Switch
              id={paramDef.name}
              checked={!!value}
              onCheckedChange={(checked) => setConfiguration({ ...configuration, [paramDef.name]: checked })}
            />
            <Label htmlFor={paramDef.name} className="cursor-pointer">
              {paramDef.name}
              {paramDef.description && <span className="text-sm text-muted-foreground ml-2">- {paramDef.description}</span>}
            </Label>
          </div>
        );
      
      case 'select':
        return (
          <div key={paramDef.name} className="space-y-2">
            <Label htmlFor={paramDef.name}>
              {paramDef.name}
              {paramDef.required && <span className="text-red-500 ml-1">*</span>}
            </Label>
            {paramDef.description && (
              <p className="text-sm text-muted-foreground">{paramDef.description}</p>
            )}
            <Select
              value={value?.toString() || ''}
              onValueChange={(val) => setConfiguration({ ...configuration, [paramDef.name]: val })}
            >
              <SelectTrigger id={paramDef.name}>
                <SelectValue placeholder={t('settings:workflowConfig.selectOption')} />
              </SelectTrigger>
              <SelectContent>
                {paramDef.options?.map(option => (
                  <SelectItem key={option} value={option}>
                    {option}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
        );
      
      case 'entity_patterns':
        return (
          <div key={paramDef.name} className="space-y-2">
            <Label>
              {paramDef.name}
              {paramDef.required && <span className="text-red-500 ml-1">*</span>}
            </Label>
            {paramDef.description && (
              <p className="text-sm text-muted-foreground mb-2">{paramDef.description}</p>
            )}
            <EntityPatternsField
              value={(value as EntityPatternConfig[]) || []}
              onChange={(patterns) => setConfiguration({ ...configuration, [paramDef.name]: patterns })}
              entityTypes={paramDef.entity_types || ['contract', 'product', 'domain']}
            />
          </div>
        );

      case 'tag_sync_configs':
        return (
          <div key={paramDef.name} className="space-y-2">
            <Label>
              {paramDef.name}
              {paramDef.required && <span className="text-red-500 ml-1">*</span>}
            </Label>
            {paramDef.description && (
              <p className="text-sm text-muted-foreground mb-2">{paramDef.description}</p>
            )}
            <TagSyncConfigsField
              value={(value as TagSyncConfig[]) || []}
              onChange={(configs) => setConfiguration({ ...configuration, [paramDef.name]: configs })}
              entityTypes={paramDef.entity_types || ['semantic_assignment', 'data_domain', 'data_contract', 'data_product']}
            />
          </div>
        );

      default:
        return null;
    }
  };

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-4xl max-h-[90vh] overflow-y-auto">
        <DialogHeader>
          <DialogTitle>{t('settings:workflowConfig.title', { name: workflowName })}</DialogTitle>
          <DialogDescription>
            {t('settings:workflowConfig.description')}
          </DialogDescription>
        </DialogHeader>

        <ContentSkeleton
          data={parameterDefs}
          sample={SAMPLE_PARAMETER_DEFS}
          loading={loading}
          empty={parameterDefs.length === 0}
          emptyMessage={<p className="text-muted-foreground">{t('settings:workflowConfig.noParameters')}</p>}
          contentClassName="space-y-6 py-4"
        >
          {(defs) => defs.map(paramDef => renderField(paramDef))}
        </ContentSkeleton>

        <DialogFooter>
          <Button variant="outline" onClick={() => onOpenChange(false)} disabled={saving}>
            {t('common:actions.cancel')}
          </Button>
          <Button onClick={handleSave} disabled={loading || saving}>
            {saving && <ActionSpinner className="mr-2" />}
            {t('settings:workflowConfig.saveButton')}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

