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
});
