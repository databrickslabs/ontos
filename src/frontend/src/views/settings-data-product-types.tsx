import SettingsPageWrapper from '@/components/settings/settings-page-wrapper';
import DataProductTypesSettings, {
  DATA_PRODUCT_TYPES_PERMISSION,
} from '@/components/settings/data-product-types-settings';
import { useTranslation } from 'react-i18next';

export default function SettingsDataProductTypesView() {
  const { t } = useTranslation(['settings']);
  return (
    <SettingsPageWrapper
      title={t('settings:tabs.dataProductTypes', 'Data Product Types')}
      permissionId={DATA_PRODUCT_TYPES_PERMISSION}
    >
      <DataProductTypesSettings />
    </SettingsPageWrapper>
  );
}
