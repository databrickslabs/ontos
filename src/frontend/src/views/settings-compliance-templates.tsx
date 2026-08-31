import SettingsPageWrapper from '@/components/settings/settings-page-wrapper';
import ComplianceTemplatesSettings from '@/components/settings/compliance-templates-settings';
import { useTranslation } from 'react-i18next';

export default function SettingsComplianceTemplatesView() {
  const { t } = useTranslation(['settings']);
  return (
    <SettingsPageWrapper
      title={t('settings:tabs.complianceTemplates', 'Compliance Templates')}
      permissionId="settings-compliance-templates"
    >
      <ComplianceTemplatesSettings />
    </SettingsPageWrapper>
  );
}
