import { describe, it, expect, afterEach } from 'vitest';
import i18n from '@/i18n/config';
import { chatMessageText } from './chat-message-text';

const failed = {
  content:
    'I encountered an error while processing your request. Please try rephrasing your question or try again. The details are in the server log (error id abc123def456).',
  error_code: 'chat_failed',
  error_params: { errorId: 'abc123def456' },
};

describe('chatMessageText', () => {
  afterEach(async () => {
    await i18n.changeLanguage('en');
  });

  it('shows a failed turn in the user language, with its error id', async () => {
    await i18n.changeLanguage('pt');
    expect(chatMessageText(failed, i18n.t)).toBe(
      'Ocorreu um erro ao processar sua solicitação. Tente reformular a pergunta ou tente novamente. Os detalhes estão no log do servidor (id do erro abc123def456).',
    );
  });

  it('keeps the stored text for an unknown code and for messages without a code', async () => {
    await i18n.changeLanguage('pt');
    expect(chatMessageText({ ...failed, error_code: 'something_new' }, i18n.t)).toBe(failed.content);
    expect(chatMessageText({ content: 'Here are 3 data products.' }, i18n.t)).toBe(
      'Here are 3 data products.',
    );
    expect(chatMessageText({ content: null }, i18n.t)).toBe('');
  });
});
