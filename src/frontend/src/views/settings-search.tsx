import SettingsPageWrapper from '@/components/settings/settings-page-wrapper';
import SearchConfigEditor from '@/components/settings/search-config-editor';
import { useTranslation } from 'react-i18next';

export default function SettingsSearchView() {
  const { t } = useTranslation(['settings']);
  return (
    <SettingsPageWrapper title={t('settings:tabs.search', 'Search')} permissionId="settings-search">
      <SearchConfigEditor />
    </SettingsPageWrapper>
  );
}
