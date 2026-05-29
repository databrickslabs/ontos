import SettingsPageWrapper from '@/components/settings/settings-page-wrapper';
import RolesSettings from '@/components/settings/roles-settings';
import { useTranslation } from 'react-i18next';

export default function SettingsRolesView() {
  const { t } = useTranslation(['settings']);
  return (
    <SettingsPageWrapper title={t('settings:tabs.roles', 'App Roles')} permissionId="settings-roles">
      <RolesSettings />
    </SettingsPageWrapper>
  );
}
