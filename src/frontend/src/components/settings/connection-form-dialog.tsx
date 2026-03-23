import { useState, useEffect } from 'react';
import { useForm } from 'react-hook-form';
import { zodResolver } from '@hookform/resolvers/zod';
import * as z from 'zod';
import { Loader2, HeartPulse, Server } from 'lucide-react';
import { useTranslation } from 'react-i18next';

import { Button } from '@/components/ui/button';
import {
  Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle,
} from '@/components/ui/dialog';
import {
  Form, FormControl, FormField, FormItem, FormLabel, FormMessage, FormDescription,
} from '@/components/ui/form';
import { Input } from '@/components/ui/input';
import { Textarea } from '@/components/ui/textarea';
import { Switch } from '@/components/ui/switch';
import { Separator } from '@/components/ui/separator';
import {
  Select, SelectContent, SelectItem, SelectTrigger, SelectValue,
} from '@/components/ui/select';
import { useApi } from '@/hooks/use-api';
import { useToast } from '@/hooks/use-toast';
import { Connection, ConnectorTypeInfo } from '@/types/connections';

interface ConnectionFormDialogProps {
  isOpen: boolean;
  onOpenChange: (open: boolean) => void;
  initialConnection: Connection | null;
  onSubmitSuccess: () => void;
}

interface SystemAssetOption {
  id: string;
  name: string;
}

const formSchema = z.object({
  name: z.string().min(1, 'Name is required').max(200),
  connector_type: z.string().min(1, 'Connector type is required'),
  description: z.string().max(500).optional().nullable(),
  enabled: z.boolean(),
  is_default: z.boolean(),
  system_asset_id: z.string().optional().nullable(),
  // BigQuery config fields
  project_id: z.string().optional(),
  location: z.string().optional(),
  uc_connection_name: z.string().optional(),
  credentials_secret_scope: z.string().optional(),
  credentials_secret_key: z.string().optional(),
  credentials_path: z.string().optional(),
});

type FormValues = z.infer<typeof formSchema>;

const BQ_CONFIG_FIELDS = [
  'project_id', 'location', 'uc_connection_name',
  'credentials_secret_scope', 'credentials_secret_key', 'credentials_path',
] as const;

const SYSTEM_CREATED_BY = 'system';

