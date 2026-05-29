import SettingsPageWrapper from '@/components/settings/settings-page-wrapper';
import GitSettings from '@/components/settings/git-settings';
import { useTranslation } from 'react-i18next';

export default function SettingsGitView() {
  const { t } = useTranslation(['settings']);
  return (
    <SettingsPageWrapper title={t('settings:tabs.git', 'Git')} permissionId="settings-git">
      <GitSettings />
    </SettingsPageWrapper>
  );
}
