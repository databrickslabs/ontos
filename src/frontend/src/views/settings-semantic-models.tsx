import SettingsPageWrapper from '@/components/settings/settings-page-wrapper';
import SemanticModelsSettings from '@/components/settings/semantic-models-settings';
import { useTranslation } from 'react-i18next';

export default function SettingsSemanticModelsView() {
  const { t } = useTranslation(['settings']);
  return (
    <SettingsPageWrapper title={t('settings:tabs.rdfSources', 'RDF Sources')} permissionId="settings-semantic-models">
      <SemanticModelsSettings />
    </SettingsPageWrapper>
  );
}
