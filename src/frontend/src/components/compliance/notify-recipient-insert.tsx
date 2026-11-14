import { useEffect, useState } from 'react';
import { useTranslation } from 'react-i18next';

import { Label } from '@/components/ui/label';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import { useApi } from '@/hooks/use-api';
import { insertTextAtCursor, notifyRecipientText } from '@/lib/insert-text-at-cursor';
import type { AvailableNotificationRecipient } from '@/types/notification-recipients';

interface NotifyRecipientInsertProps {
  /** Id of the rule textarea (uncontrolled) the NOTIFY line is inserted into */
  textareaId: string;
}

/** Offers the Notification Recipients the current user may name, and inserts a NOTIFY for one (#1450). */
export function NotifyRecipientInsert({ textareaId }: NotifyRecipientInsertProps) {
  const { t } = useTranslation(['compliance']);
  const { get } = useApi();
  const [options, setOptions] = useState<AvailableNotificationRecipient[]>([]);

  useEffect(() => {
    let active = true;
    get<AvailableNotificationRecipient[]>('/api/compliance/notification-recipients/available').then((response) => {
      if (active) setOptions(response.error ? [] : response.data ?? []);
    });
    return () => {
      active = false;
    };
  }, [get]);

  const insert = (name: string) => {
    const textarea = document.getElementById(textareaId) as HTMLTextAreaElement | null;
    if (!textarea) return;
    const next = insertTextAtCursor(
      textarea.value, textarea.selectionStart, textarea.selectionEnd, notifyRecipientText(name),
    );
    textarea.value = next.value;
    textarea.setSelectionRange(next.cursor, next.cursor);
    textarea.focus();
  };

  return (
    <div className="space-y-1">
      <Label>{t('compliance:form.notifyRecipients')}</Label>
      {options.length === 0 ? (
        <p className="text-xs text-muted-foreground">{t('compliance:form.noNotifyRecipients')}</p>
      ) : (
        <Select onValueChange={insert} value="">
          <SelectTrigger className="w-full md:w-80" aria-label={t('compliance:form.notifyRecipients')}>
            <SelectValue placeholder={t('compliance:form.insertNotifyRecipient')} />
          </SelectTrigger>
          <SelectContent>
            {options.map((option) => (
              <SelectItem key={option.id} value={option.name}>
                {option.name}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      )}
      <p className="text-xs text-muted-foreground">{t('compliance:form.notifyRecipientsHint')}</p>
    </div>
  );
}

export default NotifyRecipientInsert;
