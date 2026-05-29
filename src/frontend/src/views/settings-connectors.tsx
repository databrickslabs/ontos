import SettingsPageWrapper from '@/components/settings/settings-page-wrapper';
import ConnectorsSettings from '@/components/settings/connectors-settings';
import { useTranslation } from 'react-i18next';

export default function SettingsConnectorsView() {
  const { t } = useTranslation(['settings']);
  return (
    <SettingsPageWrapper title={t('settings:tabs.connectors', 'Connectors')} permissionId="settings-connectors">
      <ConnectorsSettings />
    </SettingsPageWrapper>
  );
}
