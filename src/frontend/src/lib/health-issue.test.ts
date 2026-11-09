/**
 * Startup problems from /api/health in the user's language.
 */
import { describe, it, expect, afterEach } from 'vitest';
import i18n from '@/i18n/config';
import { healthIssueText, retryDetailText } from './health-issue';

describe('healthIssueText', () => {
  afterEach(async () => {
    await i18n.changeLanguage('en');
  });

  it('translates a known code', async () => {
    await i18n.changeLanguage('pt');
    expect(
      healthIssueText({ code: 'seeding_failed', message: 'Default roles ...', params: {} }, i18n.t),
    ).toBe('Não foi possível criar os papéis, times ou projetos padrão. A causa está nos logs do servidor.');
  });

  it('shows the English message of an unknown code', () => {
    expect(healthIssueText({ code: 'something_new', message: 'Something new failed.' }, i18n.t)).toBe(
      'Something new failed.',
    );
  });
});

describe('retryDetailText', () => {
  it('reads a coded detail and ignores anything else', () => {
    expect(
      retryDetailText({ code: 'database_unavailable', message: 'x', params: {} }, i18n.t),
    ).toBe('The metadata database could not be initialized. The cause is in the server logs.');
    expect(retryDetailText('psycopg2.OperationalError: ...', i18n.t)).toBeNull();
    expect(retryDetailText(undefined, i18n.t)).toBeNull();
  });
});
