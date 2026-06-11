import SettingsPageWrapper from '@/components/settings/settings-page-wrapper';
import MaturityLevelsSettings from '@/components/settings/maturity-levels-settings';
import { useTranslation } from 'react-i18next';

export default function SettingsMaturityLevelsView() {
  const { t } = useTranslation(['settings']);
  return (
    <SettingsPageWrapper title={t('settings:tabs.maturityLevels', 'Maturity Levels')} permissionId="settings-maturity-levels">
      <MaturityLevelsSettings />
    </SettingsPageWrapper>
  );
}