export function ConnectionFormDialog({
  isOpen,
  onOpenChange,
  initialConnection,
  onSubmitSuccess,
}: ConnectionFormDialogProps) {
  const { t } = useTranslation(['settings', 'common']);
  const api = useApi();
  const { toast } = useToast();
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [isTesting, setIsTesting] = useState(false);
  const [connectorTypes, setConnectorTypes] = useState<ConnectorTypeInfo[]>([]);
  const [systemAssets, setSystemAssets] = useState<SystemAssetOption[]>([]);

  const isEditing = !!initialConnection;
  const isSystem = initialConnection?.created_by === SYSTEM_CREATED_BY;

  const form = useForm<FormValues>({
    resolver: zodResolver(formSchema),
    defaultValues: {
      name: '',
      connector_type: '',
      description: '',
      enabled: true,
      is_default: false,
      system_asset_id: null,
    },
  });

  const selectedType = form.watch('connector_type');

  // Fetch connector types and System assets on mount
  useEffect(() => {
    const fetchTypes = async () => {
      try {
        const response = await api.get<ConnectorTypeInfo[]>('/api/connections/types');
        if (response.data) {
          setConnectorTypes(response.data);
        }
      } catch {
        // ignore
      }
    };
    const fetchSystemAssets = async () => {
      try {
        const response = await api.get<{ items: SystemAssetOption[] }>('/api/assets?asset_type=System&limit=200');
        if (response.data?.items) {
          setSystemAssets(response.data.items);
        }
      } catch {
        // ignore
      }
    };
    fetchTypes();
    fetchSystemAssets();
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  // Reset form when dialog opens or initialConnection changes
  useEffect(() => {
    if (isOpen) {
      const cfg = initialConnection?.config || {};
      form.reset({
        name: initialConnection?.name || '',
        connector_type: initialConnection?.connector_type || '',
        description: initialConnection?.description || '',
        enabled: initialConnection?.enabled ?? true,
        is_default: initialConnection?.is_default ?? false,
        system_asset_id: initialConnection?.system_asset_id || null,
        project_id: cfg.project_id || '',
        location: cfg.location || '',
        uc_connection_name: cfg.uc_connection_name || '',
        credentials_secret_scope: cfg.credentials_secret_scope || '',
        credentials_secret_key: cfg.credentials_secret_key || '',
        credentials_path: cfg.credentials_path || '',
      });
    }
  }, [isOpen, initialConnection]); // eslint-disable-line react-hooks/exhaustive-deps

  const buildPayload = (values: FormValues) => {
    const config: Record<string, any> = {};
    if (values.connector_type === 'bigquery') {
      for (const f of BQ_CONFIG_FIELDS) {
        if (values[f]) config[f] = values[f];
      }
    }
    return {
      name: values.name,
      connector_type: values.connector_type,
      description: values.description || null,
      config,
      enabled: values.enabled,
      is_default: values.is_default,
      system_asset_id: values.system_asset_id || null,
    };
  };

  const onSubmit = async (values: FormValues) => {
    setIsSubmitting(true);
    try {
      const payload = buildPayload(values);
      let response;
      if (isEditing && initialConnection) {
        const { connector_type: _, ...updatePayload } = payload;
        response = await api.put(`/api/connections/${initialConnection.id}`, updatePayload);
      } else {
        response = await api.post('/api/connections', payload);
      }
      if (response.error) {
        toast({ title: 'Error', description: response.error, variant: 'destructive' });
      } else {
        toast({ title: t('settings:connectors.messages.saveSuccess', 'Connection saved') });
        onSubmitSuccess();
        onOpenChange(false);
      }
    } catch (e: any) {
      toast({ title: 'Error', description: e.message, variant: 'destructive' });
    } finally {
      setIsSubmitting(false);
    }
  };

  const handleTest = async () => {
    if (!initialConnection) return;
    setIsTesting(true);
    try {
      const response = await fetch(`/api/connections/${initialConnection.id}/test`, { method: 'POST' });
      const result = await response.json();
      if (result.healthy) {
        toast({
          title: t('settings:connectors.messages.testSuccess', 'Connection successful'),
          description: result.project ? `Project: ${result.project}` : undefined,
        });
      } else {
        toast({
          title: t('settings:connectors.messages.testFailed', 'Connection failed'),
          description: result.error || 'Unknown error',
          variant: 'destructive',
        });
      }
    } catch {
      toast({ title: t('settings:connectors.messages.testError', 'Test error'), variant: 'destructive' });
    } finally {
      setIsTesting(false);
    }
  };

  const availableTypes = connectorTypes.filter(ct =>
    ct.connector_type !== 'databricks'
  );

  return (
    <Dialog open={isOpen} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-[600px] max-h-[85vh] overflow-y-auto">
        <DialogHeader>
          <DialogTitle>
            {isEditing
              ? t('settings:connectors.editTitle', 'Edit Connection')
              : t('settings:connectors.createTitle', 'New Connection')}
          </DialogTitle>
          <DialogDescription>
            {isEditing
              ? t('settings:connectors.editDescription', 'Update connection settings.')
              : t('settings:connectors.createDescription', 'Configure a new connection to an external data platform.')}
          </DialogDescription>
        </DialogHeader>

        <Form {...form}>
          <form onSubmit={form.handleSubmit(onSubmit)} className="space-y-4">
            {/* Connector type (only on create) */}
            {!isEditing && (
              <FormField
                control={form.control}
                name="connector_type"
                render={({ field }) => (
                  <FormItem>
                    <FormLabel>{t('settings:connectors.form.connectorType', 'Connector Type')}</FormLabel>
                    <Select onValueChange={field.onChange} defaultValue={field.value}>
                      <FormControl>
                        <SelectTrigger>
                          <SelectValue placeholder="Select a connector type..." />
                        </SelectTrigger>
                      </FormControl>
                      <SelectContent>
                        {availableTypes.map(ct => (
                          <SelectItem key={ct.connector_type} value={ct.connector_type}>
                            {ct.display_name}
                          </SelectItem>
                        ))}
                      </SelectContent>
                    </Select>
                    <FormMessage />
                  </FormItem>
                )}
              />
            )}

            {/* Name */}
            <FormField
              control={form.control}
              name="name"
              render={({ field }) => (
                <FormItem>
                  <FormLabel>{t('settings:connectors.form.name', 'Name')}</FormLabel>
                  <FormControl>
                    <Input placeholder="e.g. Production BQ - Analytics" {...field} disabled={isSystem} />
                  </FormControl>
                  <FormMessage />
                </FormItem>
              )}
            />

            {/* Description */}
            <FormField
              control={form.control}
              name="description"
              render={({ field }) => (
                <FormItem>
                  <FormLabel>{t('settings:connectors.form.description', 'Description')}</FormLabel>
                  <FormControl>
                    <Textarea
                      placeholder="Optional description..."
                      rows={2}
                      {...field}
                      value={field.value || ''}
                      disabled={isSystem}
                    />
                  </FormControl>
                  <FormMessage />
                </FormItem>
              )}
            />

            {/* Enabled + Default toggles */}
            <div className="flex gap-6">
              <FormField
                control={form.control}
                name="enabled"
                render={({ field }) => (
                  <FormItem className="flex items-center gap-2">
                    <FormLabel className="mt-0">{t('settings:connectors.form.enabled', 'Enabled')}</FormLabel>
                    <FormControl>
                      <Switch checked={field.value} onCheckedChange={field.onChange} disabled={isSystem} />
                    </FormControl>
                  </FormItem>
                )}
              />
              <FormField
                control={form.control}
                name="is_default"
                render={({ field }) => (
                  <FormItem className="flex items-center gap-2">
                    <FormLabel className="mt-0">{t('settings:connectors.form.isDefault', 'Default')}</FormLabel>
                    <FormControl>
                      <Switch checked={field.value} onCheckedChange={field.onChange} disabled={isSystem} />
                    </FormControl>
                  </FormItem>
                )}
              />
            </div>

            {/* Linked System Asset */}
            <Separator />
            <FormField
              control={form.control}
              name="system_asset_id"
              render={({ field }) => (
                <FormItem>
                  <FormLabel className="flex items-center gap-1.5">
                    <Server className="h-3.5 w-3.5" />
                    {t('settings:connectors.form.systemAsset', 'Linked System Asset')}
                  </FormLabel>
                  <Select
                    onValueChange={(v) => field.onChange(v === '__none__' ? null : v)}
                    value={field.value || '__none__'}
                  >
                    <FormControl>
                      <SelectTrigger>
                        <SelectValue placeholder="Auto-create on first import" />
                      </SelectTrigger>
                    </FormControl>
                    <SelectContent>
                      <SelectItem value="__none__">
                        <span className="text-muted-foreground">Auto-create on first import</span>
                      </SelectItem>
                      {systemAssets.map((sa) => (
                        <SelectItem key={sa.id} value={sa.id}>
                          {sa.name}
                        </SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                  <FormDescription>
                    {t(
                      'settings:connectors.form.systemAssetHelp',
                      'Link to an existing System asset, or leave empty to auto-create one on the first import.',
                    )}
                  </FormDescription>
                  <FormMessage />
                </FormItem>
              )}
            />

            {/* BigQuery-specific config */}
            {selectedType === 'bigquery' && (
              <>
                <Separator />
                <p className="text-sm font-medium">
                  {t('settings:connectors.bigquery.configTitle', 'BigQuery Configuration')}
                </p>

                <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                  <FormField
                    control={form.control}
                    name="project_id"
                    render={({ field }) => (
                      <FormItem>
                        <FormLabel>{t('settings:connectors.bigquery.projectId', 'GCP Project ID')}</FormLabel>
                        <FormControl>
                          <Input placeholder="my-gcp-project" {...field} value={field.value || ''} />
                        </FormControl>
                        <FormDescription>
                          {t('settings:connectors.bigquery.projectIdHelp', 'Optional. Derived from credentials if not set.')}
                        </FormDescription>
                      </FormItem>
                    )}
                  />
                  <FormField
                    control={form.control}
                    name="location"
                    render={({ field }) => (
                      <FormItem>
                        <FormLabel>{t('settings:connectors.bigquery.location', 'Location')}</FormLabel>
                        <FormControl>
                          <Input placeholder="US" {...field} value={field.value || ''} />
                        </FormControl>
                        <FormDescription>
                          {t('settings:connectors.bigquery.locationHelp', 'e.g. US, EU, us-central1')}
                        </FormDescription>
                      </FormItem>
                    )}
                  />
                </div>

                <FormField
                  control={form.control}
                  name="uc_connection_name"
                  render={({ field }) => (
                    <FormItem>
                      <FormLabel>{t('settings:connectors.bigquery.ucConnectionName', 'UC Connection Name')}</FormLabel>
                      <FormControl>
                        <Input placeholder="my-bigquery-connection" {...field} value={field.value || ''} />
                      </FormControl>
                      <FormDescription>
                        {t('settings:connectors.bigquery.ucConnectionNameHelp', 'Optional. Provides GCP Project ID from UC Connection metadata.')}
                      </FormDescription>
                    </FormItem>
                  )}
                />

                <Separator />
                <p className="text-sm font-medium">
                  {t('settings:connectors.bigquery.authSectionTitle', 'Authentication')}
                </p>
                <p className="text-sm text-muted-foreground">
                  {t('settings:connectors.bigquery.authSectionHelp', 'Store the GCP service account key JSON as a Databricks Secret, then reference the scope and key name below.')}
                </p>

                <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                  <FormField
                    control={form.control}
                    name="credentials_secret_scope"
                    render={({ field }) => (
                      <FormItem>
                        <FormLabel>{t('settings:connectors.bigquery.secretScope', 'Secret Scope')}</FormLabel>
                        <FormControl>
                          <Input placeholder="ontos-connectors" {...field} value={field.value || ''} />
                        </FormControl>
                      </FormItem>
                    )}
                  />
                  <FormField
                    control={form.control}
                    name="credentials_secret_key"
                    render={({ field }) => (
                      <FormItem>
                        <FormLabel>{t('settings:connectors.bigquery.secretKey', 'Secret Key')}</FormLabel>
                        <FormControl>
                          <Input placeholder="bigquery-sa-key" {...field} value={field.value || ''} />
                        </FormControl>
                      </FormItem>
                    )}
                  />
                </div>

                <FormField
                  control={form.control}
                  name="credentials_path"
                  render={({ field }) => (
                    <FormItem>
                      <FormLabel>{t('settings:connectors.bigquery.credentialsPath', 'Credentials File Path')}</FormLabel>
                      <FormControl>
                        <Input placeholder="/path/to/service-account-key.json" {...field} value={field.value || ''} />
                      </FormControl>
                      <FormDescription>
                        {t('settings:connectors.bigquery.credentialsPathHelp', 'Dev fallback: local path to a service account key JSON file.')}
                      </FormDescription>
                    </FormItem>
                  )}
                />
              </>
            )}

            {/* Databricks system connection - read only */}
            {selectedType === 'databricks' && isSystem && (
              <>
                <Separator />
                <p className="text-sm text-muted-foreground">
                  {t('settings:connectors.databricks.systemNote', 'This connection is auto-configured from environment variables and cannot be modified.')}
                </p>
              </>
            )}

            <DialogFooter className="gap-2 sm:gap-0">
              {isEditing && initialConnection && (
                <Button
                  type="button"
                  variant="outline"
                  onClick={handleTest}
                  disabled={isTesting}
                >
                  {isTesting
                    ? <Loader2 className="w-4 h-4 mr-2 animate-spin" />
                    : <HeartPulse className="w-4 h-4 mr-2" />}
                  {t('settings:connectors.testConnection', 'Test Connection')}
                </Button>
              )}
              <Button type="submit" disabled={isSubmitting || isSystem}>
                {isSubmitting && <Loader2 className="w-4 h-4 mr-2 animate-spin" />}
                {isEditing ? t('common:save', 'Save') : t('common:create', 'Create')}
              </Button>
            </DialogFooter>
          </form>
        </Form>
      </DialogContent>
    </Dialog>
  );
}
