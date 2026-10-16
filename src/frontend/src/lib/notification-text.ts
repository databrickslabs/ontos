import type { TFunction } from 'i18next';
import type { Notification } from '@/types/notification';

/**
 * i18n keys a notification may carry in `data.i18n` (see the backend's
 * `src/common/notification_i18n.py`): `<namespace>:<key>` keys for its title
 * and description, and the values of their `{{placeholders}}`. The stored
 * English texts are the fallback.
 *
 * A description of several lines (an approval step's "Approval Required")
 * comes as `descriptionLines`: one text per line, each with its key, its
 * params and its English text; a param can itself be such a text.
 */
export interface NotificationI18n {
  title?: string;
  description?: string;
  params?: Record<string, string>;
  descriptionLines?: I18nText[];
}

export interface I18nText {
  key?: string;
  params?: Record<string, unknown>;
  text?: string;
}

type NotificationText = Pick<Notification, 'title' | 'description' | 'message' | 'data'>;

export function notificationI18n(notification: NotificationText): NotificationI18n | null {
  let data: unknown = notification.data;
  if (typeof data === 'string') {
    try {
      data = JSON.parse(data);
    } catch {
      return null;
    }
  }
  const i18n = (data as { i18n?: unknown } | null | undefined)?.i18n;
  return i18n && typeof i18n === 'object' ? (i18n as NotificationI18n) : null;
}

function translate(t: TFunction, key: string | undefined, fallback: string, params?: Record<string, unknown>) {
  if (!key) return fallback;
  return t(key, { ...(params || {}), defaultValue: fallback }) as string;
}

function isI18nText(value: unknown): value is I18nText {
  return !!value && typeof value === 'object' && ('key' in value || 'text' in value);
}

function translateText(t: TFunction, text: I18nText): string {
  const params = Object.fromEntries(
    Object.entries(text.params || {}).map(([name, value]) => [
      name, isI18nText(value) ? translateText(t, value) : value,
    ]),
  );
  return translate(t, text.key, text.text ?? '', params);
}

/** The notification's title in the user's language, or its stored text. */
export function notificationTitle(notification: NotificationText, t: TFunction): string {
  const i18n = notificationI18n(notification);
  return translate(t, i18n?.title, notification.title, i18n?.params);
}

/** The notification's description (or message) in the user's language, or its stored text. */
export function notificationDescription(notification: NotificationText, t: TFunction): string {
  const fallback = notification.description || notification.message || '';
  const i18n = notificationI18n(notification);
  if (Array.isArray(i18n?.descriptionLines) && i18n.descriptionLines.length) {
    return i18n.descriptionLines
      .map(line => (isI18nText(line) ? translateText(t, line) : String(line ?? '')))
      .join('\n');
  }
  return translate(t, i18n?.description, fallback, i18n?.params);
}
