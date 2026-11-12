import React, { useState, useEffect } from 'react';
import { useTranslation } from 'react-i18next';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Switch } from '@/components/ui/switch';
import { Button } from '@/components/ui/button';
import { Textarea } from '@/components/ui/textarea';
import { Separator } from '@/components/ui/separator';
import { Loader2, Save, Settings } from 'lucide-react';
import { SettingsFormSkeleton } from '@/components/common/list-view-skeleton';
import { usePermissions } from '@/stores/permissions-store';
import { FeatureAccessLevel } from '@/types/settings';
import { useToast } from '@/hooks/use-toast';

interface AppSettings {
  databricksCatalog: string;
  databricksSchema: string;
  databricksVolume: string;
  appAuditLogDir: string;
  llmEnabled: boolean;
  llmEndpoint: string;
  llmSystemPrompt: string;
  llmDisclaimerText: string;
  allowJobEnablementRequests: boolean;
  schemaImportChildLimit: number;
  instanceId: string;
  instanceName: string;
  instanceIdDefault: string;
  instanceNameDefault: string;
}

// Mirrors the backend rule for ONTOS_INSTANCE_ID (settings_manager.INSTANCE_ID_PATTERN)
const INSTANCE_ID_PATTERN = /^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$/;
const INSTANCE_NAME_MAX_LENGTH = 128;
// Mirrors the backend rule: no control characters (code point < 32) in the name
const hasControlChars = (value: string) => Array.from(value).some((c) => c.charCodeAt(0) < 32);

// Backend error codes (CodedValueError) -> the same i18n keys as the inline validation
const SERVER_ERROR_KEYS: Record<string, string> = {
  instance_id_invalid: 'settings:general.instanceIdentity.id.invalid',
  instance_name_invalid: 'settings:general.instanceIdentity.name.invalid',
};

