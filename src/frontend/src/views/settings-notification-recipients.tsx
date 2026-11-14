import SettingsPageWrapper from '@/components/settings/settings-page-wrapper';
import NotificationRecipientsSettings from '@/components/settings/notification-recipients-settings';
import { useTranslation } from 'react-i18next';

export default function SettingsNotificationRecipientsView() {
  const { t } = useTranslation(['settings']);
  return (
    <SettingsPageWrapper
      title={t('settings:tabs.notificationRecipients', 'Notification Recipients')}
      permissionId="settings-roles"
    >
      <NotificationRecipientsSettings />
    </SettingsPageWrapper>
  );
}
