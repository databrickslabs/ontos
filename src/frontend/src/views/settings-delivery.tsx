import SettingsPageWrapper from '@/components/settings/settings-page-wrapper';
import DeliverySettings from '@/components/settings/delivery-settings';
import { useTranslation } from 'react-i18next';

export default function SettingsDeliveryView() {
  const { t } = useTranslation(['settings']);
  return (
    <SettingsPageWrapper title={t('settings:tabs.delivery', 'Delivery Modes')} permissionId="settings-delivery">
      <DeliverySettings />
    </SettingsPageWrapper>
  );
}
