import { beforeAll, describe, expect, it } from 'vitest';
import i18next from 'i18next';

import en from '@/i18n/locales/en/workflowDefaults.json';
import pt from '@/i18n/locales/pt/workflowDefaults.json';
import { defaultTextKey, translateDefaultText } from './workflow-default-texts';

const i18n = i18next.createInstance();

beforeAll(async () => {
  await i18n.init({
    lng: 'pt',
    fallbackLng: 'en',
    resources: { en: { workflowDefaults: en }, pt: { workflowDefaults: pt } },
  });
});

describe('translateDefaultText', () => {
  it('translates a shipped default text into the user language', () => {
    expect(translateDefaultText(i18n.t, i18n, 'Enter a reason')).toBe('Informe um motivo');
    expect(translateDefaultText(i18n.t, i18n, 'Why do you need access?')).toBe(
      'Por que você precisa de acesso?',
    );
  });

  it('shows a text an admin changed as written', () => {
    expect(translateDefaultText(i18n.t, i18n, 'Enter a reason (required)')).toBe(
      'Enter a reason (required)',
    );
  });

  it('leaves empty values alone', () => {
    expect(translateDefaultText(i18n.t, i18n, undefined)).toBeUndefined();
    expect(translateDefaultText(i18n.t, i18n, '')).toBe('');
  });

  it('finds the key of a shipped text, ignoring surrounding spaces', () => {
    expect(defaultTextKey(i18n, '  Request access ')).toBe('requestAccess.title');
    expect(defaultTextKey(i18n, 'Something else')).toBeUndefined();
  });

  it("translates a shipped fail step's message", () => {
    expect(translateDefaultText(i18n.t, i18n, 'Access request was denied')).toBe(
      'A solicitação de acesso foi negada',
    );
    expect(defaultTextKey(i18n, 'Table name cannot be a SQL reserved word')).toBe(
      'failMessages.tablePreCreation.reservedWord',
    );
  });

  it('falls back to the configured text when a language has no entry', async () => {
    const other = i18next.createInstance();
    await other.init({ lng: 'xx', fallbackLng: false, resources: { en: { workflowDefaults: en } } });
    expect(translateDefaultText(other.t, other, 'Request review')).toBe('Request review');
  });
});
