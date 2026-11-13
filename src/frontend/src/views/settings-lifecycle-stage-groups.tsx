import SettingsPageWrapper from '@/components/settings/settings-page-wrapper';
import LifecycleStageGroupsSettings from '@/components/settings/lifecycle-stage-groups-settings';
import { useTranslation } from 'react-i18next';

export default function SettingsLifecycleStageGroupsView() {
  const { t } = useTranslation(['lifecycle']);
  return (
    <SettingsPageWrapper
      title={t('lifecycle:settings.tab', 'Lifecycle Stage Groups')}
      permissionId="settings-lifecycle-stage-groups"
    >
      <LifecycleStageGroupsSettings />
    </SettingsPageWrapper>
  );
}
