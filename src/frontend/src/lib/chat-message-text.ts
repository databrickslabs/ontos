import type { TFunction } from 'i18next';
import type { ChatMessage } from '@/types/llm-search';

/**
 * The text of a chat message to show.
 *
 * An assistant message that reports a failed turn carries `error_code` and
 * `error_params` (the error id): it is shown in the user's language, with the
 * stored English `content` as the fallback for an unknown code. Messages
 * reloaded from a session have no code and show `content` as stored.
 */
export function chatMessageText(
  message: Pick<ChatMessage, 'content' | 'error_code' | 'error_params'>,
  t: TFunction,
): string {
  const content = message.content || '';
  if (!message.error_code) return content;
  return t(`search:chatErrors.${message.error_code}`, {
    ...(message.error_params ?? {}),
    defaultValue: content,
  }) as string;
}
