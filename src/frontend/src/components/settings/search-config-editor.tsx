import { useState, useEffect, useCallback } from 'react';
import { useTranslation } from 'react-i18next';
import { Card, CardContent, CardDescription, CardHeader, CardTitle, CardFooter } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Switch } from '@/components/ui/switch';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import { Accordion, AccordionContent, AccordionItem, AccordionTrigger } from '@/components/ui/accordion';
import { Badge } from '@/components/ui/badge';
import { Separator } from '@/components/ui/separator';
import { Alert, AlertDescription } from '@/components/ui/alert';
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs';
import { Loader2, Save, RefreshCw, Search, Settings2, Layers, ArrowUpDown, Check, AlertCircle } from 'lucide-react';
import { useToast } from '@/hooks/use-toast';
import { usePermissions } from '@/stores/permissions-store';
import { 
  FeatureAccessLevel, 
  SearchConfig, 
  FieldConfig, 
  AssetTypeConfig, 
  MatchType, 
  SortField,
  // DefaultsConfig - unused
  RankingConfig,
} from '@/types/settings';


const MATCH_TYPE_LABELS: Record<MatchType, string> = {
  [MatchType.PREFIX]: 'Prefix (start of word)',
  [MatchType.SUBSTRING]: 'Substring (anywhere)',
  [MatchType.EXACT]: 'Exact match only',
  [MatchType.FUZZY]: 'Fuzzy (allow typos)',
};

const SORT_FIELD_LABELS: Record<SortField, string> = {
  [SortField.MATCH_PRIORITY]: 'Field Priority (title > description > tags)',
  [SortField.BOOST_SCORE]: 'Boost Score (weighted relevance)',
  [SortField.TITLE_ASC]: 'Title (A → Z)',
  [SortField.TITLE_DESC]: 'Title (Z → A)',
};

const ASSET_TYPE_DISPLAY_NAMES: Record<string, string> = {
  'data-product': 'Data Products',
  'data-contract': 'Data Contracts',
  'glossary-term': 'Glossary Terms',
  'dataset': 'Datasets',
  'data-asset-review': 'Asset Reviews',
  'tag': 'Tags',
  'data-domain': 'Data Domains',
};

interface FieldConfigEditorProps {
  fieldName: string;
  config: FieldConfig;
  onChange: (config: FieldConfig) => void;
  disabled?: boolean;
  showSource?: boolean;
}

