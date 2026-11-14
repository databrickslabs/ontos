/**
 * Asset create and update errors for a retired asset type (#970), in the user's language.
 */
import { describe, it, expect, afterEach } from 'vitest';
import i18n from '@/i18n/config';
import { assetTypeErrorText } from './asset-type-error';

const RETIRED = {
  error: "Asset type 'Legacy Business Term' is retired and cannot be used for new assets.",
  errorCode: 'asset_type_retired',
  errorParams: { name: 'Legacy Business Term' },
};

describe('assetTypeErrorText', () => {
  afterEach(async () => {
    await i18n.changeLanguage('en');
  });

  it('names the retired type in the user language', async () => {
    await i18n.changeLanguage('de');
    const text = assetTypeErrorText(RETIRED, i18n.t);
    expect(text).toContain('Legacy Business Term');
    expect(text).not.toBe(RETIRED.error);
  });

  it('names the retired type in English without repeating the API text', async () => {
    await i18n.changeLanguage('en');
    expect(assetTypeErrorText(RETIRED, i18n.t)).toBe(
      "Asset type 'Legacy Business Term' is retired. Choose an active asset type.",
    );
  });

  it('shows other errors as the API sent them', () => {
    expect(assetTypeErrorText({ error: 'Boom', errorCode: null, errorParams: null }, i18n.t)).toBe('Boom');
  });

  it('uses the fallback when the API sent no text', () => {
    expect(assetTypeErrorText({ error: null, errorCode: null, errorParams: null }, i18n.t, 'Failed')).toBe('Failed');
  });
});
