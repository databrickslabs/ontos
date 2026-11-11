import { afterEach, describe, expect, it } from 'vitest';
import i18n from '@/i18n/config';
import { notificationDescription, notificationTitle } from './notification-text';

const t = i18n.t.bind(i18n);

const english = {
  title: 'Status change not applied',
  description: "The request to change the status from 'draft' to 'proposed' was approved, but ...",
};

const withKeys = {
  ...english,
  data: {
    i18n: {
      title: 'notifications:statusChangeNotApplied.title',
      description: 'notifications:statusChangeNotApplied.statusChanged',
      params: { fromStatus: 'draft', toStatus: 'proposed', currentStatus: 'sandbox' },
    },
  },
};

describe('notification text', () => {
  afterEach(() => {
    i18n.changeLanguage('en');
  });

  it('shows the stored texts when there are no keys', () => {
    expect(notificationTitle(english, t)).toBe(english.title);
    expect(notificationDescription(english, t)).toBe(english.description);
    expect(notificationDescription({ title: 'Job', message: 'Running' }, t)).toBe('Running');
  });

  it('translates title and description with their params', async () => {
    expect(notificationTitle(withKeys, t)).toBe('Status change not applied');
    expect(notificationDescription(withKeys, t)).toContain("the status is now 'sandbox'");

    await i18n.changeLanguage('de');
    expect(notificationTitle(withKeys, t)).toBe('Statusänderung nicht übernommen');
    expect(notificationDescription(withKeys, t)).toContain('„sandbox“');
  });

  it('falls back to the stored text for an unknown key', () => {
    const unknown = { ...english, data: { i18n: { title: 'notifications:nope.title' } } };
    expect(notificationTitle(unknown, t)).toBe(english.title);
  });

  it('reads data sent as a JSON string', () => {
    const asString = { ...english, data: JSON.stringify(withKeys.data) as unknown as Record<string, unknown> };
    expect(notificationDescription(asString, t)).toContain("is now 'sandbox'");
    expect(notificationTitle({ ...english, data: 'not json' as unknown as Record<string, unknown> }, t))
      .toBe(english.title);
  });

  it('has every key in every locale', () => {
    const keys = [
      'statusChangeNotApplied.title', 'statusChangeNotApplied.statusChanged',
      'statusChangeNotApplied.refused', 'contractStatusNotChanged.title',
      'contractStatusNotChanged.notUnderReview', 'contractStatusNotChanged.notApplied',
    ];
    for (const lng of ['en', 'de', 'es', 'fr', 'it', 'ja', 'nl', 'pt']) {
      for (const key of keys) {
        expect(i18n.exists(`notifications:${key}`, { lng }), `${lng} ${key}`).toBe(true);
      }
    }
  });

  it('translates the statuses and a coded refusal reason (gate blocked a review decision)', async () => {
    const refused = {
      title: 'Contract status not changed',
      description:
        "Your review decision was recorded, but the contract was not set to 'approved': " +
        "Status transition from 'proposed' to 'approved' blocked by workflow: Contract Gate: Not yet",
      data: {
        i18n: {
          title: 'notifications:contractStatusNotChanged.title',
          description: 'notifications:contractStatusNotChanged.notApplied',
          params: {
            toStatus: 'approved',
            reason: "Status transition from 'proposed' to 'approved' blocked by workflow: Contract Gate: Not yet",
          },
          statusNamespace: 'data-contracts',
          error: {
            code: 'status_change_blocked',
            message: "Status transition from 'proposed' to 'approved' blocked by workflow: Contract Gate: Not yet",
            params: {
              fromStatus: 'proposed',
              toStatus: 'approved',
              reasons: [{ workflow: 'Contract Gate', text: 'Not yet' }],
            },
          },
        },
      },
    };
    await i18n.changeLanguage('pt');
    const text = notificationDescription(refused, t);
    expect(text).toContain('"Aprovado"');
    expect(text).toContain('A mudança de status de Proposto para Aprovado foi bloqueada por um workflow: Contract Gate: Not yet');
    expect(text).not.toContain('Status transition');
  });

  it('keeps the English reason when the refusal has no code', async () => {
    const plain = {
      title: 'Status change not applied',
      description: "Your request to change the status to 'deprecated' was approved, but ...",
      data: {
        i18n: {
          title: 'notifications:statusChangeNotApplied.title',
          description: 'notifications:statusChangeNotApplied.refused',
          params: { toStatus: 'deprecated', reason: 'Invalid transition' },
          statusNamespace: 'data-products',
        },
      },
    };
    await i18n.changeLanguage('pt');
    const text = notificationDescription(plain, t);
    expect(text).toContain('Invalid transition');
    expect(text).not.toContain('"deprecated"');
  });
});
