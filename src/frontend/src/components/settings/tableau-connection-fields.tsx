import type { Control, FieldValues, Path } from 'react-hook-form';
import { useWatch } from 'react-hook-form';
import { useTranslation } from 'react-i18next';

import {
  FormControl, FormDescription, FormField, FormItem, FormLabel,
} from '@/components/ui/form';
import { Input } from '@/components/ui/input';
import { Separator } from '@/components/ui/separator';
import {
  Select, SelectContent, SelectItem, SelectTrigger, SelectValue,
} from '@/components/ui/select';

export const TABLEAU_CONFIG_FIELDS = [
  'server_url', 'site_content_url', 'auth_mode',
  'client_id', 'secret_id', 'username', 'pat_name',
  'secret_name', 'ca_bundle_path', 'default_catalog',
] as const;

interface Props<T extends FieldValues> {
  // The dialog's form; only the Tableau field names are used here.
  control: Control<T>;
}

/** Tableau Cloud / Server connection settings. The secret is referenced as a Unity Catalog secret. */
export function TableauConnectionFields<T extends FieldValues>({ control }: Props<T>) {
  const { t } = useTranslation(['settings']);
  const authMode: string = useWatch({ control, name: 'auth_mode' as Path<T> }) || 'connected_app';

  const textField = (name: string, label: string, placeholder: string, help?: string) => (
    <FormField
      control={control}
      name={name as Path<T>}
      render={({ field }) => (
        <FormItem>
          <FormLabel>{label}</FormLabel>
          <FormControl>
            <Input placeholder={placeholder} {...field} value={field.value || ''} />
          </FormControl>
          {help && <FormDescription>{help}</FormDescription>}
        </FormItem>
      )}
    />
  );

  return (
    <>
      <Separator />
      <p className="text-sm font-medium">{t('settings:connectors.tableau.configTitle')}</p>

      <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
        {textField(
          'server_url',
          t('settings:connectors.tableau.serverUrl'),
          'https://10az.online.tableau.com',
          t('settings:connectors.tableau.serverUrlHelp'),
        )}
        {textField(
          'site_content_url',
          t('settings:connectors.tableau.site'),
          'mysite',
          t('settings:connectors.tableau.siteHelp'),
        )}
      </div>

      <Separator />
      <p className="text-sm font-medium">{t('settings:connectors.tableau.authSectionTitle')}</p>
      <p className="text-sm text-muted-foreground">{t('settings:connectors.tableau.authSectionHelp')}</p>

      <FormField
        control={control}
        name={'auth_mode' as Path<T>}
        render={({ field }) => (
          <FormItem>
            <FormLabel>{t('settings:connectors.tableau.authMode')}</FormLabel>
            <Select onValueChange={field.onChange} value={field.value || 'connected_app'}>
              <FormControl>
                <SelectTrigger><SelectValue /></SelectTrigger>
              </FormControl>
              <SelectContent>
                <SelectItem value="connected_app">{t('settings:connectors.tableau.authConnectedApp')}</SelectItem>
                <SelectItem value="pat">{t('settings:connectors.tableau.authPat')}</SelectItem>
              </SelectContent>
            </Select>
            <FormDescription>
              {authMode === 'pat'
                ? t('settings:connectors.tableau.authPatHelp')
                : t('settings:connectors.tableau.authConnectedAppHelp')}
            </FormDescription>
          </FormItem>
        )}
      />

      {authMode === 'pat' ? (
        textField('pat_name', t('settings:connectors.tableau.patName'), 'ontos-import')
      ) : (
        <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
          {textField('client_id', t('settings:connectors.tableau.clientId'), '00000000-0000-0000-0000-000000000000')}
          {textField('secret_id', t('settings:connectors.tableau.secretId'), '00000000-0000-0000-0000-000000000000')}
          {textField(
            'username',
            t('settings:connectors.tableau.username'),
            'svc-ontos@example.com',
            t('settings:connectors.tableau.usernameHelp'),
          )}
        </div>
      )}

      {textField(
        'secret_name',
        t('settings:connectors.tableau.secretName'),
        authMode === 'pat' ? 'main.ontos.tableau_pat' : 'main.ontos.tableau_connected_app',
        t('settings:connectors.tableau.secretNameHelp'),
      )}

      {textField(
        'default_catalog',
        t('settings:connectors.tableau.defaultCatalog'),
        'main',
        t('settings:connectors.tableau.defaultCatalogHelp'),
      )}

      {textField(
        'ca_bundle_path',
        t('settings:connectors.tableau.caBundlePath'),
        '/path/to/ca-bundle.pem',
        t('settings:connectors.tableau.caBundlePathHelp'),
      )}
    </>
  );
}
