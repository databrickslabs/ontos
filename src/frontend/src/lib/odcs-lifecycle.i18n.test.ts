/**
 * Contract statuses in the "Change Status" dialog come from the lifecycle
 * config (English); they are shown through data-contracts:status.*,
 * data-contracts:statusDescriptions.* and
 * data-contracts:requests.statusChange.recommended.* in every locale.
 */
import { describe, expect, it } from 'vitest';
import i18n from '@/i18n/config';
import {
  ALLOWED_TRANSITIONS,
  getRecommendedAction,
  getRecommendedActionText,
  getStatusText,
} from './odcs-lifecycle';

const LOCALES = import.meta.glob('@/i18n/locales/*/data-contracts.json', { eager: true }) as Record<
  string,
  { default: Record<string, any> }
>;

const STATUSES = Object.keys(ALLOWED_TRANSITIONS);

describe('contract status texts', () => {
  it('shows labels, descriptions and the recommended action in the UI language', async () => {
    await i18n.changeLanguage('pt');
    try {
      expect(getStatusText('proposed', i18n.t)).toEqual({
        label: 'Proposto',
        description: 'Enviado para avaliação de revisão',
      });
      expect(getStatusText('DEPRECATED', i18n.t).label).toBe('Obsoleto');
      expect(getRecommendedActionText('draft', i18n.t)).toBe(
        'Envie para revisão (Proposto) quando estiver pronto',
      );
      expect(getRecommendedActionText('retired', i18n.t)).toBeNull();
    } finally {
      await i18n.changeLanguage('en');
    }
  });

  it('keeps the English texts in English', () => {
    expect(getStatusText('draft', i18n.t)).toEqual({
      label: 'Draft',
      description: 'Under development, not yet submitted for review',
    });
    expect(getRecommendedActionText('active', i18n.t)).toBe(getRecommendedAction('active'));
  });

  it.each(Object.keys(LOCALES))('%s has a label, a description and a recommendation for every status', (path) => {
    const messages = LOCALES[path].default;
    for (const status of STATUSES) {
      expect(messages.status?.[status], `${path} status.${status}`).toBeTruthy();
      expect(messages.statusDescriptions?.[status], `${path} statusDescriptions.${status}`).toBeTruthy();
      if (getRecommendedAction(status)) {
        expect(
          messages.requests?.statusChange?.recommended?.[status],
          `${path} requests.statusChange.recommended.${status}`,
        ).toBeTruthy();
      }
    }
  });
});
