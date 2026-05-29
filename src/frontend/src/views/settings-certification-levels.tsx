import SettingsPageWrapper from '@/components/settings/settings-page-wrapper';
import CertificationLevelsSettings from '@/components/settings/certification-levels-settings';
import { useTranslation } from 'react-i18next';

export default function SettingsCertificationLevelsView() {
  const { t } = useTranslation(['settings']);
  return (
    <SettingsPageWrapper title={t('settings:tabs.certificationLevels', 'Certification Levels')} permissionId="settings-certification-levels">
      <CertificationLevelsSettings />
    </SettingsPageWrapper>
  );
}
