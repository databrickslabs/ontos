import React, { useState, useEffect } from 'react';
import { useTranslation } from 'react-i18next';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Switch } from '@/components/ui/switch';
import { Button } from '@/components/ui/button';
import { Textarea } from '@/components/ui/textarea';
import { Separator } from '@/components/ui/separator';
import { Loader2, Save, Settings } from 'lucide-react';
import { usePermissions } from '@/stores/permissions-store';
import { FeatureAccessLevel } from '@/types/settings';
import { useToast } from '@/hooks/use-toast';

interface AppSettings {
  enableBackgroundJobs: boolean;
  workspaceDeploymentPath: string;
  databricksCatalog: string;
  databricksSchema: string;
  databricksVolume: string;
  appAuditLogDir: string;
  llmEnabled: boolean;
  llmEndpoint: string;
  llmSystemPrompt: string;
  llmDisclaimerText: string;
}

export default function GeneralSettings() {
  const { t } = useTranslation(['settings', 'common']);
  const { hasPermission } = usePermissions();
  const { toast } = useToast();

  const hasWriteAccess = hasPermission('settings', FeatureAccessLevel.READ_WRITE);

  const [settings, setSettings] = useState<AppSettings>({
    enableBackgroundJobs: false,
    workspaceDeploymentPath: '',
    databricksCatalog: '',
    databricksSchema: '',
    databricksVolume: '',
    appAuditLogDir: '',
    llmEnabled: false,
    llmEndpoint: '',
    llmSystemPrompt: '',
    llmDisclaimerText: '',
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
            enableBackgroundJobs: data.enable_background_jobs || false,
            workspaceDeploymentPath: data.workspace_deployment_path || '',
            databricksCatalog: data.databricks_catalog || '',
            databricksSchema: data.databricks_schema || '',
            databricksVolume: data.databricks_volume || '',
            appAuditLogDir: data.app_audit_log_dir || '',
            llmEnabled: data.llm_enabled || false,
            llmEndpoint: data.llm_endpoint || '',
            llmSystemPrompt: data.llm_system_prompt || '',
            llmDisclaimerText: data.llm_disclaimer_text || '',
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

  const handleSave = async () => {
    setIsSaving(true);
    try {
      const response = await fetch('/api/settings', {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          enable_background_jobs: settings.enableBackgroundJobs,
          workspace_deployment_path: settings.workspaceDeploymentPath,
          databricks_catalog: settings.databricksCatalog,
          databricks_schema: settings.databricksSchema,
          databricks_volume: settings.databricksVolume,
          app_audit_log_dir: settings.appAuditLogDir,
          llm_enabled: settings.llmEnabled,
          llm_endpoint: settings.llmEndpoint,
          llm_system_prompt: settings.llmSystemPrompt,
          llm_disclaimer_text: settings.llmDisclaimerText,
        }),
      });
      if (response.ok) {
        toast({
          title: t('settings:general.messages.saveSuccess', 'Settings saved successfully'),
        });
      } else {
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
        {/* Background Jobs */}
        <div className="flex items-center space-x-2">
          <Switch
            id="background-jobs"
            checked={settings.enableBackgroundJobs}
            onCheckedChange={(checked) => setSettings(prev => ({ ...prev, enableBackgroundJobs: checked }))}
          />
          <Label htmlFor="background-jobs">{t('settings:general.enableBackgroundJobs')}</Label>
        </div>

        <div className="space-y-2">
          <Label htmlFor="workspaceDeploymentPath">
            {t('settings:general.workspaceDeploymentPath.label', 'Workspace Deployment Path')}
          </Label>
          <Input
            id="workspaceDeploymentPath"
            name="workspaceDeploymentPath"
            value={settings.workspaceDeploymentPath}
            onChange={handleChange}
            placeholder={t('settings:general.workspaceDeploymentPath.placeholder', '/Workspace/Users/user@domain.com/ontos-workflows')}
            disabled={!hasWriteAccess || isLoading}
          />
          <p className="text-sm text-muted-foreground">
            {t('settings:general.workspaceDeploymentPath.help', 'Path in Databricks workspace where workflow files are deployed for background jobs.')}
          </p>
        </div>

        <Separator />

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