export default function GeneralSettings() {
  const { t } = useTranslation(['settings', 'common']);
  const { hasPermission } = usePermissions();
  const { toast } = useToast();

  const hasWriteAccess = hasPermission('settings-general', FeatureAccessLevel.READ_WRITE);

  const [settings, setSettings] = useState<AppSettings>({
    databricksCatalog: '',
    databricksSchema: '',
    databricksVolume: '',
    appAuditLogDir: '',
    llmEnabled: false,
    llmEndpoint: '',
    llmSystemPrompt: '',
    llmDisclaimerText: '',
    allowJobEnablementRequests: false,
    schemaImportChildLimit: 500,
    instanceId: '',
    instanceName: '',
    instanceIdDefault: '',
    instanceNameDefault: '',
  });
  const [isLoading, setIsLoading] = useState(false);
  const [isSaving, setIsSaving] = useState(false);

  useEffect(() => {
    const fetchSettings = async () => {
      setIsLoading(true);
      try {
        const response = await fetch('/api/settings');
        if (response.ok) {
          const data = await response.json();
          setSettings({
            databricksCatalog: data.databricks_catalog || '',
            databricksSchema: data.databricks_schema || '',
            databricksVolume: data.databricks_volume || '',
            appAuditLogDir: data.app_audit_log_dir || '',
            llmEnabled: data.llm_enabled || false,
            llmEndpoint: data.llm_endpoint || '',
            llmSystemPrompt: data.llm_system_prompt || '',
            llmDisclaimerText: data.llm_disclaimer_text || '',
            allowJobEnablementRequests: data.allow_job_enablement_requests || false,
            schemaImportChildLimit: data.schema_import_child_limit ?? 500,
            instanceId: data.ontos_instance_id || '',
            instanceName: data.ontos_instance_name || '',
            instanceIdDefault: data.ontos_instance_id_default || '',
            instanceNameDefault: data.ontos_instance_name_default || '',
          });
        }
      } catch (error) {
        console.error('Failed to fetch settings:', error);
      } finally {
        setIsLoading(false);
      }
    };
    fetchSettings();
  }, []);

  const instanceId = settings.instanceId.trim();
  const instanceName = settings.instanceName.trim();
  const instanceIdError =
    instanceId !== '' && !INSTANCE_ID_PATTERN.test(instanceId)
      ? t(
          'settings:general.instanceIdentity.id.invalid',
          'Use 1-128 letters, digits, ".", "_", ":" or "-", starting with a letter or digit.'
        )
      : null;
  const instanceNameError =
    instanceName.length > INSTANCE_NAME_MAX_LENGTH || hasControlChars(instanceName)
      ? t('settings:general.instanceIdentity.name.invalid', 'Use at most 128 characters, without control characters.')
      : null;

  const handleSave = async () => {
    if (instanceIdError || instanceNameError) {
      toast({
        title: t('settings:general.messages.saveError', 'Failed to save settings'),
        variant: 'destructive',
      });
      return;
    }
    setIsSaving(true);
    try {
      const response = await fetch('/api/settings', {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          databricks_catalog: settings.databricksCatalog,
          databricks_schema: settings.databricksSchema,
          databricks_volume: settings.databricksVolume,
          app_audit_log_dir: settings.appAuditLogDir,
          llm_enabled: settings.llmEnabled,
          llm_endpoint: settings.llmEndpoint,
          llm_system_prompt: settings.llmSystemPrompt,
          llm_disclaimer_text: settings.llmDisclaimerText,
          allow_job_enablement_requests: settings.allowJobEnablementRequests,
          schema_import_child_limit: settings.schemaImportChildLimit,
          // A value equal to the default (or blank) clears the override, so an untouched
          // field never pins the derived default.
          ontos_instance_id: instanceId === settings.instanceIdDefault ? '' : instanceId,
          ontos_instance_name: instanceName === settings.instanceNameDefault ? '' : instanceName,
        }),
      });
      if (response.ok) {
        toast({
          title: t('settings:general.messages.saveSuccess', 'Settings saved successfully'),
        });
      } else {
        // Structured error ({code, message, params}): show it translated when we know the code.
        const body = await response.json().catch(() => null);
        const code = body?.detail && typeof body.detail === 'object' ? body.detail.code : null;
        const translationKey = code ? SERVER_ERROR_KEYS[code] : undefined;
        if (translationKey) {
          toast({
            title: t('settings:general.messages.saveError', 'Failed to save settings'),
            description: String(
              t(translationKey, { ...(body.detail.params ?? {}), defaultValue: body.detail.message })
            ),
            variant: 'destructive',
          });
          return;
        }
        throw new Error('Failed to save settings');
      }
    } catch (error) {
      toast({
        title: t('settings:general.messages.saveError', 'Failed to save settings'),
        variant: 'destructive',
      });
    } finally {
      setIsSaving(false);
    }
  };

  const handleChange = (e: React.ChangeEvent<HTMLInputElement | HTMLTextAreaElement>) => {
    const { name, value } = e.target;
    setSettings(prev => ({ ...prev, [name]: value }));
  };

  if (isLoading) {
    return (
      <>
        <div className="mb-6">
          <h1 className="text-3xl font-bold flex items-center gap-2">
            <Settings className="w-8 h-8" />
            {t('settings:general.title')}
          </h1>
          <p className="text-muted-foreground mt-1">{t('settings:general.description')}</p>
        </div>
        <SettingsFormSkeleton sections={3} fieldsPerSection={3} showTitle={false} />
      </>
    );
  }

  return (
    <>
      <div className="mb-6">
        <h1 className="text-3xl font-bold flex items-center gap-2">
          <Settings className="w-8 h-8" />
          {t('settings:general.title')}
        </h1>
        <p className="text-muted-foreground mt-1">{t('settings:general.description')}</p>
      </div>

      <div className="space-y-6">
        {/* Unity Catalog Settings */}
        <div>
          <h3 className="text-lg font-medium mb-3">{t('settings:general.unityCatalog.title', 'Unity Catalog')}</h3>
          <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
            <div className="space-y-2">
              <Label htmlFor="databricksCatalog">
                {t('settings:general.unityCatalog.catalog.label', 'Catalog')}
              </Label>
              <Input
                id="databricksCatalog"
                name="databricksCatalog"
                value={settings.databricksCatalog}
                onChange={handleChange}
                placeholder={t('settings:general.unityCatalog.catalog.placeholder', 'app_data')}
                disabled={!hasWriteAccess || isLoading}
              />
            </div>
            <div className="space-y-2">
              <Label htmlFor="databricksSchema">
                {t('settings:general.unityCatalog.schema.label', 'Schema')}
              </Label>
              <Input
                id="databricksSchema"
                name="databricksSchema"
                value={settings.databricksSchema}
                onChange={handleChange}
                placeholder={t('settings:general.unityCatalog.schema.placeholder', 'app_ontos')}
                disabled={!hasWriteAccess || isLoading}
              />
            </div>
            <div className="space-y-2">
              <Label htmlFor="databricksVolume">
                {t('settings:general.unityCatalog.volume.label', 'Volume')}
              </Label>
              <Input
                id="databricksVolume"
                name="databricksVolume"
                value={settings.databricksVolume}
                onChange={handleChange}
                placeholder={t('settings:general.unityCatalog.volume.placeholder', 'app_files')}
                disabled={!hasWriteAccess || isLoading}
              />
            </div>
          </div>
          <p className="text-sm text-muted-foreground mt-2">
            {t('settings:general.unityCatalog.help', 'Unity Catalog location for storing application data.')}
          </p>
        </div>

        <Separator />

        {/* Instance Identity */}
        <div>
          <h3 className="text-lg font-medium mb-3">
            {t('settings:general.instanceIdentity.title', 'Instance Identity')}
          </h3>
          <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
            <div className="space-y-2">
              <Label htmlFor="instanceId">
                {t('settings:general.instanceIdentity.id.label', 'Instance ID')}
              </Label>
              <Input
                id="instanceId"
                name="instanceId"
                value={settings.instanceId}
                onChange={handleChange}
                placeholder={settings.instanceIdDefault}
                disabled={!hasWriteAccess || isLoading}
                aria-invalid={!!instanceIdError}
              />
              {instanceIdError && <p className="text-sm text-destructive">{instanceIdError}</p>}
              <p className="text-sm text-muted-foreground">
                {t(
                  'settings:general.instanceIdentity.id.help',
                  'Stable identifier of this Ontos instance, stamped on exported entities. Default: {{default}}. Clear the field to restore the default.',
                  { default: settings.instanceIdDefault }
                )}
              </p>
            </div>
            <div className="space-y-2">
              <Label htmlFor="instanceName">
                {t('settings:general.instanceIdentity.name.label', 'Instance Name')}
              </Label>
              <Input
                id="instanceName"
                name="instanceName"
                value={settings.instanceName}
                onChange={handleChange}
                placeholder={settings.instanceNameDefault}
                disabled={!hasWriteAccess || isLoading}
                aria-invalid={!!instanceNameError}
              />
              {instanceNameError && <p className="text-sm text-destructive">{instanceNameError}</p>}
              <p className="text-sm text-muted-foreground">
                {t(
                  'settings:general.instanceIdentity.name.help',
                  'Human-readable name of this instance. Default: {{default}}. Clear the field to restore the default.',
                  { default: settings.instanceNameDefault }
                )}
              </p>
            </div>
          </div>
        </div>

        <Separator />

        {/* Audit Log Settings */}
        <div className="space-y-2">
          <Label htmlFor="appAuditLogDir">
            {t('settings:general.auditLog.label', 'Audit Log Directory')}
          </Label>
          <Input
            id="appAuditLogDir"
            name="appAuditLogDir"
            value={settings.appAuditLogDir}
            onChange={handleChange}
            placeholder={t('settings:general.auditLog.placeholder', 'audit_logs')}
            disabled={!hasWriteAccess || isLoading}
          />
          <p className="text-sm text-muted-foreground">
            {t('settings:general.auditLog.help', 'Directory where audit log files are stored.')}
          </p>
        </div>

        <Separator />

        {/* Background Job Settings */}
        <div>
          <h3 className="text-lg font-medium mb-3">
            {t('settings:general.backgroundJobs.title', 'Background Jobs')}
          </h3>

          <div className="space-y-2">
            <div className="flex items-center space-x-2">
              <Switch
                id="allowJobEnablementRequests"
                checked={settings.allowJobEnablementRequests}
                onCheckedChange={(checked) => setSettings(prev => ({ ...prev, allowJobEnablementRequests: checked }))}
                disabled={!hasWriteAccess || isLoading}
              />
              <Label htmlFor="allowJobEnablementRequests">
                {t('settings:general.backgroundJobs.allowEnablementRequests.label', 'Allow users to request background job enablement')}
              </Label>
            </div>
            <p className="text-sm text-muted-foreground">
              {t(
                'settings:general.backgroundJobs.allowEnablementRequests.help',
                'When a user hits a feature whose background job is not enabled, they can send a notification asking an administrator to enable it.'
              )}
            </p>
          </div>
        </div>

        <Separator />

        {/* Schema Importer Settings */}
        <div>
          <h3 className="text-lg font-medium mb-3">
            {t('settings:general.schemaImporter.title', 'Schema Importer')}
          </h3>
          <div className="space-y-2 max-w-xs">
            <Label htmlFor="schemaImportChildLimit">
              {t('settings:general.schemaImporter.childLimit.label', 'Max objects fetched per level')}
            </Label>
            <Input
              id="schemaImportChildLimit"
              name="schemaImportChildLimit"
              type="number"
              min={1}
              max={10000}
              value={settings.schemaImportChildLimit}
              onChange={(e) =>
                setSettings(prev => ({
                  ...prev,
                  schemaImportChildLimit: e.target.value === '' ? 0 : parseInt(e.target.value, 10),
                }))
              }
              disabled={!hasWriteAccess || isLoading}
            />
            <p className="text-sm text-muted-foreground">
              {t(
                'settings:general.schemaImporter.childLimit.help',
                'Maximum number of tables/views/objects the importer fetches per catalog or schema when browsing (1–10000). Raise this for large estates; there is no pagination beyond this cap.'
              )}
            </p>
          </div>
        </div>

        <Separator />

        {/* LLM Settings */}
        <div>
          <h3 className="text-lg font-medium mb-3">{t('settings:general.llm.title', 'AI / LLM Configuration')}</h3>

          <div className="space-y-4">
            <div className="flex items-center space-x-2">
              <Switch
                id="llmEnabled"
                checked={settings.llmEnabled}
                onCheckedChange={(checked) => setSettings(prev => ({ ...prev, llmEnabled: checked }))}
                disabled={!hasWriteAccess || isLoading}
              />
              <Label htmlFor="llmEnabled">{t('settings:general.llm.enabled.label', 'Enable AI Features')}</Label>
            </div>

            <div className="space-y-2">
              <Label htmlFor="llmEndpoint">
                {t('settings:general.llm.endpoint.label', 'LLM Endpoint')}
              </Label>
              <Input
                id="llmEndpoint"
                name="llmEndpoint"
                value={settings.llmEndpoint}
                onChange={handleChange}
                placeholder={t('settings:general.llm.endpoint.placeholder', 'databricks-claude-sonnet-4-5')}
                disabled={!hasWriteAccess || isLoading || !settings.llmEnabled}
              />
              <p className="text-sm text-muted-foreground">
                {t('settings:general.llm.endpoint.help', 'Databricks serving endpoint name for the LLM.')}
              </p>
            </div>

            <div className="space-y-2">
              <Label htmlFor="llmSystemPrompt">
                {t('settings:general.llm.systemPrompt.label', 'System Prompt')}
              </Label>
              <Textarea
                id="llmSystemPrompt"
                name="llmSystemPrompt"
                value={settings.llmSystemPrompt}
                onChange={handleChange}
                placeholder={t('settings:general.llm.systemPrompt.placeholder', 'You are a Data Steward...')}
                disabled={!hasWriteAccess || isLoading || !settings.llmEnabled}
                rows={4}
              />
              <p className="text-sm text-muted-foreground">
                {t('settings:general.llm.systemPrompt.help', 'System prompt that defines the AI assistant behavior.')}
              </p>
            </div>

            <div className="space-y-2">
              <Label htmlFor="llmDisclaimerText">
                {t('settings:general.llm.disclaimer.label', 'Disclaimer Text')}
              </Label>
              <Textarea
                id="llmDisclaimerText"
                name="llmDisclaimerText"
                value={settings.llmDisclaimerText}
                onChange={handleChange}
                placeholder={t('settings:general.llm.disclaimer.placeholder', 'This feature uses AI to analyze data assets...')}
                disabled={!hasWriteAccess || isLoading || !settings.llmEnabled}
                rows={3}
              />
              <p className="text-sm text-muted-foreground">
                {t('settings:general.llm.disclaimer.help', 'Disclaimer shown to users when using AI features.')}
              </p>
            </div>
          </div>
        </div>

        {hasWriteAccess && (
          <div className="pt-4">
            <Button onClick={handleSave} disabled={isSaving}>
              {isSaving ? (
                <Loader2 className="mr-2 h-4 w-4 animate-spin" />
              ) : (
                <Save className="mr-2 h-4 w-4" />
              )}
              {t('settings:general.saveButton', 'Save Settings')}
            </Button>
          </div>
        )}
      </div>
    </>
  );
}
