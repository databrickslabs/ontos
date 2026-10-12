import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import type { TFunction } from 'i18next';
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Switch } from '@/components/ui/switch';
import { Alert, AlertDescription } from '@/components/ui/alert';
import { Badge } from '@/components/ui/badge';
import { Info, AlertCircle } from 'lucide-react';
import { TagSyncConfig } from '@/types/workflow-configurations';

interface TagSyncConfigsFieldProps {
  value: TagSyncConfig[];
  onChange: (configs: TagSyncConfig[]) => void;
  entityTypes: string[];
}

// Available variables for each entity type
const AVAILABLE_VARIABLES: Record<string, { key: string; description: string }[]> = {
  semantic_assignment: [
    { key: '{LINK.IRI}', description: 'Full IRI of the semantic link' },
    { key: '{LINK.LABEL}', description: 'Label of the semantic link' },
    { key: '{LINK.SLUG}', description: 'Slugified IRI (e.g., "customer")' },
  ],
  data_domain: [
    { key: '{DOMAIN.ID}', description: 'Domain UUID' },
    { key: '{DOMAIN.NAME}', description: 'Domain name' },
  ],
  data_contract: [
    { key: '{CONTRACT.ID}', description: 'Contract UUID' },
    { key: '{CONTRACT.NAME}', description: 'Contract name' },
    { key: '{CONTRACT.VERSION}', description: 'Contract version' },
    { key: '{CONTRACT.STATUS}', description: 'Contract status' },
  ],
  data_product: [
    { key: '{PRODUCT.ID}', description: 'Product UUID' },
    { key: '{PRODUCT.NAME}', description: 'Product name' },
    { key: '{PRODUCT.VERSION}', description: 'Product version' },
    { key: '{PRODUCT.STATUS}', description: 'Product status' },
  ],
};

// UC tag key validation
const INVALID_TAG_CHARS = [',', '.', ':', '-', '/', '`', '='];

function validateTagKey(key: string, t: TFunction): string | null {
  if (!key.trim()) {
    return t('settings:tags.syncConfigs.errors.empty');
  }
  if (key !== key.trim()) {
    return t('settings:tags.syncConfigs.errors.spaces');
  }
  for (const char of INVALID_TAG_CHARS) {
    if (key.includes(char)) {
      return t('settings:tags.syncConfigs.errors.invalidChar', { char });
    }
  }
  return null;
}

