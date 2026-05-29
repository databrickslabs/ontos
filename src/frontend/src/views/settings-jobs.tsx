import SettingsPageWrapper from '@/components/settings/settings-page-wrapper';
import JobsSettings from '@/components/settings/jobs-settings';
import { useTranslation } from 'react-i18next';

export default function SettingsJobsView() {
  const { t } = useTranslation(['settings']);
  return (
    <SettingsPageWrapper title={t('settings:tabs.jobs', 'Jobs')} permissionId="settings-jobs">
      <JobsSettings />
    </SettingsPageWrapper>
  );
}
