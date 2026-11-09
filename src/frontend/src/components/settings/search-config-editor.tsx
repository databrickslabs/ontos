import { useState, useEffect, useCallback } from 'react';
import { useTranslation } from 'react-i18next';
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
import {
  CardSkeleton,
  SkeletonLine,
} from '@/components/common/list-view-skeleton';
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


// i18n key suffixes (under the `settings:` namespace); rendered via t(`settings:${key}`)
const MATCH_TYPE_LABEL_KEYS: Record<MatchType, string> = {
  [MatchType.PREFIX]: 'search.matchType.prefix',
  [MatchType.SUBSTRING]: 'search.matchType.substring',
  [MatchType.EXACT]: 'search.matchType.exact',
  [MatchType.FUZZY]: 'search.matchType.fuzzy',
};

const SORT_FIELD_LABEL_KEYS: Record<SortField, string> = {
  [SortField.MATCH_PRIORITY]: 'search.sortField.matchPriority',
  [SortField.BOOST_SCORE]: 'search.sortField.boostScore',
  [SortField.TITLE_ASC]: 'search.sortField.titleAsc',
  [SortField.TITLE_DESC]: 'search.sortField.titleDesc',
};

const ASSET_TYPE_DISPLAY_NAME_KEYS: Record<string, string> = {
  'data-product': 'search.assetType.dataProduct',
  'data-contract': 'search.assetType.dataContract',
  'glossary-term': 'search.assetType.glossaryTerm',
  'data-asset-review': 'search.assetType.dataAssetReview',
  'tag': 'search.assetType.tag',
  'data-domain': 'search.assetType.dataDomain',
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
  const { t } = useTranslation(['settings', 'common']);
  return (
    <div className="border rounded-lg p-4 space-y-4 bg-card">
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          <span className="font-medium capitalize">{fieldName}</span>
          {showSource && config.source && (
            <Badge variant="outline" className="text-xs">
              {t('settings:search.fieldEditor.sourceBadge', { source: config.source })}
            </Badge>
          )}
        </div>
        <div className="flex items-center gap-2">
          <Label htmlFor={`${fieldName}-indexed`} className="text-sm text-muted-foreground">
            {t('settings:search.fieldEditor.indexed')}
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
            <Label className="text-sm">{t('settings:search.fieldEditor.matchType')}</Label>
            <Select
              value={config.match_type}
              onValueChange={(value) => onChange({ ...config, match_type: value as MatchType })}
              disabled={disabled}
            >
              <SelectTrigger>
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {Object.entries(MATCH_TYPE_LABEL_KEYS).map(([value, labelKey]) => (
                  <SelectItem key={value} value={value}>
                    {t(`settings:${labelKey}`)}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>

          <div className="space-y-2">
            <Label className="text-sm">{t('settings:search.fieldEditor.priorityLabel')}</Label>
            <Input
              type="number"
              value={config.priority}
              onChange={(e) => onChange({ ...config, priority: Math.max(1, Math.min(100, parseInt(e.target.value) || 1)) })}
              min={1}
              max={100}
              disabled={disabled}
              className="w-24"
            />
            <p className="text-xs text-muted-foreground">{t('settings:search.fieldEditor.priorityHelp')}</p>
          </div>

          <div className="space-y-2">
            <Label className="text-sm">{t('settings:search.fieldEditor.boostLabel')}</Label>
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
            <p className="text-xs text-muted-foreground">{t('settings:search.fieldEditor.boostHelp')}</p>
          </div>
        </div>
      )}
    </div>
  );
}


export default function SearchConfigEditor() {
  const { t } = useTranslation(['settings', 'common']);
  const { toast } = useToast();
  const { hasPermission } = usePermissions();
  
  const hasWriteAccess = hasPermission('settings-search', FeatureAccessLevel.ADMIN);

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
        title: t('settings:search.messages.loadErrorTitle'),
        description: t('settings:search.messages.loadErrorDescription'),
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
        title: t('settings:search.messages.saveSuccessTitle'),
        description: t('settings:search.messages.saveSuccessDescription'),
      });
    } catch (error) {
      console.error('Error saving config:', error);
      toast({
        title: t('settings:search.messages.saveErrorTitle'),
        description: t('settings:search.messages.saveErrorDescription'),
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
        title: t('settings:search.messages.rebuildSuccessTitle'),
        description: t('settings:search.messages.rebuildSuccessDescription', { count: result.index_size }),
      });
    } catch (error) {
      console.error('Error rebuilding index:', error);
      toast({
        title: t('settings:search.messages.rebuildErrorTitle'),
        description: t('settings:search.messages.rebuildErrorDescription'),
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
    // Tab strip + 2 config sections
    return (
      <div className="space-y-6">
        <SkeletonLine height="h-10" width="w-96" />
        <CardSkeleton titleWidth="w-48" descriptionWidth="w-72" contentRows={5} />
        <CardSkeleton titleWidth="w-40" descriptionWidth="w-60" contentRows={4} />
      </div>
    );
  }

  if (!config) {
    return (
      <div className="py-8">
        <Alert variant="destructive">
          <AlertCircle className="h-4 w-4" />
          <AlertDescription>
            {t('settings:search.loadFailedAlert')}
          </AlertDescription>
        </Alert>
      </div>
    );
  }

  return (
    <>
      <div className="mb-6">
        <div className="flex items-center justify-between">
          <div>
            <h1 className="text-3xl font-bold flex items-center gap-2">
              <Search className="w-8 h-8" />
              {t('settings:search.title')}
            </h1>
            <p className="text-muted-foreground mt-1">
              {t('settings:search.description')}
            </p>
          </div>
          <Badge variant="outline">v{config.version}</Badge>
        </div>
      </div>

      <div className="space-y-6">
        {hasChanges && (
          <Alert>
            <AlertCircle className="h-4 w-4" />
            <AlertDescription>
              {t('settings:search.unsavedChanges')}
            </AlertDescription>
          </Alert>
        )}

        <Tabs defaultValue="defaults" className="space-y-4">
          <TabsList className="grid w-full grid-cols-3">
            <TabsTrigger value="defaults" className="flex items-center gap-2">
              <Settings2 className="h-4 w-4" />
              {t('settings:search.tabs.defaultFields')}
            </TabsTrigger>
            <TabsTrigger value="asset-types" className="flex items-center gap-2">
              <Layers className="h-4 w-4" />
              {t('settings:search.tabs.assetTypes')}
            </TabsTrigger>
            <TabsTrigger value="ranking" className="flex items-center gap-2">
              <ArrowUpDown className="h-4 w-4" />
              {t('settings:search.tabs.ranking')}
            </TabsTrigger>
          </TabsList>

          {/* Default Fields Tab */}
          <TabsContent value="defaults" className="space-y-4">
            <p className="text-sm text-muted-foreground">
              {t('settings:search.defaults.description')}
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
              {t('settings:search.assetTypesTab.description')}
            </p>

            <Accordion type="multiple" className="space-y-2">
              {Object.entries(config.asset_types).map(([assetType, assetConfig]) => (
                <AccordionItem key={assetType} value={assetType} className="border rounded-lg">
                  <AccordionTrigger className="px-4 hover:no-underline">
                    <div className="flex items-center gap-3">
                      <span className="font-medium">
                        {ASSET_TYPE_DISPLAY_NAME_KEYS[assetType] ? t(`settings:${ASSET_TYPE_DISPLAY_NAME_KEYS[assetType]}`) : assetType}
                      </span>
                      {assetConfig.enabled ? (
                        <Badge variant="default" className="text-xs">
                          <Check className="h-3 w-3 mr-1" />
                          {t('common:labels.enabled')}
                        </Badge>
                      ) : (
                        <Badge variant="secondary" className="text-xs">
                          {t('common:labels.disabled')}
                        </Badge>
                      )}
                      {Object.keys(assetConfig.extra_fields).length > 0 && (
                        <Badge variant="outline" className="text-xs">
                          {t('settings:search.assetTypesTab.extraFieldsBadge', { count: Object.keys(assetConfig.extra_fields).length })}
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
                        <Label htmlFor={`${assetType}-enabled`}>{t('settings:search.assetTypesTab.enableIndexing')}</Label>
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
                        <Label htmlFor={`${assetType}-inherit`}>{t('settings:search.assetTypesTab.inheritDefaults')}</Label>
                      </div>
                    </div>

                    {assetConfig.enabled && Object.keys(assetConfig.extra_fields).length > 0 && (
                      <>
                        <Separator />
                        <div className="space-y-2">
                          <h4 className="text-sm font-medium">{t('settings:search.assetTypesTab.extraFieldsTitle')}</h4>
                          <p className="text-xs text-muted-foreground">
                            {t('settings:search.assetTypesTab.extraFieldsDescription')}
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
              {t('settings:search.ranking.description')}
            </p>

            <div className="grid gap-4">
              <div className="space-y-2">
                <Label>{t('settings:search.ranking.primarySort')}</Label>
                <Select
                  value={config.ranking.primary_sort}
                  onValueChange={(value) => updateRanking({ ...config.ranking, primary_sort: value as SortField })}
                  disabled={!hasWriteAccess}
                >
                  <SelectTrigger>
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    {Object.entries(SORT_FIELD_LABEL_KEYS).map(([value, labelKey]) => (
                      <SelectItem key={value} value={value}>
                        {t(`settings:${labelKey}`)}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
                <p className="text-xs text-muted-foreground">
                  {t('settings:search.ranking.primarySortHelp')}
                </p>
              </div>

              <div className="space-y-2">
                <Label>{t('settings:search.ranking.secondarySort')}</Label>
                <Select
                  value={config.ranking.secondary_sort}
                  onValueChange={(value) => updateRanking({ ...config.ranking, secondary_sort: value as SortField })}
                  disabled={!hasWriteAccess}
                >
                  <SelectTrigger>
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    {Object.entries(SORT_FIELD_LABEL_KEYS).map(([value, labelKey]) => (
                      <SelectItem key={value} value={value}>
                        {t(`settings:${labelKey}`)}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
                <p className="text-xs text-muted-foreground">
                  {t('settings:search.ranking.secondarySortHelp')}
                </p>
              </div>

              <div className="space-y-2">
                <Label>{t('settings:search.ranking.tertiarySort')}</Label>
                <Select
                  value={config.ranking.tertiary_sort}
                  onValueChange={(value) => updateRanking({ ...config.ranking, tertiary_sort: value as SortField })}
                  disabled={!hasWriteAccess}
                >
                  <SelectTrigger>
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    {Object.entries(SORT_FIELD_LABEL_KEYS).map(([value, labelKey]) => (
                      <SelectItem key={value} value={value}>
                        {t(`settings:${labelKey}`)}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
                <p className="text-xs text-muted-foreground">
                  {t('settings:search.ranking.tertiarySortHelp')}
                </p>
              </div>
            </div>
          </TabsContent>
        </Tabs>
        <div className="flex justify-between pt-4">
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
            {t('settings:search.buttons.rebuildIndex')}
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
            {t('settings:search.buttons.save')}
          </Button>
        </div>
      </div>
    </>
  );
}

