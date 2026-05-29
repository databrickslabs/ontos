import SettingsPageWrapper from '@/components/settings/settings-page-wrapper';
import UICustomizationSettings from '@/components/settings/ui-customization-settings';
import { useTranslation } from 'react-i18next';

export default function SettingsUiView() {
  const { t } = useTranslation(['settings']);
  return (
    <SettingsPageWrapper title={t('settings:tabs.uiCustomization', 'UI Customization')} permissionId="settings-ui">
      <UICustomizationSettings />
    </SettingsPageWrapper>
  );
}
