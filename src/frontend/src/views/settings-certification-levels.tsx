import SettingsPageWrapper from '@/components/settings/settings-page-wrapper';
import CertificationLevelsSettings from '@/components/settings/certification-levels-settings';
import CertifiedDeprecationGuardSettings
  from '@/components/settings/certified-deprecation-guard-settings';
import { useTranslation } from 'react-i18next';

export default function SettingsCertificationLevelsView() {
  const { t } = useTranslation(['settings']);
  return (
    <SettingsPageWrapper title={t('settings:tabs.certificationLevels', 'Certification Levels')} permissionId="settings-certification-levels">
      <div className="space-y-6">
        <CertificationLevelsSettings />
        <CertifiedDeprecationGuardSettings />
      </div>
    </SettingsPageWrapper>
  );
}
