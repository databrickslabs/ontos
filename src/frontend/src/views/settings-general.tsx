import SettingsPageWrapper from '@/components/settings/settings-page-wrapper';
import GeneralSettings from '@/components/settings/general-settings';
import { useTranslation } from 'react-i18next';

export default function SettingsGeneralView() {
  const { t } = useTranslation(['settings']);
  return (
    <SettingsPageWrapper title={t('settings:tabs.general', 'General')} permissionId="settings-general">
      <GeneralSettings />
    </SettingsPageWrapper>
  );
}
