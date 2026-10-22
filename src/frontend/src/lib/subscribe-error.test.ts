import { afterEach, describe, expect, it } from 'vitest';

import i18n from '@/i18n/config';
import { subscribeErrorText, subscribeResponseErrorText } from './subscribe-error';

afterEach(async () => {
  await i18n.changeLanguage('en');
});

const detail = {
  code: 'product_not_subscribable',
  message:
    "Cannot subscribe to Old Product in status 'deprecated'. "
    + 'Product must be in one of: active, certified',
  params: { status: 'deprecated', productName: 'Old Product' },
};

describe('subscribeErrorText', () => {
  it('translates the refusal in English with the status label', () => {
    expect(subscribeErrorText(detail, i18n.t, 'fallback')).toBe(
      "Cannot subscribe to 'Old Product': its status is 'Deprecated'. "
      + 'Only active or certified products accept new subscriptions.',
    );
  });

  it('translates the refusal in Portuguese', async () => {
    await i18n.changeLanguage('pt');
    const text = subscribeErrorText(detail, i18n.t, 'fallback');
    expect(text).toContain("Não é possível assinar 'Old Product'");
    expect(text).not.toContain('Cannot subscribe');
    expect(text).not.toContain('{{');
  });

  it('shows the message of an unknown code, a plain text, or the fallback', () => {
    expect(subscribeErrorText({ code: 'x', message: 'Other' }, i18n.t, 'fb')).toBe('Other');
    expect(subscribeErrorText('Plain', i18n.t, 'fb')).toBe('Plain');
    expect(subscribeErrorText(undefined, i18n.t, 'fb')).toBe('fb');
  });
});

describe('subscribeResponseErrorText', () => {
  it('translates a useApi error response in Portuguese', async () => {
    await i18n.changeLanguage('pt');
    const text = subscribeResponseErrorText(
      { error: detail.message, errorCode: detail.code, errorParams: detail.params },
      i18n.t,
      'fb',
    );
    expect(text).toContain("Não é possível assinar 'Old Product'");
    expect(text).toContain("'Obsoleto'");
  });
});
