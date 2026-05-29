import SettingsPageWrapper from '@/components/settings/settings-page-wrapper';
import TagsSettings from '@/components/settings/tags-settings';
import { useTranslation } from 'react-i18next';

export default function SettingsTagsView() {
  const { t } = useTranslation(['settings']);
  return (
    <SettingsPageWrapper title={t('settings:tabs.tags', 'Tags')} permissionId="settings-tags">
      <TagsSettings />
    </SettingsPageWrapper>
  );
}
