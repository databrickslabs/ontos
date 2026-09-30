import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Switch } from '@/components/ui/switch';
import { Button } from '@/components/ui/button';
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from '@/components/ui/collapsible';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import { Alert, AlertDescription } from '@/components/ui/alert';
import { ChevronDown, ChevronRight, Info } from 'lucide-react';
import { EntityPatternConfig } from '@/types/workflow-configurations';

interface EntityPatternsFieldProps {
  value: EntityPatternConfig[];
  onChange: (patterns: EntityPatternConfig[]) => void;
  entityTypes: string[];
}

export default function EntityPatternsField({ value, onChange, entityTypes }: EntityPatternsFieldProps) {
  const { t } = useTranslation(['settings', 'common']);
  const [activeTab, setActiveTab] = useState<string>(entityTypes[0] || 'contract');

  // Ensure we have a pattern config for each entity type
  const getPatternForType = (entityType: string): EntityPatternConfig => {
    const existing = value.find(p => p.entity_type === entityType);
    if (existing) return existing;
    
    // Return default config
    return {
      entity_type: entityType,
      enabled: false,
      key_pattern: '',
      value_extraction_source: 'key',
      value_extraction_pattern: ''
    };
  };

  const updatePattern = (entityType: string, updates: Partial<EntityPatternConfig>) => {
    const newPatterns = [...value];
    const index = newPatterns.findIndex(p => p.entity_type === entityType);
    
    if (index >= 0) {
      newPatterns[index] = { ...newPatterns[index], ...updates };
    } else {
      newPatterns.push({ ...getPatternForType(entityType), ...updates });
    }
    
    onChange(newPatterns);
  };

  const [filterExpanded, setFilterExpanded] = useState<Record<string, boolean>>({});

  return (
    <div className="space-y-4">
      <Alert>
        <Info className="h-4 w-4" />
        <AlertDescription>
          {t('settings:tags.entityPatterns.intro')}
        </AlertDescription>
      </Alert>

      <Tabs value={activeTab} onValueChange={setActiveTab}>
        <TabsList className="grid w-full" style={{ gridTemplateColumns: `repeat(${entityTypes.length}, 1fr)` }}>
          {entityTypes.map(type => (
            <TabsTrigger key={type} value={type} className="capitalize">
              {type}
            </TabsTrigger>
          ))}
        </TabsList>

        {entityTypes.map(entityType => {
          const pattern = getPatternForType(entityType);
          
          return (
            <TabsContent key={entityType} value={entityType}>
              <Card>
                <CardHeader>
                  <CardTitle className="flex items-center justify-between">
                    <span className="capitalize">{t('settings:tags.entityPatterns.discoveryTitle', { type: entityType })}</span>
                    <div className="flex items-center gap-2">
                      <Label htmlFor={`${entityType}-enabled`}>{t('settings:tags.enable')}</Label>
                      <Switch
                        id={`${entityType}-enabled`}
                        checked={pattern.enabled}
                        onCheckedChange={(enabled) => updatePattern(entityType, { enabled })}
                      />
                    </div>
                  </CardTitle>
                  <CardDescription>
                    {t('settings:tags.entityPatterns.cardDescription', { type: entityType })}
                  </CardDescription>
                </CardHeader>
                <CardContent className="space-y-4">
                  {/* Filter Pattern (Optional) */}
                  <Collapsible
                    open={filterExpanded[entityType]}
                    onOpenChange={(open) => setFilterExpanded({ ...filterExpanded, [entityType]: open })}
                  >
                    <CollapsibleTrigger asChild>
                      <Button variant="ghost" className="w-full justify-between p-0 hover:no-underline">
                        <span className="text-sm font-medium">{t('settings:tags.entityPatterns.filterPatternOptional')}</span>
                        {filterExpanded[entityType] ? (
                          <ChevronDown className="h-4 w-4" />
                        ) : (
                          <ChevronRight className="h-4 w-4" />
                        )}
                      </Button>
                    </CollapsibleTrigger>
                    <CollapsibleContent className="space-y-3 pt-3">
                      <p className="text-sm text-muted-foreground">
                        {t('settings:tags.entityPatterns.filterHelp')}
                      </p>
                      <div className="space-y-2">
                        <Label>{t('settings:tags.entityPatterns.filterSource')}</Label>
                        <Select
                          value={pattern.filter_source || 'key'}
                          onValueChange={(source) => updatePattern(entityType, { filter_source: source })}
                        >
                          <SelectTrigger>
                            <SelectValue />
                          </SelectTrigger>
                          <SelectContent>
                            <SelectItem value="key">{t('settings:tags.entityPatterns.tagKey')}</SelectItem>
                            <SelectItem value="value">{t('settings:tags.entityPatterns.tagValue')}</SelectItem>
                          </SelectContent>
                        </Select>
                      </div>
                      <div className="space-y-2">
                        <Label>{t('settings:tags.entityPatterns.filterPatternRegex')}</Label>
                        <Input
                          value={pattern.filter_pattern || ''}
                          onChange={(e) => updatePattern(entityType, { filter_pattern: e.target.value })}
                          placeholder="^include-.*$"
                        />
                      </div>
                    </CollapsibleContent>
                  </Collapsible>

                  {/* Key Pattern (Required) */}
                  <div className="space-y-2">
                    <Label className="text-base font-semibold">{t('settings:tags.entityPatterns.keyPatternRequired')}</Label>
                    <p className="text-sm text-muted-foreground">
                      {t('settings:tags.entityPatterns.keyPatternHelp')}
                    </p>
                    <Input
                      value={pattern.key_pattern}
                      onChange={(e) => updatePattern(entityType, { key_pattern: e.target.value })}
                      placeholder={`^data-${entityType}-.*$`}
                      required
                    />
                  </div>

                  {/* Value Extraction (Required) */}
                  <div className="space-y-3">
                    <Label className="text-base font-semibold">{t('settings:tags.entityPatterns.valueExtractionRequired')}</Label>
                    <p className="text-sm text-muted-foreground">
                      {t('settings:tags.entityPatterns.valueExtractionHelp', { type: entityType })}
                    </p>
                    <div className="space-y-2">
                      <Label>{t('settings:tags.entityPatterns.extractionSource')}</Label>
                      <Select
                        value={pattern.value_extraction_source}
                        onValueChange={(source) => updatePattern(entityType, { value_extraction_source: source })}
                      >
                        <SelectTrigger>
                          <SelectValue />
                        </SelectTrigger>
                        <SelectContent>
                          <SelectItem value="key">{t('settings:tags.entityPatterns.tagKey')}</SelectItem>
                          <SelectItem value="value">{t('settings:tags.entityPatterns.tagValue')}</SelectItem>
                        </SelectContent>
                      </Select>
                    </div>
                    <div className="space-y-2">
                      <Label>{t('settings:tags.entityPatterns.extractionPatternLabel')}</Label>
                      <Input
                        value={pattern.value_extraction_pattern}
                        onChange={(e) => updatePattern(entityType, { value_extraction_pattern: e.target.value })}
                        placeholder={`^data-${entityType}-(.+)$`}
                        required
                      />
                      <p className="text-xs text-muted-foreground">
                        {t('settings:tags.entityPatterns.extractionExampleBefore', { type: entityType })} <code>^data-{entityType}-(.+)$</code> {t('settings:tags.entityPatterns.extractionExampleAfter', { type: entityType })}
                      </p>
                    </div>
                  </div>
                </CardContent>
              </Card>
            </TabsContent>
          );
        })}
      </Tabs>
    </div>
  );
}