function FieldConfigEditor({ 
  fieldName, 
  config, 
  onChange, 
  disabled = false,
  showSource = false,
}: FieldConfigEditorProps) {
  return (
    <div className="border rounded-lg p-4 space-y-4 bg-card">
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          <span className="font-medium capitalize">{fieldName}</span>
          {showSource && config.source && (
            <Badge variant="outline" className="text-xs">
              source: {config.source}
            </Badge>
          )}
        </div>
        <div className="flex items-center gap-2">
          <Label htmlFor={`${fieldName}-indexed`} className="text-sm text-muted-foreground">
            Indexed
          </Label>
          <Switch
            id={`${fieldName}-indexed`}
            checked={config.indexed}
            onCheckedChange={(checked) => onChange({ ...config, indexed: checked })}
            disabled={disabled}
          />
        </div>
      </div>

      {config.indexed && (
        <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
          <div className="space-y-2">
            <Label className="text-sm">Match Type</Label>
            <Select
              value={config.match_type}
              onValueChange={(value) => onChange({ ...config, match_type: value as MatchType })}
              disabled={disabled}
            >
              <SelectTrigger>
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {Object.entries(MATCH_TYPE_LABELS).map(([value, label]) => (
                  <SelectItem key={value} value={value}>
                    {label}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>

          <div className="space-y-2">
            <Label className="text-sm">Priority (1-100)</Label>
            <Input
              type="number"
              value={config.priority}
              onChange={(e) => onChange({ ...config, priority: Math.max(1, Math.min(100, parseInt(e.target.value) || 1)) })}
              min={1}
              max={100}
              disabled={disabled}
              className="w-24"
            />
            <p className="text-xs text-muted-foreground">Lower = higher importance</p>
          </div>

          <div className="space-y-2">
            <Label className="text-sm">Boost (0-10)</Label>
            <Input
              type="number"
              value={config.boost.toFixed(1)}
              onChange={(e) => onChange({ ...config, boost: Math.max(0, Math.min(10, parseFloat(e.target.value) || 1)) })}
              min={0}
              max={10}
              step={0.1}
              disabled={disabled}
              className="w-24"
            />
            <p className="text-xs text-muted-foreground">Score multiplier for ranking</p>
          </div>
        </div>
      )}
    </div>
  );
}


export default function SearchConfigEditor() {
  const { t: _t } = useTranslation(['settings', 'common']);
  const { toast } = useToast();
  const { hasPermission } = usePermissions();
  
  const hasWriteAccess = hasPermission('settings', FeatureAccessLevel.ADMIN);

  const [config, setConfig] = useState<SearchConfig | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [isSaving, setIsSaving] = useState(false);
  const [isRebuilding, setIsRebuilding] = useState(false);
  const [hasChanges, setHasChanges] = useState(false);
  const [originalConfig, setOriginalConfig] = useState<SearchConfig | null>(null);

  // Load config on mount
  useEffect(() => {
    loadConfig();
  }, []);

  const loadConfig = async () => {
    setIsLoading(true);
    try {
      const response = await fetch('/api/settings/search-config');
      if (!response.ok) {
        throw new Error('Failed to load search configuration');
      }
      const data: SearchConfig = await response.json();
      setConfig(data);
      setOriginalConfig(JSON.parse(JSON.stringify(data)));
      setHasChanges(false);
    } catch (error) {
      console.error('Error loading search config:', error);
      toast({
        title: 'Error loading configuration',
        description: 'Failed to load search configuration. Please try again.',
        variant: 'destructive',
      });
    } finally {
      setIsLoading(false);
    }
  };

  const handleSave = async () => {
    if (!config) return;
    
    setIsSaving(true);
    try {
      const response = await fetch('/api/settings/search-config', {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          defaults: config.defaults,
          asset_types: config.asset_types,
          ranking: config.ranking,
        }),
      });
      
      if (!response.ok) {
        throw new Error('Failed to save configuration');
      }
      
      const updatedConfig = await response.json();
      setConfig(updatedConfig);
      setOriginalConfig(JSON.parse(JSON.stringify(updatedConfig)));
      setHasChanges(false);
      
      toast({
        title: 'Configuration saved',
        description: 'Search configuration has been updated. Consider rebuilding the index to apply changes.',
      });
    } catch (error) {
      console.error('Error saving config:', error);
      toast({
        title: 'Error saving configuration',
        description: 'Failed to save search configuration. Please try again.',
        variant: 'destructive',
      });
    } finally {
      setIsSaving(false);
    }
  };

  const handleRebuildIndex = async () => {
    setIsRebuilding(true);
    try {
      const response = await fetch('/api/settings/search-config/rebuild-index', {
        method: 'POST',
      });
      
      if (!response.ok) {
        throw new Error('Failed to rebuild index');
      }
      
      const result = await response.json();
      
      toast({
        title: 'Index rebuilt',
        description: `Search index rebuilt with ${result.index_size} items.`,
      });
    } catch (error) {
      console.error('Error rebuilding index:', error);
      toast({
        title: 'Error rebuilding index',
        description: 'Failed to rebuild search index. Please try again.',
        variant: 'destructive',
      });
    } finally {
      setIsRebuilding(false);
    }
  };

  const updateConfig = useCallback((updates: Partial<SearchConfig>) => {
    setConfig(prev => {
      if (!prev) return prev;
      const newConfig = { ...prev, ...updates };
      setHasChanges(JSON.stringify(newConfig) !== JSON.stringify(originalConfig));
      return newConfig;
    });
  }, [originalConfig]);

  const updateDefaultField = useCallback((fieldName: 'title' | 'description' | 'tags', fieldConfig: FieldConfig) => {
    if (!config) return;
    updateConfig({
      defaults: {
        ...config.defaults,
        fields: {
          ...config.defaults.fields,
          [fieldName]: fieldConfig,
        },
      },
    });
  }, [config, updateConfig]);

  const updateAssetType = useCallback((assetType: string, assetConfig: AssetTypeConfig) => {
    if (!config) return;
    updateConfig({
      asset_types: {
        ...config.asset_types,
        [assetType]: assetConfig,
      },
    });
  }, [config, updateConfig]);

  const updateRanking = useCallback((ranking: RankingConfig) => {
    updateConfig({ ranking });
  }, [updateConfig]);

  if (isLoading) {
    return (
      <Card>
        <CardContent className="flex items-center justify-center py-12">
          <Loader2 className="h-8 w-8 animate-spin text-primary" />
        </CardContent>
      </Card>
    );
  }

  if (!config) {
    return (
      <Card>
        <CardContent className="py-8">
          <Alert variant="destructive">
            <AlertCircle className="h-4 w-4" />
            <AlertDescription>
              Failed to load search configuration. Please refresh the page.
            </AlertDescription>
          </Alert>
        </CardContent>
      </Card>
    );
  }

  return (
    <Card>
      <CardHeader>
        <div className="flex items-center justify-between">
          <div>
            <CardTitle className="flex items-center gap-2">
              <Search className="h-5 w-5" />
              Search Configuration
            </CardTitle>
            <CardDescription>
              Configure how the global search indexes and ranks results across different asset types.
            </CardDescription>
          </div>
          <Badge variant="outline">v{config.version}</Badge>
        </div>
      </CardHeader>

      <CardContent className="space-y-6">
        {hasChanges && (
          <Alert>
            <AlertCircle className="h-4 w-4" />
            <AlertDescription>
              You have unsaved changes. Save to persist your configuration.
            </AlertDescription>
          </Alert>
        )}

        <Tabs defaultValue="defaults" className="space-y-4">
          <TabsList className="grid w-full grid-cols-3">
            <TabsTrigger value="defaults" className="flex items-center gap-2">
              <Settings2 className="h-4 w-4" />
              Default Fields
            </TabsTrigger>
            <TabsTrigger value="asset-types" className="flex items-center gap-2">
              <Layers className="h-4 w-4" />
              Asset Types
            </TabsTrigger>
            <TabsTrigger value="ranking" className="flex items-center gap-2">
              <ArrowUpDown className="h-4 w-4" />
              Ranking
            </TabsTrigger>
          </TabsList>

          {/* Default Fields Tab */}
          <TabsContent value="defaults" className="space-y-4">
            <p className="text-sm text-muted-foreground">
              These settings apply to all asset types by default. Individual asset types can override these settings.
            </p>
            
            <div className="space-y-4">
              <FieldConfigEditor
                fieldName="title"
                config={config.defaults.fields.title}
                onChange={(c) => updateDefaultField('title', c)}
                disabled={!hasWriteAccess}
              />
              <FieldConfigEditor
                fieldName="description"
                config={config.defaults.fields.description}
                onChange={(c) => updateDefaultField('description', c)}
                disabled={!hasWriteAccess}
              />
              <FieldConfigEditor
                fieldName="tags"
                config={config.defaults.fields.tags}
                onChange={(c) => updateDefaultField('tags', c)}
                disabled={!hasWriteAccess}
              />
            </div>
          </TabsContent>

          {/* Asset Types Tab */}
          <TabsContent value="asset-types" className="space-y-4">
            <p className="text-sm text-muted-foreground">
              Configure search behavior for each asset type. Enable/disable indexing and customize extra fields.
            </p>

            <Accordion type="multiple" className="space-y-2">
              {Object.entries(config.asset_types).map(([assetType, assetConfig]) => (
                <AccordionItem key={assetType} value={assetType} className="border rounded-lg">
                  <AccordionTrigger className="px-4 hover:no-underline">
                    <div className="flex items-center gap-3">
                      <span className="font-medium">
                        {ASSET_TYPE_DISPLAY_NAMES[assetType] || assetType}
                      </span>
                      {assetConfig.enabled ? (
                        <Badge variant="default" className="text-xs">
                          <Check className="h-3 w-3 mr-1" />
                          Enabled
                        </Badge>
                      ) : (
                        <Badge variant="secondary" className="text-xs">
                          Disabled
                        </Badge>
                      )}
                      {Object.keys(assetConfig.extra_fields).length > 0 && (
                        <Badge variant="outline" className="text-xs">
                          +{Object.keys(assetConfig.extra_fields).length} extra fields
                        </Badge>
                      )}
                    </div>
                  </AccordionTrigger>
                  <AccordionContent className="px-4 pb-4 space-y-4">
                    <div className="flex items-center gap-6 py-2">
                      <div className="flex items-center gap-2">
                        <Switch
                          id={`${assetType}-enabled`}
                          checked={assetConfig.enabled}
                          onCheckedChange={(checked) => 
                            updateAssetType(assetType, { ...assetConfig, enabled: checked })
                          }
                          disabled={!hasWriteAccess}
                        />
                        <Label htmlFor={`${assetType}-enabled`}>Enable indexing</Label>
                      </div>
                      <div className="flex items-center gap-2">
                        <Switch
                          id={`${assetType}-inherit`}
                          checked={assetConfig.inherit_defaults}
                          onCheckedChange={(checked) =>
                            updateAssetType(assetType, { ...assetConfig, inherit_defaults: checked })
                          }
                          disabled={!hasWriteAccess || !assetConfig.enabled}
                        />
                        <Label htmlFor={`${assetType}-inherit`}>Inherit default field settings</Label>
                      </div>
                    </div>

                    {assetConfig.enabled && Object.keys(assetConfig.extra_fields).length > 0 && (
                      <>
                        <Separator />
                        <div className="space-y-2">
                          <h4 className="text-sm font-medium">Extra Fields</h4>
                          <p className="text-xs text-muted-foreground">
                            Additional fields specific to this asset type.
                          </p>
                          <div className="space-y-3">
                            {Object.entries(assetConfig.extra_fields).map(([fieldName, fieldConfig]) => (
                              <FieldConfigEditor
                                key={fieldName}
                                fieldName={fieldName}
                                config={fieldConfig}
                                onChange={(c) => updateAssetType(assetType, {
                                  ...assetConfig,
                                  extra_fields: {
                                    ...assetConfig.extra_fields,
                                    [fieldName]: c,
                                  },
                                })}
                                disabled={!hasWriteAccess}
                                showSource
                              />
                            ))}
                          </div>
                        </div>
                      </>
                    )}
                  </AccordionContent>
                </AccordionItem>
              ))}
            </Accordion>
          </TabsContent>

          {/* Ranking Tab */}
          <TabsContent value="ranking" className="space-y-4">
            <p className="text-sm text-muted-foreground">
              Configure how search results are sorted. Results matching higher priority fields appear first.
            </p>

            <div className="grid gap-4">
              <div className="space-y-2">
                <Label>Primary Sort</Label>
                <Select
                  value={config.ranking.primary_sort}
                  onValueChange={(value) => updateRanking({ ...config.ranking, primary_sort: value as SortField })}
                  disabled={!hasWriteAccess}
                >
                  <SelectTrigger>
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    {Object.entries(SORT_FIELD_LABELS).map(([value, label]) => (
                      <SelectItem key={value} value={value}>
                        {label}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
                <p className="text-xs text-muted-foreground">
                  The main criterion used to order results.
                </p>
              </div>

              <div className="space-y-2">
                <Label>Secondary Sort (tie-breaker)</Label>
                <Select
                  value={config.ranking.secondary_sort}
                  onValueChange={(value) => updateRanking({ ...config.ranking, secondary_sort: value as SortField })}
                  disabled={!hasWriteAccess}
                >
                  <SelectTrigger>
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    {Object.entries(SORT_FIELD_LABELS).map(([value, label]) => (
                      <SelectItem key={value} value={value}>
                        {label}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
                <p className="text-xs text-muted-foreground">
                  Used when primary sort values are equal.
                </p>
              </div>

              <div className="space-y-2">
                <Label>Tertiary Sort</Label>
                <Select
                  value={config.ranking.tertiary_sort}
                  onValueChange={(value) => updateRanking({ ...config.ranking, tertiary_sort: value as SortField })}
                  disabled={!hasWriteAccess}
                >
                  <SelectTrigger>
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    {Object.entries(SORT_FIELD_LABELS).map(([value, label]) => (
                      <SelectItem key={value} value={value}>
                        {label}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
                <p className="text-xs text-muted-foreground">
                  Final tie-breaker for results with equal primary and secondary values.
                </p>
              </div>
            </div>
          </TabsContent>
        </Tabs>
      </CardContent>

      <CardFooter className="flex justify-between border-t pt-6">
        <Button
          variant="outline"
          onClick={handleRebuildIndex}
          disabled={isRebuilding || !hasWriteAccess}
        >
          {isRebuilding ? (
            <Loader2 className="mr-2 h-4 w-4 animate-spin" />
          ) : (
            <RefreshCw className="mr-2 h-4 w-4" />
          )}
          Rebuild Search Index
        </Button>

        <Button
          onClick={handleSave}
          disabled={isSaving || !hasWriteAccess || !hasChanges}
        >
          {isSaving ? (
            <Loader2 className="mr-2 h-4 w-4 animate-spin" />
          ) : (
            <Save className="mr-2 h-4 w-4" />
          )}
          Save Configuration
        </Button>
      </CardFooter>
    </Card>
  );
}