export default function TagSyncConfigsField({ value, onChange, entityTypes }: TagSyncConfigsFieldProps) {
  const { t } = useTranslation(['settings', 'common']);
  const [activeTab, setActiveTab] = useState<string>(entityTypes[0] || 'semantic_assignment');

  // User-facing descriptions for the available template variables
  const variableDescriptions: Record<string, string> = {
    '{LINK.IRI}': t('settings:tags.syncConfigs.variables.linkIri'),
    '{LINK.LABEL}': t('settings:tags.syncConfigs.variables.linkLabel'),
    '{LINK.SLUG}': t('settings:tags.syncConfigs.variables.linkSlug'),
    '{DOMAIN.ID}': t('settings:tags.syncConfigs.variables.domainId'),
    '{DOMAIN.NAME}': t('settings:tags.syncConfigs.variables.domainName'),
    '{CONTRACT.ID}': t('settings:tags.syncConfigs.variables.contractId'),
    '{CONTRACT.NAME}': t('settings:tags.syncConfigs.variables.contractName'),
    '{CONTRACT.VERSION}': t('settings:tags.syncConfigs.variables.contractVersion'),
    '{CONTRACT.STATUS}': t('settings:tags.syncConfigs.variables.contractStatus'),
    '{PRODUCT.ID}': t('settings:tags.syncConfigs.variables.productId'),
    '{PRODUCT.NAME}': t('settings:tags.syncConfigs.variables.productName'),
    '{PRODUCT.VERSION}': t('settings:tags.syncConfigs.variables.productVersion'),
    '{PRODUCT.STATUS}': t('settings:tags.syncConfigs.variables.productStatus'),
  };

  // Ensure we have a config for each entity type
  const getConfigForType = (entityType: string): TagSyncConfig => {
    const existing = value.find(c => c.entity_type === entityType);
    if (existing) return existing;

    // Return default config based on entity type
    const defaults: Record<string, { key: string; value: string }> = {
      semantic_assignment: {
        key: 'ontos_semantic_{LINK.SLUG}',
        value: '{LINK.IRI}',
      },
      data_domain: {
        key: 'ontos_data_domain_name',
        value: '{DOMAIN.NAME}',
      },
      data_contract: {
        key: 'ontos_contract_name',
        value: '{CONTRACT.NAME}',
      },
      data_product: {
        key: 'ontos_product_name',
        value: '{PRODUCT.NAME}',
      },
    };

    const def = defaults[entityType] || { key: '', value: '' };
    return {
      entity_type: entityType as TagSyncConfig['entity_type'],
      enabled: true,
      tag_key_format: def.key,
      tag_value_format: def.value,
    };
  };

  const updateConfig = (entityType: string, updates: Partial<TagSyncConfig>) => {
    const newConfigs = [...value];
    const index = newConfigs.findIndex(c => c.entity_type === entityType);

    if (index >= 0) {
      newConfigs[index] = { ...newConfigs[index], ...updates };
    } else {
      newConfigs.push({ ...getConfigForType(entityType), ...updates });
    }

    onChange(newConfigs);
  };

  // Render example tag key with current format
  const renderExampleKey = (config: TagSyncConfig): string => {
    let example = config.tag_key_format;
    const variables = AVAILABLE_VARIABLES[config.entity_type] || [];

    // Replace variables with example values
    for (const variable of variables) {
      const exampleValues: Record<string, string> = {
        '{LINK.IRI}': 'https://example.com/terms/customer',
        '{LINK.LABEL}': 'Customer',
        '{LINK.SLUG}': 'customer',
        '{DOMAIN.ID}': '123e4567-e89b-12d3-a456-426614174000',
        '{DOMAIN.NAME}': 'sales',
        '{CONTRACT.ID}': '123e4567-e89b-12d3-a456-426614174001',
        '{CONTRACT.NAME}': 'customer_contract',
        '{CONTRACT.VERSION}': '1.0.0',
        '{CONTRACT.STATUS}': 'active',
        '{PRODUCT.ID}': '123e4567-e89b-12d3-a456-426614174002',
        '{PRODUCT.NAME}': 'customer_product',
        '{PRODUCT.VERSION}': '1.0.0',
        '{PRODUCT.STATUS}': 'active',
      };
      example = example.replace(variable.key, exampleValues[variable.key] || '?');
    }

    return example;
  };

  const formatEntityTypeName = (type: string): string => {
    return type.split('_').map(word => word.charAt(0).toUpperCase() + word.slice(1)).join(' ');
  };

  return (
    <div className="space-y-4">
      <Alert>
        <Info className="h-4 w-4" />
        <AlertDescription>
          {t('settings:tags.syncConfigs.introBefore')}{' '}
          <code className="text-xs bg-muted px-1 py-0.5 rounded">{'{'} {'}'}</code>{' '}
          {t('settings:tags.syncConfigs.introAfter')}
        </AlertDescription>
      </Alert>

      <Alert variant="destructive" className="bg-yellow-50 dark:bg-yellow-950 border-yellow-200 dark:border-yellow-800">
        <AlertCircle className="h-4 w-4 text-yellow-600 dark:text-yellow-400" />
        <AlertDescription className="text-yellow-800 dark:text-yellow-200">
          {t('settings:tags.syncConfigs.invalidCharsBefore')} <code className="text-xs bg-yellow-100 dark:bg-yellow-900 px-1 py-0.5 rounded">
            {INVALID_TAG_CHARS.join(' ')}
          </code> {t('settings:tags.syncConfigs.invalidCharsAfter')}
        </AlertDescription>
      </Alert>

      <Tabs value={activeTab} onValueChange={setActiveTab}>
        <TabsList className="grid w-full" style={{ gridTemplateColumns: `repeat(${entityTypes.length}, 1fr)` }}>
          {entityTypes.map(type => (
            <TabsTrigger key={type} value={type} className="text-xs">
              {formatEntityTypeName(type)}
            </TabsTrigger>
          ))}
        </TabsList>

        {entityTypes.map(entityType => {
          const config = getConfigForType(entityType);
          const variables = AVAILABLE_VARIABLES[entityType] || [];
          const keyValidation = config.tag_key_format ? validateTagKey(renderExampleKey(config), t) : null;

          return (
            <TabsContent key={entityType} value={entityType}>
              <Card>
                <CardHeader>
                  <CardTitle className="flex items-center justify-between">
                    <span>{formatEntityTypeName(entityType)}</span>
                    <div className="flex items-center gap-2">
                      <Label htmlFor={`${entityType}-enabled`}>{t('settings:tags.enable')}</Label>
                      <Switch
                        id={`${entityType}-enabled`}
                        checked={config.enabled}
                        onCheckedChange={(enabled) => updateConfig(entityType, { enabled })}
                      />
                    </div>
                  </CardTitle>
                  <CardDescription>
                    {t('settings:tags.syncConfigs.cardDescription', { type: formatEntityTypeName(entityType).toLowerCase() })}
                  </CardDescription>
                </CardHeader>
                <CardContent className="space-y-4">
                  {/* Available Variables */}
                  <div className="space-y-2">
                    <Label className="text-sm font-medium">{t('settings:tags.syncConfigs.availableVariables')}</Label>
                    <div className="flex flex-wrap gap-2">
                      {variables.map(variable => (
                        <Badge key={variable.key} variant="secondary" className="text-xs font-mono">
                          {variable.key}
                        </Badge>
                      ))}
                    </div>
                    <div className="text-xs text-muted-foreground space-y-1">
                      {variables.map(variable => (
                        <div key={variable.key}>
                          <code className="bg-muted px-1 py-0.5 rounded">{variable.key}</code> - {variableDescriptions[variable.key] ?? variable.description}
                        </div>
                      ))}
                    </div>
                  </div>

                  {/* Tag Key Format */}
                  <div className="space-y-2">
                    <Label htmlFor={`${entityType}-key-format`}>
                      {t('settings:tags.syncConfigs.keyFormatLabel')}
                      <span className="text-red-500 ml-1">*</span>
                    </Label>
                    <Input
                      id={`${entityType}-key-format`}
                      value={config.tag_key_format}
                      onChange={(e) => updateConfig(entityType, { tag_key_format: e.target.value })}
                      placeholder={t('settings:tags.syncConfigs.keyFormatPlaceholder')}
                      className="font-mono text-sm"
                      disabled={!config.enabled}
                    />
                    {config.enabled && config.tag_key_format && (
                      <div className="text-xs space-y-1">
                        <div className="text-muted-foreground">
                          {t('settings:tags.syncConfigs.example')} <code className="bg-muted px-1 py-0.5 rounded">{renderExampleKey(config)}</code>
                        </div>
                        {keyValidation && (
                          <div className="text-red-500 flex items-center gap-1">
                            <AlertCircle className="h-3 w-3" />
                            {keyValidation}
                          </div>
                        )}
                      </div>
                    )}
                  </div>

                  {/* Tag Value Format */}
                  <div className="space-y-2">
                    <Label htmlFor={`${entityType}-value-format`}>
                      {t('settings:tags.syncConfigs.valueFormatLabel')}
                      <span className="text-red-500 ml-1">*</span>
                    </Label>
                    <Input
                      id={`${entityType}-value-format`}
                      value={config.tag_value_format}
                      onChange={(e) => updateConfig(entityType, { tag_value_format: e.target.value })}
                      placeholder={t('settings:tags.syncConfigs.valueFormatPlaceholder')}
                      className="font-mono text-sm"
                      disabled={!config.enabled}
                    />
                    <p className="text-xs text-muted-foreground">
                      {t('settings:tags.syncConfigs.valueFormatHelp')}
                    </p>
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
